import os
import sys
import unittest
from unittest.mock import patch

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-guardrails-test-secret-key-1234567890")

from app.services import whatsapp_bot_guardrails as gr


def _turno(**kwargs) -> gr.TurnoDeGeracao:
    base = {
        "persona": "tutor",
        "tools_ok": [
            "consultar_dados_institucionais",
            "consultar_horario_funcionamento",
            "consultar_preco_tabela",
            "consultar_status_laudo",
            "buscar_conhecimento_institucional",
        ],
    }
    base.update(kwargs)
    return gr.TurnoDeGeracao(**base)


class GuardrailBloqueioClinicoTest(unittest.TestCase):
    """RF-022: o requisito mais importante da entrega."""

    def test_diagnostico_bloqueia(self) -> None:
        for texto in (
            "Pelo que voce descreve, seu pet tem insuficiencia cardiaca.",
            "Isso indica um sopro grau 3.",
            "Provavelmente e cardiomiopatia dilatada.",
        ):
            veredito = gr.avaliar_resposta(
                texto=texto, intent="horario_funcionamento", modo="auto", turno=_turno()
            )
            self.assertFalse(veredito.aprovado, texto)
            self.assertEqual(veredito.motivo, "diagnostico", texto)

    def test_dose_e_medicacao_bloqueiam(self) -> None:
        for texto in (
            "Pode dar meio comprimido de furosemida a cada 12 horas.",
            "A dose usual e 2 mg por kg.",
            "Administre o pimobendan duas vezes ao dia.",
        ):
            veredito = gr.avaliar_resposta(
                texto=texto, intent="horario_funcionamento", modo="auto", turno=_turno()
            )
            self.assertFalse(veredito.aprovado, texto)
            self.assertEqual(veredito.motivo, "dose_medicacao", texto)

    def test_prognostico_bloqueia(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="A expectativa de vida nesses casos costuma ser curta.",
            intent="horario_funcionamento",
            modo="auto",
            turno=_turno(),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "prognostico")

    def test_avaliacao_de_sintoma_bloqueia(self) -> None:
        for texto in (
            "Tossir depois de correr e normal, fique tranquilo.",
            "Nao precisa se preocupar, pode esperar a proxima consulta.",
        ):
            veredito = gr.avaliar_resposta(
                texto=texto, intent="horario_funcionamento", modo="auto", turno=_turno()
            )
            self.assertFalse(veredito.aprovado, texto)
            self.assertEqual(veredito.motivo, "avaliacao_sintoma", texto)

    def test_conteudo_clinico_bloqueia_mesmo_com_fonte_da_base(self) -> None:
        """"Veio da base" nao e passe livre: a base contem procedimento clinico."""
        veredito = gr.avaliar_resposta(
            texto="Conforme nosso manual, seu pet tem endocardiose de valva mitral.",
            intent="horario_funcionamento",
            modo="auto",
            turno=_turno(tools_ok=["buscar_conhecimento_institucional"]),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "diagnostico")

    def test_vazamento_de_conteudo_de_laudo_bloqueia(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="O laudo diz: atrio esquerdo moderadamente aumentado com refluxo.",
            intent="status_laudo",
            modo="auto",
            turno=_turno(
                textos_clinicos_proibidos=["atrio esquerdo moderadamente aumentado com refluxo"]
            ),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "vazamento_conteudo_laudo")


class GuardrailFonteEAncoragemTest(unittest.TestCase):
    def test_sem_fonte_nao_responde(self) -> None:
        """RF-020 / CA-016."""
        veredito = gr.avaliar_resposta(
            texto="Funcionamos de segunda a sexta.",
            intent="horario_funcionamento",
            modo="auto",
            turno=_turno(tools_ok=[]),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "sem_fonte")

    def test_valor_fora_da_tabela_bloqueia(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="O ecocardiograma custa R$ 350,00.",
            intent="preco_servico",
            modo="auto",
            turno=_turno(valores_permitidos={"420.00"}),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "valor_fora_tabela")

    def test_tool_sem_relacao_nao_conta_como_fonte_da_intent(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="O ecocardiograma custa R$ 420,00.",
            intent="preco_servico",
            modo="auto",
            turno=_turno(
                tools_ok=["consultar_horario_funcionamento"],
                valores_permitidos={"420.00"},
            ),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "sem_fonte")

    def test_valor_ancorado_na_tabela_passa(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="O ecocardiograma custa R$ 420,00.",
            intent="preco_servico",
            modo="auto",
            turno=_turno(valores_permitidos={"420.00"}),
        )
        self.assertTrue(veredito.aprovado, veredito.detalhe)

    def test_horario_nao_confirmado_por_tool_bloqueia(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="Hoje atendemos das 08:00 as 18:00.",
            intent="horario_funcionamento",
            modo="auto",
            turno=_turno(horarios_permitidos={"08:00", "14:00"}),
        )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "prazo_nao_confirmado")

    def test_horario_ancorado_passa(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="Hoje atendemos das 08:00 as 14:00.",
            intent="horario_funcionamento",
            modo="auto",
            turno=_turno(horarios_permitidos={"08:00", "14:00"}),
        )
        self.assertTrue(veredito.aprovado, veredito.detalhe)


class GuardrailAllowlistDeIntentTest(unittest.TestCase):
    def test_bloco_comum_sempre_vira_rascunho_nas_duas_personas(self) -> None:
        """CA-024: OS, cobranca, valor em aberto, repasse."""
        for persona in ("tutor", "clinica"):
            for intent in ("ordem_servico", "cobranca", "valor_em_aberto", "repasse_negociacao"):
                veredito = gr.avaliar_resposta(
                    texto="Sobre isso, veja com a equipe.",
                    intent=intent,
                    modo="auto",
                    turno=_turno(persona=persona),
                )
                self.assertTrue(veredito.aprovado, f"{persona}/{intent}")
                self.assertFalse(veredito.auto_elegivel, f"{persona}/{intent}")
                self.assertEqual(veredito.motivo, "intent_fora_allowlist", f"{persona}/{intent}")

    def test_intent_de_outra_persona_nao_e_auto(self) -> None:
        # `como_agendar` e do tutor; `como_solicitar_exame` e da clinica.
        veredito = gr.avaliar_resposta(
            texto="Para agendar, chame a equipe.",
            intent="como_agendar",
            modo="auto",
            turno=_turno(persona="clinica"),
        )
        self.assertTrue(veredito.aprovado)
        self.assertFalse(veredito.auto_elegivel)
        self.assertEqual(veredito.motivo, "intent_fora_allowlist")

        veredito = gr.avaliar_resposta(
            texto="Para solicitar exame, chame a equipe.",
            intent="como_solicitar_exame",
            modo="auto",
            turno=_turno(persona="tutor"),
        )
        self.assertTrue(veredito.aprovado)
        self.assertFalse(veredito.auto_elegivel)
        self.assertEqual(veredito.motivo, "intent_fora_allowlist")

    def test_outro_nunca_e_auto(self) -> None:
        veredito = gr.avaliar_resposta(
            texto="Vou passar para a equipe.", intent="outro", modo="auto", turno=_turno()
        )
        self.assertTrue(veredito.aprovado)
        self.assertFalse(veredito.auto_elegivel)
        self.assertEqual(veredito.motivo, "intent_fora_allowlist")


class GuardrailTetosTest(unittest.TestCase):
    def test_teto_de_caracteres(self) -> None:
        with patch.object(gr.settings, "WHATSAPP_BOT_MAX_REPLY_CHARS", 40):
            veredito = gr.avaliar_resposta(
                texto="a" * 41,
                intent="horario_funcionamento",
                modo="auto",
                turno=_turno(),
            )
        self.assertFalse(veredito.aprovado)
        self.assertEqual(veredito.motivo, "teto_caracteres")


class GuardrailTurnoTest(unittest.TestCase):
    def test_turno_extrai_valores_e_horarios_do_retorno_literal_das_tools(self) -> None:
        turno = gr.turno_a_partir_dos_resultados(
            "tutor",
            [
                (
                    "consultar_horario_funcionamento",
                    {"ok": True, "aberto": True, "inicio": "08:00", "fim": "14:00", "data": "2026-08-24"},
                ),
                (
                    "consultar_preco_tabela",
                    {"ok": True, "itens": [{"servico": "Eco", "valor": "420.00"}]},
                ),
                ("consultar_status_laudo", {"ok": False, "error": "nada"}),
            ],
        )
        self.assertEqual(sorted(turno.tools_ok), ["consultar_horario_funcionamento", "consultar_preco_tabela"])
        self.assertEqual(turno.horarios_permitidos, {"08:00", "14:00"})
        self.assertEqual(turno.valores_permitidos, {"420.00"})
        self.assertTrue(turno.tem_fonte)

    def test_tool_com_ok_false_nao_conta_como_fonte(self) -> None:
        turno = gr.turno_a_partir_dos_resultados(
            "tutor", [("consultar_status_laudo", {"ok": False, "error": "nada"})]
        )
        self.assertEqual(turno.tools_ok, [])
        self.assertFalse(turno.tem_fonte)


if __name__ == "__main__":
    unittest.main()


class GuardrailPrecoForaDoAutoTest(unittest.TestCase):
    """`preco_servico` continua seguro, mas nunca sai sozinho (2026-08-24)."""

    def test_preco_nao_e_auto_em_nenhuma_persona(self) -> None:
        for persona in ("tutor", "clinica"):
            self.assertNotIn("preco_servico", gr.INTENTS_AUTO_POR_PERSONA[persona], persona)
            self.assertIn("preco_servico", gr.INTENTS_ATENDIDAS_POR_PERSONA[persona], persona)

    def test_preco_ancorado_e_aprovado_mas_vira_rascunho(self) -> None:
        """Aprovado e auto_elegivel sao coisas diferentes.

        O texto e seguro - o valor veio da tool -, entao nao e bloqueio: e
        rascunho para revisao humana.
        """
        turno = gr.TurnoDeGeracao(
            persona="tutor",
            tools_ok=["consultar_preco_tabela"],
            valores_permitidos={"420.00"},
        )
        v = gr.avaliar_resposta(
            texto="O ecocardiograma custa R$ 420,00.", intent="preco_servico", modo="auto", turno=turno
        )
        self.assertTrue(v.aprovado)
        self.assertFalse(v.auto_elegivel)
        self.assertEqual(v.motivo, "intent_fora_allowlist")

    def test_as_demais_intents_seguem_auto(self) -> None:
        turno = gr.TurnoDeGeracao(persona="tutor", tools_ok=["consultar_horario_funcionamento"])
        v = gr.avaliar_resposta(
            texto="Funcionamos de segunda a sexta.", intent="horario_funcionamento", modo="auto", turno=turno
        )
        self.assertTrue(v.aprovado)
        self.assertTrue(v.auto_elegivel)
