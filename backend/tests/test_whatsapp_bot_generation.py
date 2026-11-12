import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-generation-test-secret-key-1234567890")

from app.models.agendamento import Agendamento
from app.models.assistente_ia import AssistenteIAConhecimentoDocumento
from app.models.atendimento_clinico import AtendimentoClinico
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.laudo import Exame, Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao
from app.models.whatsapp_bot import WhatsAppBotSolicitacao
from app.models.whatsapp_bot import (
    WhatsAppBotClinicaEstado,
    WhatsAppBotConversaEstado,
    WhatsAppBotResposta,
)
from app.schemas.whatsapp_bot import WhatsAppBotReplyOutput
from app.services import whatsapp_bot_generation as generation
from app.services.whatsapp_bot_providers import GeneratedReply, WhatsAppBotProviderError


def fake_provider(
    *, texto, intent, fontes=None, precisa_humano=False, tool_name=None, tool_arguments=None
):
    """Provider fake de duas etapas: function_call -> saida estruturada."""
    fonte_padrao = {
        "horario_funcionamento": "consultar_horario_funcionamento",
        "endereco": "consultar_dados_institucionais",
        "formas_contato": "consultar_dados_institucionais",
        "preco_servico": "consultar_preco_tabela",
        "status_laudo": "consultar_status_laudo",
    }.get(intent, "consultar_dados_institucionais")
    nome = tool_name or fonte_padrao
    argumentos_padrao = {
        "consultar_horario_funcionamento": {"data": None},
        "consultar_dados_institucionais": {},
        "consultar_preco_tabela": {"servico_nome": "Ecocardiograma", "regiao": "fortaleza"},
        "consultar_status_laudo": {"pet_nome": "Thor"},
    }.get(nome, {"consulta": "atendimento FortCordis"})
    tool_turn = GeneratedReply(
        output=None,
        model="fake-model",
        input_tokens=60,
        output_tokens=5,
        tool_calls=[
            {
                "call_id": "call-1",
                "name": nome,
                "arguments": tool_arguments if tool_arguments is not None else argumentos_padrao,
            }
        ],
        continuation_input=[{"type": "function_call", "call_id": "call-1", "name": nome}],
    )
    reply = GeneratedReply(
        output=WhatsAppBotReplyOutput(
            texto=texto, intent=intent, fontes=fontes or [], precisa_humano=precisa_humano
        ),
        model="fake-model",
        input_tokens=60,
        output_tokens=35,
    )
    return SimpleNamespace(generate=Mock(side_effect=[tool_turn, reply]))


class WhatsAppBotGenerationTest(unittest.TestCase):
    def _factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-generation-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            WhatsAppBotContextoSelecao.__table__,
            Configuracao.__table__,
            WhatsAppBotConversaEstado.__table__,
            WhatsAppBotClinicaEstado.__table__,
            Servico.__table__,
            Clinica.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AtendimentoClinico.__table__,
            AssistenteIAConhecimentoDocumento.__table__,
            WhatsAppBotResposta.__table__, WhatsAppBotSolicitacao.__table__,
        ):
            table.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def _seed_tutor(self, db, *, whatsapp="5585999990001"):
        db.add(Configuracao(cidade="Fortaleza", endereco="Rua Teste, 100", telefone="8533334444"))
        db.add(Servico(nome="Ecocardiograma", ativo=True, preco_fortaleza_comercial=420,
                       preco_domiciliar_comercial=560))
        tutor = Tutor(nome="Maria", whatsapp=whatsapp, ativo=1)
        db.add(tutor)
        db.commit()
        db.add(Paciente(nome="Thor", tutor_id=tutor.id, ativo=1))
        db.commit()
        return tutor

    # --- caminhos que NAO chamam o provider ------------------------------

    def test_visitante_responde_informacao_publica_sem_acesso_a_cadastros(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                with Factory() as db:
                    db.add(Configuracao(telefone="8533334444"))
                    db.commit()
                    provider = fake_provider(
                        texto="Atendimento automatico: para falar com uma pessoa, e so pedir.",
                        intent="formas_contato",
                    )
                    resultado = generation.gerar_resposta(
                        db, wa_identity="5585900000000", corpo_mensagem="como falo com voces?",
                        modo="suggest", provider=provider,
                    )
                    self.assertEqual(resultado.match_type, "visitante")
                    self.assertEqual(resultado.decisao, "draft")
                    self.assertEqual(provider.generate.call_count, 2)
                    call = provider.generate.call_args_list[0].kwargs
                    self.assertFalse(call["payload"]["contexto"]["tem_dados_do_cliente"])
                    self.assertEqual({t["name"] for t in call["tools"]}, {
                        "consultar_horario_funcionamento", "consultar_dados_institucionais",
                        "buscar_conhecimento_institucional",
                    })
            finally:
                engine.dispose()

    def test_identidade_ambigua_nao_chama_provider_nem_expoe_candidatos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    provider = SimpleNamespace(
                        generate=Mock(side_effect=AssertionError("provider nao deve ser chamado"))
                    )
                    contexto = {
                        "resolution": "ambiguous",
                        "match_type": None,
                        "tutores": [{"id": 1, "nome": "Pessoa privada"}],
                    }
                    with patch.object(generation, "_resolver_contexto", return_value=contexto):
                        resultado = generation.gerar_resposta(
                            db,
                            wa_identity="5585900000000",
                            corpo_mensagem="qual o horario?",
                            modo="suggest",
                            provider=provider,
                        )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "handoff")
                self.assertEqual(resultado.motivo, "identidade_ambigua")
                self.assertEqual(resultado.resolution, "ambiguous")
                self.assertEqual(resultado.texto_gerado, generation.IDENTITY_HANDOFF_MESSAGE)
                self.assertNotIn("Pessoa privada", resultado.texto_gerado)
                self.assertFalse(resultado.auto_elegivel)
                provider.generate.assert_not_called()
            finally:
                engine.dispose()

    def test_teto_diario_suprime_antes_de_gastar_token(self) -> None:
        """RF-025/CA-017."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    for i in range(3):
                        db.add(
                            WhatsAppBotResposta(
                                job_id=i + 1,
                                wa_identity="5585999990001",
                                conversation_id="conv-1",
                                decisao="sent",
                                motivo="ok",
                            )
                        )
                    db.commit()

                    provider = SimpleNamespace(
                        generate=Mock(side_effect=AssertionError("provider nao deve ser chamado"))
                    )
                    with patch.object(
                        generation.settings, "WHATSAPP_BOT_MAX_REPLIES_PER_CONVERSATION_DAY", 3
                    ):
                        resultado = generation.gerar_resposta(
                            db,
                            wa_identity="5585999990001",
                            corpo_mensagem="qual o horario?",
                            modo="auto",
                            provider=provider,
                        )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "suppressed")
                self.assertEqual(resultado.motivo, "teto_diario")
                provider.generate.assert_not_called()
            finally:
                engine.dispose()

    def test_rascunho_nao_consome_teto_diario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    for i in range(5):
                        db.add(
                            WhatsAppBotResposta(
                                job_id=i + 1,
                                wa_identity="5585999990001",
                                conversation_id="conv-1",
                                decisao="draft",
                                motivo="modo_suggest",
                            )
                        )
                    db.commit()
                    contagem = generation.contar_respostas_do_dia(db, "5585999990001")
                finally:
                    db.close()
                self.assertEqual(contagem, 0)
            finally:
                engine.dispose()

    # --- guardrails no caminho completo ----------------------------------

    def test_conteudo_clinico_gerado_vira_blocked_com_motivo(self) -> None:
        """CA-015: bloqueio nunca vira silencio."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Pelo que voce descreve, seu pet tem insuficiencia cardiaca.",
                        intent="horario_funcionamento",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="ele tossiu, e serio?",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "blocked")
                self.assertEqual(resultado.motivo, "diagnostico")
                # O texto gerado fica registrado para auditoria, mas nao e enviado.
                self.assertIn("insuficiencia cardiaca", resultado.texto_gerado)
                self.assertEqual(resultado.modelo, "fake-model")
                self.assertIsNotNone(resultado.prompt_version)
            finally:
                engine.dispose()

    def test_intent_fora_da_allowlist_em_auto_vira_rascunho(self) -> None:
        """CA-014/CA-024."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Sobre a cobranca, a equipe vai te responder.",
                        intent="cobranca",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="tenho valor em aberto?",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "intent_fora_allowlist")
            finally:
                engine.dispose()

    def test_intent_fora_da_allowlist_em_suggest_continua_editavel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Sobre a cobranca, a equipe vai te responder.",
                        intent="cobranca",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="tenho valor em aberto?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "modo_suggest")
            finally:
                engine.dispose()

    def test_resposta_aprovada_em_suggest_vira_rascunho_sem_envio(self) -> None:
        """Critério de conclusao da Fase 4."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto=(
                            "Somos o atendimento automatico da FortCordis. "
                            "Se precisar de uma pessoa, e so pedir."
                        ),
                        intent="formas_contato",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="como falo com voces?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "modo_suggest")
                self.assertIsNone(resultado.texto_enviado)
                self.assertEqual(resultado.match_type, "tutor")
                self.assertEqual(resultado.resolution, "matched")
                self.assertEqual(resultado.input_tokens, 120)
                self.assertEqual(resultado.output_tokens, 40)
                self.assertIsNotNone(resultado.latencia_ms)
            finally:
                engine.dispose()

    def test_aprovada_em_auto_e_elegivel_sem_enviar_no_gerador(self) -> None:
        """RF-027 depende de mudanca no servico Node - envio e Fase 6."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Atendimento automatico: para falar com alguem, e so pedir.",
                        intent="formas_contato",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="como falo com voces?",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "aprovado_auto")
                self.assertTrue(resultado.auto_elegivel)
                self.assertIsNone(resultado.texto_enviado)
            finally:
                engine.dispose()

    def test_tool_de_preco_roda_e_texto_final_vem_do_payload_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="O valor e R$ 999,00.",
                        intent="preco_servico",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="quanto custa o ecocardiograma?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()

                # RF-P15/P17: o modelo pediu `regiao="fortaleza"` (tabela
                # praticada com clinica parceira). O tutor nao recebe esse
                # valor -- mas TAMBEM nao pode receber silencio. O turno vira
                # rascunho com a pergunta que a secretaria faria.
                self.assertEqual(resultado.decisao, "draft")
                self.assertIn("depende do tipo de atendimento", resultado.texto_gerado)
                self.assertIn("clínica parceira", resultado.texto_gerado)
                self.assertNotIn("420", resultado.texto_gerado)
                self.assertNotIn("999", resultado.texto_gerado)
                self.assertIn("consultar_preco_tabela", resultado.tools_usadas or "")
            finally:
                engine.dispose()

    def test_preco_a_tutor_sai_pela_tabela_domiciliar(self) -> None:
        """O caminho que o tutor PODE receber: tabela 3, da propria FortCordis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="O valor e R$ 999,00.",
                        intent="preco_servico",
                        tool_arguments={"servico_nome": "Ecocardiograma", "regiao": "domiciliar"},
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="quanto custa o eco em casa?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertIn("R$ 560,00", resultado.texto_gerado)
                self.assertNotIn("420", resultado.texto_gerado)
                self.assertNotIn("999", resultado.texto_gerado)
                segunda_entrada = provider.generate.call_args_list[1].kwargs["continuation_input"]
                self.assertIn('"valor": "560.00"', segunda_entrada[-1]["output"])
            finally:
                engine.dispose()

    def test_tool_sem_relacao_nao_autoriza_status_de_laudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="O laudo do Thor esta pronto.",
                        intent="status_laudo",
                        tool_name="consultar_horario_funcionamento",
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="o laudo saiu?",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "blocked")
                self.assertEqual(resultado.motivo, "sem_fonte")
            finally:
                engine.dispose()

    def test_limite_de_rodadas_de_tools_vira_rascunho_seguro(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    tool_turn = GeneratedReply(
                        output=None,
                        model="fake-model",
                        input_tokens=10,
                        output_tokens=2,
                        tool_calls=[
                            {
                                "call_id": "call-loop",
                                "name": "consultar_dados_institucionais",
                                "arguments": {},
                            }
                        ],
                        continuation_input=[{"type": "function_call", "call_id": "call-loop"}],
                    )
                    provider = SimpleNamespace(generate=Mock(return_value=tool_turn))
                    with patch.object(generation, "MAX_TOOL_ROUNDS", 1):
                        resultado = generation.gerar_resposta(
                            db,
                            wa_identity="5585999990001",
                            corpo_mensagem="como falo com voces?",
                            modo="suggest",
                            provider=provider,
                        )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "limite_rodadas_tools")
                self.assertIn("não consegui confirmar", resultado.texto_gerado)
                self.assertEqual(provider.generate.call_count, 2)
            finally:
                engine.dispose()

    def test_teto_global_de_tokens_degrada_para_draft_antes_do_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    db.add(
                        WhatsAppBotResposta(
                            job_id=99,
                            wa_identity="5585000000000",
                            conversation_id="conv-outra",
                            decisao="draft",
                            motivo="modo_suggest",
                            input_tokens=80,
                            output_tokens=20,
                        )
                    )
                    db.commit()
                    provider = SimpleNamespace(
                        generate=Mock(side_effect=AssertionError("provider nao deve ser chamado"))
                    )
                    with patch.object(generation.settings, "WHATSAPP_BOT_MAX_TOKENS_PER_DAY", 100):
                        resultado = generation.gerar_resposta(
                            db,
                            wa_identity="5585999990001",
                            corpo_mensagem="qual o horario?",
                            modo="auto",
                            provider=provider,
                        )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "draft")
                self.assertEqual(resultado.motivo, "teto_global_tokens")
                self.assertIn("revisão da equipe", resultado.texto_gerado)
                provider.generate.assert_not_called()
            finally:
                engine.dispose()

    def test_modelo_pedindo_humano_vira_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Vou passar para a equipe te ajudar.",
                        intent="formas_contato",
                        precisa_humano=True,
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="preciso de ajuda",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "handoff")
                self.assertEqual(resultado.motivo, "modelo_pediu_humano")
            finally:
                engine.dispose()

    def test_falha_do_provider_vira_handoff_nao_erro(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = SimpleNamespace(
                        generate=Mock(
                            side_effect=WhatsAppBotProviderError("timeout", code="provider_timeout")
                        )
                    )
                    resultado = generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="qual o horario?",
                        modo="auto",
                        provider=provider,
                    )
                finally:
                    db.close()

                self.assertEqual(resultado.decisao, "handoff")
                self.assertEqual(resultado.motivo, "provider:provider_timeout")
            finally:
                engine.dispose()

    def test_contexto_do_prompt_nao_carrega_ordem_de_servico(self) -> None:
        """CA-024: OS/valor/cobranca nao entram no prompt nem por contexto."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Factory, engine = self._factory(tmpdir)
            try:
                db = Factory()
                try:
                    self._seed_tutor(db)
                    provider = fake_provider(
                        texto="Atendimento automatico da FortCordis.", intent="formas_contato"
                    )
                    generation.gerar_resposta(
                        db,
                        wa_identity="5585999990001",
                        corpo_mensagem="Qual é o telefone de contato?",
                        modo="suggest",
                        provider=provider,
                    )
                finally:
                    db.close()

                payload = provider.generate.call_args.kwargs["payload"]
                texto_payload = str(payload).lower()
                for proibido in ("numero_os", "valor_final", "ordens_servico"):
                    self.assertNotIn(proibido, texto_payload, proibido)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
