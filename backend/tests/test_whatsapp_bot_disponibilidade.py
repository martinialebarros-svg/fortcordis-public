"""Disponibilidade natural e confirmação contextual sem criar agenda/fila."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-disponibilidade-1234567890")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.whatsapp_bot import (
    WhatsAppBotResposta as Resposta,
    WhatsAppBotSolicitacao as Pedido,
)
from app.services import whatsapp_bot_disponibilidade as disponibilidade
from app.services.whatsapp_bot_agendamento import KEY as COLETA_KEY
from app.services.whatsapp_bot_agendamento import exame_em_consulta_disponibilidade
from app.services.whatsapp_bot_generation import gerar_resposta


class DisponibilidadeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        for model in (Resposta, Pedido):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.contexto = {
            "resolution": "matched",
            "match_type": "clinica",
            "clinicas": [{"id": 9, "nome": "Clínica teste"}],
        }
        self._job_id = 0

    def response(self, text="Resposta anterior", audit=None, **overrides):
        self._job_id += 1
        values = dict(
            job_id=self._job_id, wa_identity="test", conversation_id="49",
            clinica_id=9, decisao="sent", texto_gerado=text, texto_enviado=text,
            tools_usadas=json.dumps(audit or {}, ensure_ascii=False),
            created_at=datetime.now(timezone.utc),
        )
        values.update(overrides)
        row = Resposta(**values)
        self.db.add(row)
        self.db.commit()
        return row

    def pedido(self, **overrides):
        old_collection = {
            "clinica_id": 9, "status": "encaminhada",
            "dados": {"exame": "eletro", "paciente": "Pet antigo",
                      "tutor": "Tutor antigo", "preferencia": "segunda à tarde"},
        }
        source = self.response(audit={COLETA_KEY: old_collection})
        now = datetime.now(timezone.utc)
        values = dict(
            resposta_id=source.id, wa_identity="test", conversation_id="49",
            clinica_id=9, resumo="Pedido anterior encerrado", status="cancelado",
            responsavel_id=1, prazo_em=now, created_at=now, updated_at=now,
            versao=3, historico="[]",
        )
        values.update(overrides)
        row = Pedido(**values)
        self.db.add(row)
        self.db.commit()
        return row

    def invite(self, pedido=None, **response_overrides):
        pedido = pedido or self.pedido()
        result = disponibilidade.convidar(pedido, "eco", "test", 9, "49")
        self.assertIsNotNone(result)
        text, audit = result
        row = self.response(text, audit, **response_overrides)
        return pedido, row

    def reply(self, pedido, message="sim", **scope):
        return disponibilidade.responder(
            self.db, pedido, message, scope.get("wa_identity", "test"),
            scope.get("clinica_id", 9), scope.get("conversation_id", "49"),
            self.contexto,
        )

    def test_pergunta_real_e_variacoes_retornam_exame_literal(self):
        cases = {
            "Qual a disponibilidade de horário pra eco": "eco",
            "Qual a disponibilidade de horários para ecocardiograma?": "ecocardiograma",
            "Tem disponibilidade de horário para ECG?": "ECG",
            "Vocês têm horário para eco?": "eco",
            "Quais horários disponíveis para ecocardiograma?": "ecocardiograma",
            "Qual a disponibilidade pra eco?": "eco",
            "Oi\nBoa tarde\nQual a disponibilidade pra eco": "eco",
            "Ola\nOi\nBoa tarde\nQual a disponibilidade pra eco": "eco",
            "Olá! Bom dia, Oi. Quais horários para ECG?": "ECG",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(exame_em_consulta_disponibilidade(message), expected)

    def test_frases_negativas_clinicas_e_mistas_nao_viram_coleta(self):
        for message in (
            "Não quero horário para eco",
            "Não tem disponibilidade de horário para eco?",
            "Qual a disponibilidade de horário pra eco? Meu pet está com falta de ar",
            "Qual a disponibilidade de horário pra eco e qual o valor?",
            "Qual o horário do meu eco?",
            "Qual a disponibilidade de horário pra eco amanhã?",
            "Qual o valor do eco?",
            "Oi\nNão quero\nQual a disponibilidade pra eco",
            "Oi\nBoa tarde\nQual a disponibilidade pra eco e qual o valor?",
            "Oi\nMeu pet está tossindo\nQual a disponibilidade pra eco",
            "Oi\nMeu pet está com falta de ar\nQual a disponibilidade pra eco",
            "Oi\nQuero falar com um atendente\nQual a disponibilidade pra eco",
            "Oi? Boa tarde. Qual a disponibilidade pra eco",
            "Oiboa tarde Qual a disponibilidade pra eco",
            "Obrigada\nQual a disponibilidade pra eco",
        ):
            with self.subTest(message=message):
                self.assertIsNone(exame_em_consulta_disponibilidade(message))

    def test_geracao_pergunta_convite_sim_sem_modelo_nem_duplicar_pedido(self):
        pedido = self.pedido()
        provider = Mock()
        with patch("app.services.whatsapp_bot_generation._resolver_contexto", return_value=self.contexto), patch(
            "app.services.whatsapp_bot_generation.resolve_modo_efetivo", return_value=("auto", None)
        ):
            invitation = gerar_resposta(
                self.db, wa_identity="test", conversation_id="49",
                corpo_mensagem="Qual a disponibilidade de horário pra eco",
                modo="auto", provider=provider,
            )
            audit = json.loads(invitation.tools_usadas)
            self.assertTrue(invitation.auto_elegivel)
            self.assertIn(disponibilidade.KEY, audit)
            self.assertNotIn(COLETA_KEY, audit)
            self.assertIn("nova solicitação", invitation.texto_gerado)
            self.response(invitation.texto_gerado, audit)
            self.assertTrue(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))

            confirmation = gerar_resposta(
                self.db, wa_identity="test", conversation_id="49", corpo_mensagem="sim",
                modo="auto", provider=provider,
            )
        state = json.loads(confirmation.tools_usadas)[COLETA_KEY]
        self.assertTrue(confirmation.auto_elegivel)
        self.assertEqual(state["status"], "coletando")
        self.assertEqual(state["dados"], {"exame": "eco"})
        self.assertEqual(state["origens"], {"exame": "mensagem_cliente"})
        self.assertEqual(state["fila_anterior_id"], pedido.id)
        self.assertIn("nome do paciente", confirmation.texto_gerado)
        self.assertIn("nome do tutor", confirmation.texto_gerado)
        provider.generate.assert_not_called()
        self.assertEqual(self.db.query(Pedido).count(), 1)
        self.assertEqual(pedido.status, "cancelado")
        self.assertIsNone(pedido.agendamento_id)
        self.assertEqual(pedido.versao, 3)

    def test_nao_encerra_convite_sem_coleta_ou_alterar_pedido(self):
        pedido, _ = self.invite()
        self.assertTrue(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "não", "49"))
        text, audit = self.reply(pedido, "não")
        self.assertTrue(text)
        self.assertEqual(audit, {})
        self.response(text, audit)
        self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))
        self.assertIsNone(self.reply(pedido))
        self.assertEqual(self.db.query(Pedido).count(), 1)
        self.assertEqual(pedido.status, "cancelado")

    def test_convite_so_para_pedido_cancelado_sem_agenda_no_mesmo_escopo(self):
        for changes in (
            {"status": "aguardando_equipe"}, {"status": "em_atendimento"},
            {"status": "aguardando_cliente"}, {"status": "agendado"},
            {"agendamento_id": 77}, {"wa_identity": "outra"},
            {"clinica_id": 10}, {"conversation_id": "50"},
        ):
            with self.subTest(changes=changes):
                pedido = self.pedido(**changes)
                self.assertIsNone(disponibilidade.convidar(pedido, "eco", "test", 9, "49"))

    def test_convite_nao_enviado_editado_ou_expirado_nao_confirma(self):
        for changes in (
            {"decisao": "draft"}, {"decisao": "auto_pending"},
            {"decisao": "sending"}, {"decisao": "blocked"},
            {"texto_enviado": "Texto editado pela equipe"}, {"texto_enviado": None},
            {"created_at": datetime.now(timezone.utc) - timedelta(minutes=31)},
        ):
            with self.subTest(changes=changes):
                pedido, _ = self.invite(**changes)
                self.assertIsNone(self.reply(pedido))
                self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))

    def test_resposta_mais_recente_invalida_convite_inclusive_rascunho(self):
        for decision in ("sent", "draft", "blocked", "suppressed"):
            with self.subTest(decision=decision):
                pedido, _ = self.invite()
                self.response("Resposta posterior sem convite", decisao=decision)
                self.assertIsNone(self.reply(pedido))
                self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))

    def test_mudanca_de_versao_status_ou_agenda_invalida_convite(self):
        for changes in ({"versao": 4}, {"status": "aguardando_equipe"}, {"agendamento_id": 99}):
            with self.subTest(changes=changes):
                pedido, _ = self.invite()
                for key, value in changes.items():
                    setattr(pedido, key, value)
                self.db.commit()
                self.assertIsNone(self.reply(pedido))
                self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))

    def test_evento_do_worker_sem_clinica_invalida_convite(self):
        for decision in ("suppressed", "handoff", "blocked"):
            with self.subTest(decision=decision):
                pedido, _ = self.invite()
                self.response("Evento posterior do worker", decisao=decision, clinica_id=None)
                self.assertIsNone(self.reply(pedido, "quero sim"))
                self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))

    def test_convite_de_outra_conversa_clinica_ou_identidade_nao_confirma(self):
        pedido, _ = self.invite()
        for changes in ({"wa_identity": "outra"}, {"clinica_id": 10}, {"conversation_id": "50"}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.reply(pedido, **changes))
        self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "50"))
        self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "outra", "sim", "49"))

    def test_sim_com_pergunta_ressalva_ou_sintoma_nao_confirma(self):
        pedido, _ = self.invite()
        for message in ("sim?", "sim, mas não quero novo pedido", "sim, está com falta de ar", "não, quero falar com atendente"):
            with self.subTest(message=message):
                self.assertIsNone(self.reply(pedido, message))
                self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", message, "49"))

    def test_convite_consumido_nao_pode_ser_reutilizado(self):
        pedido, _ = self.invite()
        text, audit = self.reply(pedido)
        self.response(text, audit)
        self.assertIsNone(self.reply(pedido))
        self.assertFalse(disponibilidade.resposta_ao_convite_pendente(self.db, "test", "sim", "49"))
        self.assertEqual(self.db.query(Pedido).count(), 1)


if __name__ == "__main__":
    unittest.main()
