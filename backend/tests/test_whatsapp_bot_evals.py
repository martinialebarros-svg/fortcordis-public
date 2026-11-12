import json
import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-evals-test-secret-key-1234567890")

from app.schemas.whatsapp_bot import WhatsAppBotIntent
from app.services import whatsapp_bot_guardrails as gr
from app.services.whatsapp_bot_tools import TOOLS_POR_PERSONA

CASES_PATH = BACKEND_DIR / "evals" / "whatsapp_bot_cases.json"


def _intents_validas() -> set[str]:
    return set(WhatsAppBotIntent.__args__)


def _texto_do_caso(case: dict) -> str:
    if "texto_repetido" in case:
        repetido = case["texto_repetido"]
        return str(repetido["trecho"]) * int(repetido["vezes"])
    return str(case["texto"])


def _turno_do_caso(case: dict) -> gr.TurnoDeGeracao:
    bruto = case.get("turno") or {}
    return gr.TurnoDeGeracao(
        persona=case["persona"],
        tools_ok=list(bruto.get("tools_ok") or []),
        valores_permitidos=set(bruto.get("valores_permitidos") or []),
        horarios_permitidos=set(bruto.get("horarios_permitidos") or []),
        datas_permitidas=set(bruto.get("datas_permitidas") or []),
        textos_clinicos_proibidos=list(bruto.get("textos_clinicos_proibidos") or []),
        telefones_permitidos=set(bruto.get("telefones_permitidos") or []),
        ceps_permitidos=set(bruto.get("ceps_permitidos") or []),
        tem_endereco_na_fonte=bool(bruto.get("tem_endereco_na_fonte")),
    )


class WhatsAppBotEvalContractTest(unittest.TestCase):
    """P6.1: casos de regressao dos guardrails, deterministicos e sem rede."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = cls.payload["cases"]

    def test_dataset_bem_formado(self) -> None:
        self.assertGreaterEqual(len(self.cases), 27)
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)), "ids de caso duplicados")

        intents_validas = _intents_validas()
        for case in self.cases:
            self.assertIn(case["persona"], ("tutor", "clinica"), case["id"])
            self.assertIn(case["intent"], intents_validas, case["id"])
            self.assertTrue(case.get("guardrail"), case["id"])
            self.assertTrue("texto" in case or "texto_repetido" in case, case["id"])
            esperado = case["esperado"]
            for chave in ("aprovado", "auto_elegivel", "motivo"):
                self.assertIn(chave, esperado, case["id"])

    def test_toda_tool_citada_existe_na_persona_do_caso(self) -> None:
        for case in self.cases:
            permitidas = TOOLS_POR_PERSONA[case["persona"]]
            for nome in (case.get("turno") or {}).get("tools_ok") or []:
                self.assertIn(nome, permitidas, f'{case["id"]}: {nome}')

    def test_todo_motivo_esperado_esta_no_literal(self) -> None:
        motivos_validos = set(gr.MotivoBloqueio.__args__)
        for case in self.cases:
            motivo = case["esperado"]["motivo"]
            if motivo is not None:
                self.assertIn(motivo, motivos_validos, case["id"])

    def test_cada_caso_produz_o_veredito_esperado(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                veredito = gr.avaliar_resposta(
                    texto=_texto_do_caso(case),
                    intent=case["intent"],
                    modo="auto",
                    turno=_turno_do_caso(case),
                )
                esperado = case["esperado"]
                self.assertEqual(veredito.aprovado, esperado["aprovado"], veredito.detalhe)
                self.assertEqual(veredito.auto_elegivel, esperado["auto_elegivel"], veredito.detalhe)
                self.assertEqual(veredito.motivo, esperado["motivo"], veredito.detalhe)

    def test_cobertura_de_todos_os_motivos_de_bloqueio(self) -> None:
        """Nenhum motivo do Literal pode ficar sem caso de regressao.

        Excecoes declaradas: `teto_diario` depende de contagem no banco
        (coberto em test_whatsapp_bot_generation) e nao de texto candidato.
        """
        cobertos = {case["esperado"]["motivo"] for case in self.cases}
        cobertos.discard(None)
        esperados = set(gr.MotivoBloqueio.__args__) - {"teto_diario"}
        self.assertEqual(esperados - cobertos, set(), "motivos sem caso de regressao")

    def test_grupo_da_deny_list_sempre_mapeia_para_motivo_do_literal(self) -> None:
        """Guarda a integridade da metrica por motivo (P6.5).

        `avaliar_resposta` usa o NOME DO GRUPO do JSON como `motivo`, com um
        `type: ignore`. Um grupo novo com nome fora do Literal passaria em
        runtime e sujaria a agregacao por motivo sem quebrar nada - por isso
        o contrato e verificado aqui.
        """
        motivos_validos = set(gr.MotivoBloqueio.__args__)
        grupos = [nome for nome, _termos in gr._carregar_grupos_bloqueio()]
        self.assertTrue(grupos, "deny-list clinica vazia: guardrail desligado")
        for nome in grupos:
            self.assertIn(nome, motivos_validos, f"grupo {nome} fora de MotivoBloqueio")

    def test_deny_list_nao_tem_termo_vazio_nem_generico_demais(self) -> None:
        """Termo curto casa dentro de palavra maior e bloqueia demais."""
        for nome, termos in gr._carregar_grupos_bloqueio():
            for termo in termos:
                self.assertTrue(termo.strip(), f"{nome}: termo vazio")
                self.assertGreaterEqual(len(termo), 2, f"{nome}: termo {termo!r} curto demais")

    def test_cobertura_das_duas_personas_e_do_bloco_comum(self) -> None:
        personas = {case["persona"] for case in self.cases}
        self.assertEqual(personas, {"tutor", "clinica"})

        bloco_comum = {"ordem_servico", "cobranca", "valor_em_aberto", "repasse_negociacao"}
        intents_do_bloco = {
            case["intent"] for case in self.cases if case["intent"] in bloco_comum
        }
        self.assertEqual(intents_do_bloco, bloco_comum, "bloco comum incompleto")
        for case in self.cases:
            if case["intent"] in bloco_comum:
                self.assertFalse(
                    case["esperado"]["auto_elegivel"],
                    f'{case["id"]}: bloco comum nunca e auto',
                )

    def test_existe_caso_aprovado_em_cada_persona(self) -> None:
        aprovados_auto = {
            case["persona"]
            for case in self.cases
            if case["esperado"]["aprovado"] and case["esperado"]["auto_elegivel"]
        }
        self.assertEqual(aprovados_auto, {"tutor", "clinica"})


if __name__ == "__main__":
    unittest.main()
