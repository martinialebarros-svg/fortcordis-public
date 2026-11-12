import importlib.util
import sys
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_DIR / "scripts" / "ci" / "check_promotion_verify_pending.py"
SPEC = importlib.util.spec_from_file_location("check_promotion_verify_pending", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar o gate de promocao: {SCRIPT_PATH}")
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


class StatusPendenteTest(unittest.TestCase):
    def test_marcadores_diretos_sao_pendencia(self) -> None:
        for status in ["pendente", "Pendente", "pendente (QA manual)", "pendente-prod", "stage_pending"]:
            self.assertTrue(GATE.status_e_pendente(status), status)

    def test_status_que_comeca_bem_e_termina_pendente(self) -> None:
        # O caso que motivou o marcador forte valer em qualquer posicao.
        for status in [
            "aprovado em stage; producao pendente",
            "passou localmente; proximo deploy pendente",
            "ok/pendente",
        ]:
            self.assertTrue(GATE.status_e_pendente(status), status)

    def test_vocabulario_de_aprovacao_do_repo_nao_e_pendencia(self) -> None:
        for status in ["ok", "passou", "aprovado", "local_pass", "concluido", "pronto", "passed"]:
            self.assertFalse(GATE.status_e_pendente(status), status)

    def test_generico_em_prosa_tecnica_nao_e_pendencia(self) -> None:
        # "parcial" descrevendo um indice do Postgres nao e criterio pela metade.
        self.assertFalse(
            GATE.status_e_pendente(
                "ok local - node serializa por advisory lock e indice unico parcial de idempotency_key"
            )
        )

    def test_generico_no_inicio_e_pendencia(self) -> None:
        self.assertTrue(GATE.status_e_pendente("parcial"))
        self.assertTrue(GATE.status_e_pendente("parcial - ver risco residual 1"))


class ExtracaoDeTabelaTest(unittest.TestCase):
    def test_le_apenas_tabela_com_coluna_status(self) -> None:
        conteudo = (
            "| ID | Tipo | Evidencia | Status |\n"
            "| --- | --- | --- | --- |\n"
            "| CA-001 | aceitacao | teste x | ok |\n"
            "| CA-002 | aceitacao | depende de tela | pendente |\n"
            "\n"
            "| Etapa | Resultado |\n"
            "| --- | --- |\n"
            "| Migracao | pendente |\n"
        )
        pendencias = GATE.extrair_pendencias(conteudo, "feature-x")
        self.assertEqual([p.identificador for p in pendencias], ["CA-002"])

    def test_tabela_sem_coluna_id_ainda_reporta(self) -> None:
        conteudo = (
            "| Criterio | Status |\n"
            "| --- | --- |\n"
            "| algo | pendente |\n"
        )
        pendencias = GATE.extrair_pendencias(conteudo, "feature-x")
        self.assertEqual(len(pendencias), 1)
        self.assertEqual(pendencias[0].identificador, "(sem id)")


class FeaturesTocadasTest(unittest.TestCase):
    def test_ignora_templates_e_arquivos_fora_de_specs(self) -> None:
        arquivos = [
            "docs/specs/feature-a/spec.md",
            "docs/specs/templates/verify.md",
            "backend/app/main.py",
            "docs/RUNBOOK-STAGE-PROD.md",
        ]
        self.assertEqual(GATE.features_tocadas(arquivos), ["feature-a"])


class AvaliacaoTest(unittest.TestCase):
    def test_diff_sem_specs_dispensa_o_gate(self) -> None:
        resultado = GATE.avaliar([".github/workflows/deploy.yml"], str(REPO_DIR))
        self.assertTrue(resultado.passou)

    def test_label_de_excecao_libera_mas_mantem_a_pendencia_visivel(self) -> None:
        conteudo_pendente = GATE.extrair_pendencias(
            "| ID | Status |\n| --- | --- |\n| CA-001 | pendente |\n", "f"
        )
        self.assertEqual(len(conteudo_pendente), 1)


if __name__ == "__main__":
    unittest.main()
