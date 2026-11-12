"""Regressão da conversa real: saudações fragmentadas antes da disponibilidade.

Exercita worker, agrupamento, geração determinística, persistência e entrega.
Somente a identidade resolvida, o provider e os transportes externos são isolados.
"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-saudacoes-1234567890")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.agendamento import Agendamento
from app.models.alerta_interno import AlertaInterno
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import (
    WhatsAppBotConversaEstado as Estado,
    WhatsAppBotContextoSelecao,
    WhatsAppBotJob as Job,
    WhatsAppBotResposta as Resposta,
    WhatsAppBotSolicitacao as Pedido,
)
from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput
from app.services import whatsapp_bot_gates as gates
from app.services import whatsapp_bot_generation as generation
from app.services import whatsapp_bot_handoff_service as handoff
from app.services import whatsapp_bot_worker_service as worker
from app.services.whatsapp_bot_agendamento import KEY as COLETA_KEY
from app.services.whatsapp_bot_disponibilidade import KEY as CONVITE_KEY
from app.services.whatsapp_bot_providers import GeneratedReply


IDENTITY = "558588018899"
QUESTION = "Qual a disponibilidade pra eco"


def http_response(payload, status=200):
    response = Mock(status_code=status)
    response.json.return_value = payload
    return response


class SaudacoesAgrupadasWorkerTests(unittest.TestCase):
    def setUp(self):
        guard = patch("app.services.whatsapp_bot_delivery_service.resposta_contexto_vigente", return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine = create_engine(f"sqlite:///{tmp.name}/worker.db")
        self.addCleanup(self.engine.dispose)
        for model in (WhatsAppBotContextoSelecao, Configuracao, Estado, Job, Resposta, Pedido, AlertaInterno, Agendamento):
            model.__table__.create(self.engine)
        factory = sessionmaker(bind=self.engine, autoflush=False)
        self.db = factory()
        self.addCleanup(self.db.close)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.message_id = 0
        self.db.add(Configuracao(whatsapp_bot_atendimento_habilitado=True))
        self.estado = Estado(wa_identity=IDENTITY, modo="auto")
        self.db.add(self.estado)
        self.old_data = {
            "clinica_id": 9, "status": "encaminhada",
            "dados": {"exame": "eletro", "paciente": "Pet antigo",
                      "tutor": "Tutor antigo", "preferencia": "segunda à tarde"},
        }
        self.source = Resposta(
            job_id=100, wa_identity=IDENTITY, conversation_id="49", clinica_id=9,
            decisao="sent", texto_gerado="Pedido anterior", texto_enviado="Pedido anterior",
            tools_usadas=json.dumps({COLETA_KEY: self.old_data}),
            created_at=self.now - timedelta(hours=5),
        )
        self.db.add(self.source)
        self.db.flush()
        self.pedido = Pedido(
            resposta_id=self.source.id, wa_identity=IDENTITY, conversation_id="49",
            clinica_id=9, resumo="Pedido anterior cancelado", status="cancelado",
            responsavel_id=1, prazo_em=self.now, created_at=self.now,
            updated_at=self.now, versao=3, historico="[]",
        )
        self.db.add(self.pedido)
        self.db.commit()
        self.pedido_before = self.pedido_snapshot()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {
            "WHATSAPP_BOT_ENABLED": True, "WHATSAPP_BOT_AUTO_SEND_ENABLED": True,
            "WHATSAPP_AGENDA_SERVICE_URL": "http://node.test",
            "WHATSAPP_AGENDA_INTERNAL_TOKEN": "unit-test-token",
            "WHATSAPP_BOT_HISTORICO_MENSAGENS": 8,
        }.items():
            self.stack.enter_context(patch.object(gates.settings, key, value))
        self.stack.enter_context(patch.object(gates, "SessionLocal", factory))
        self.stack.enter_context(patch.object(generation, "_resolver_contexto", return_value={
            "resolution": "matched", "match_type": "clinica",
            "clinicas": [{"id": 9, "nome": "Clínica teste"}],
        }))
        self.provider = Mock()
        self.provider.generate.return_value = GeneratedReply(
            output=WhatsAppBotReplyOutput(intent="outro", texto="A equipe precisa conferir."),
            model="mock", input_tokens=1, output_tokens=1,
        )
        self.provider_factory = self.stack.enter_context(patch.object(
            generation, "get_whatsapp_bot_reply_provider", return_value=self.provider,
        ))
        self.get = self.stack.enter_context(patch.object(worker.httpx, "get"))
        self.post = self.stack.enter_context(patch.object(
            worker.httpx, "post", return_value=http_response({"status": "sent"}, 201),
        ))
        self.pending = self.stack.enter_context(patch.object(
            worker.httpx, "patch", return_value=http_response({}),
        ))
        self.push = self.stack.enter_context(patch.object(handoff, "send_whatsapp_message_push_notification"))

    def message(self, body, seconds_ago=0, *, from_me=False):
        self.message_id += 1
        return {
            "wa_message_id": f"message-{self.message_id}", "type": "text",
            "body": body, "from_me": from_me, "origem": "bot" if from_me else None,
            "created_at": (self.now - timedelta(seconds=seconds_ago)).isoformat(),
        }

    def run_job(self, messages, *, agent=None, inbound_hours=0):
        current = messages[-1]
        job = Job(
            wa_identity=IDENTITY, conversation_id="49", wa_message_id=current["wa_message_id"],
            status="processing", attempts=0, scheduled_for=self.now,
        )
        self.db.add(job)
        self.db.commit()
        conversation = {
            "id": "49", "last_agent_id": agent,
            "last_inbound_at": (self.now - timedelta(hours=inbound_hours)).isoformat(),
            **{f"last_message_{key}": current[key] for key in ("body", "wa_message_id", "from_me", "type", "origem")},
            "last_message_at": current["created_at"],
        }
        self.get.side_effect = [http_response({"data": [conversation]}), http_response({
            "data": messages, "pagination": {"total": len(messages)},
        })]
        self.assertEqual(worker._process_job(self.db, job), "done")
        self.db.commit()
        self.assertEqual(job.status, "done")
        return self.db.query(Resposta).filter_by(job_id=job.id).one()

    def pedido_snapshot(self):
        return {column.name: getattr(self.pedido, column.name) for column in Pedido.__table__.columns}

    def assert_no_business_mutations(self):
        self.db.refresh(self.pedido)
        self.db.refresh(self.source)
        self.assertEqual(self.pedido_snapshot(), self.pedido_before)
        self.assertEqual(json.loads(self.source.tools_usadas), {COLETA_KEY: self.old_data})
        self.assertEqual(self.db.query(Pedido).count(), 1)
        self.assertEqual(self.db.query(Agendamento).count(), 0)

    def assert_no_handoff(self):
        self.db.refresh(self.estado)
        self.assertIsNone(self.estado.pausado_ate)
        self.assertIsNone(self.estado.handoff_motivo)
        self.assertEqual(self.db.query(AlertaInterno).count(), 0)
        self.pending.assert_not_called()
        self.push.assert_not_called()

    def test_conversa_real_quatro_mensagens_convite_e_sim_sem_modelo(self):
        # O primeiro "Ola" fica fora dos dois minutos quando a pergunta chega;
        # "Oi" e "Boa tarde" permanecem, como na falha de produção.
        messages = [self.message("Ola", 130), self.message("Oi", 100),
                    self.message("Boa tarde", 60), self.message(QUESTION)]
        for index in range(3):
            result = self.run_job(messages[:index + 1])
            self.assertEqual((result.decisao, result.motivo), ("suppressed", "sem_pergunta"))
            self.assert_no_handoff()
        invitation = self.run_job(messages)
        self.assertEqual((invitation.decisao, invitation.motivo), ("sent", "enviado_auto"))
        self.assertIn(CONVITE_KEY, json.loads(invitation.tools_usadas))
        self.assertIn("nova solicitação de eco", invitation.texto_enviado)
        self.assertIn("Nenhum horário foi reservado", invitation.texto_enviado)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args.kwargs["json"]["metadata"], {
            "origem": "bot", "source": "bot_auto", "resposta_id": str(invitation.id),
            "idempotency_key": f"whatsapp-bot-resposta-{invitation.id}",
            "inbound_wa_message_id": messages[-1]["wa_message_id"],
        })
        self.assert_no_handoff()
        self.assert_no_business_mutations()

        messages += [self.message(invitation.texto_enviado, -1, from_me=True), self.message("sim", -2)]
        answer = self.run_job(messages)
        self.assertEqual((answer.decisao, answer.motivo), ("sent", "enviado_auto"))
        state = json.loads(answer.tools_usadas)[COLETA_KEY]
        self.assertEqual(state["dados"], {"exame": "eco"})
        self.assertEqual(state["origens"], {"exame": "mensagem_cliente"})
        self.assertEqual(state["status"], "coletando")
        self.assertEqual(state["fila_anterior_id"], self.pedido.id)
        self.assertIn("nome do paciente", answer.texto_enviado)
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.post.call_args.kwargs["json"]["metadata"], {
            "origem": "bot", "source": "bot_auto", "resposta_id": str(answer.id),
            "idempotency_key": f"whatsapp-bot-resposta-{answer.id}",
            "inbound_wa_message_id": messages[-1]["wa_message_id"],
        })
        self.provider_factory.assert_not_called()
        self.provider.generate.assert_not_called()
        self.assert_no_handoff()
        self.assert_no_business_mutations()

    def test_worker_suggest_persiste_convite_sem_enviar(self):
        # O worker continua lendo a conversa do Node, mas a decisão em
        # suggest persiste somente um rascunho mesmo com envio auto habilitado.
        self.estado.modo = "suggest"
        self.db.commit()
        result = self.run_job([
            self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION),
        ])
        self.assertEqual((result.decisao, result.motivo), ("draft", "continuidade_administrativa"))
        self.assertIn(CONVITE_KEY, json.loads(result.tools_usadas))
        self.assertIn("nova solicitação de eco", result.texto_gerado)
        self.assertIsNone(result.texto_enviado)
        self.assertEqual(result.clinica_id, 9)
        self.assertEqual(self.get.call_count, 2)
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.provider.generate.assert_not_called()
        self.assert_no_handoff()
        self.assert_no_business_mutations()

    def test_fragmento_emergencia_120_segundos_mantem_prioridade(self):
        self.estado.pausado_ate = self.now + timedelta(hours=1)
        self.db.commit()
        messages = [self.message("Meu pet está com falta de ar", 120),
                    self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION)]
        result = self.run_job(messages, agent=7, inbound_hours=25)
        self.assertEqual((result.decisao, result.motivo), ("handoff", "emergencia"))
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_business_mutations()

    def test_fragmento_anterior_a_121_segundos_nao_vira_emergencia_atual(self):
        messages = [self.message("Meu pet está com falta de ar", 121),
                    self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION)]
        result = self.run_job(messages)
        self.assertEqual(result.decisao, "sent")
        self.assertIn(CONVITE_KEY, json.loads(result.tools_usadas))
        self.provider_factory.assert_not_called()
        self.assert_no_handoff()
        self.assert_no_business_mutations()

    def test_pedido_humano_agrupado_continua_encaminhando(self):
        result = self.run_job([self.message("Quero falar com um atendente", 90),
                              self.message("Oi", 80), self.message("Boa tarde", 60), self.message(QUESTION)])
        self.assertEqual((result.decisao, result.motivo), ("handoff", "pedido_humano"))
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)
        self.assertTrue(gates.is_locally_paused(self.estado))
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_business_mutations()

    def test_pausa_existente_impede_convite(self):
        self.estado.pausado_ate = self.now + timedelta(hours=1)
        self.db.commit()
        result = self.run_job([self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION)])
        self.assertEqual((result.decisao, result.motivo), ("suppressed", "pausado"))
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_business_mutations()

    def test_conversa_assumida_impede_convite(self):
        result = self.run_job([self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION)], agent=7)
        self.assertEqual((result.decisao, result.motivo), ("suppressed", "pausado"))
        self.assertTrue(gates.is_locally_paused(self.estado))
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_business_mutations()

    def test_janela_fechada_impede_convite(self):
        result = self.run_job([self.message("Oi", 100), self.message("Boa tarde", 60), self.message(QUESTION)], inbound_hours=25)
        self.assertEqual((result.decisao, result.motivo), ("suppressed", "janela_fechada"))
        self.post.assert_not_called()
        self.provider_factory.assert_not_called()
        self.assert_no_handoff()
        self.assert_no_business_mutations()

    def test_fragmentos_clinicos_negacao_e_preco_permanecem_no_corpo(self):
        for fragment in ("Meu pet está tossindo", "Não quero marcar agora", "E qual o preço?"):
            with self.subTest(fragment=fragment):
                # Cada caso usa identidade operacional sem a pausa produzida
                # pelo fallback simulado do caso anterior.
                self.estado.pausado_ate = None
                self.estado.handoff_motivo = None
                self.db.commit()
                self.provider.generate.reset_mock()
                messages = [self.message("Oi", 100), self.message(fragment, 90),
                            self.message("Boa tarde", 60), self.message(QUESTION)]
                result = self.run_job(messages)
                self.assertEqual(result.decisao, "blocked")
                self.provider.generate.assert_called_once()
                payload = self.provider.generate.call_args.kwargs["payload"]
                self.assertEqual(payload["mensagem_do_cliente"], "\n".join(item["body"] for item in messages))
                self.assertNotIn(CONVITE_KEY, json.loads(result.tools_usadas))
                self.assertNotIn(COLETA_KEY, json.loads(result.tools_usadas))
                self.post.assert_not_called()
                self.assert_no_business_mutations()


if __name__ == "__main__":
    unittest.main()
