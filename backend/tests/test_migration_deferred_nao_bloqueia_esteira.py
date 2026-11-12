"""Uma pendencia de conciliacao de dados nao pode bloquear o resto da esteira.

Cenario real: uma base criada antes do indice unico parcial de
`ux_atendimentos_clinicos_agendamento_unico` acumulou dois atendimentos para o
mesmo agendamento. A migracao 20260730_59 nao consegue criar a restricao ate
alguem conciliar esses registros — mas isso nao tem relacao nenhuma com as
migracoes 60+ (colunas de dose, tabelas fiscais, historico de ajuste de exame).

Antes da correcao, o `RuntimeError` da 59 parava o runner e as migracoes
seguintes nunca eram aplicadas, enquanto `executar_migracoes()` engolia a
excecao e deixava o app subir com schema incompleto.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import json
from sqlalchemy import inspect, text

from app.db.database import Base, engine
import app.models  # noqa: F401
import app.models.configuracao  # noqa: F401
from migrations.runner import get_deferred_migrations, get_migration_status, run_migrations

Base.metadata.create_all(bind=engine)

# Simula base legada: o indice unico ainda nao existia e duplicidades entraram.
with engine.begin() as conn:
    conn.execute(text("DROP INDEX IF EXISTS ux_atendimentos_clinicos_agendamento_unico"))
    conn.execute(
        text(
            "INSERT INTO atendimentos_clinicos"
            " (paciente_id, veterinario_id, agendamento_id, status, data_atendimento)"
            " VALUES (1, 1, 4242, 'Triagem', '2026-08-01 09:00:00'),"
            "        (1, 1, 4242, 'Triagem', '2026-08-01 09:00:00')"
        )
    )

applied = run_migrations()
status = get_migration_status()

# O runner registra o que adiou, para o deploy poder relatar.
deferred_reportado = [version for version, _motivo in get_deferred_migrations()]
deferred_motivos = [motivo for _version, motivo in get_deferred_migrations()]

with engine.begin() as conn:
    versoes_aplicadas = sorted(
        str(row[0]) for row in conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    )
    duplicatas = conn.execute(
        text("SELECT COUNT(*) FROM atendimentos_clinicos WHERE agendamento_id = 4242")
    ).scalar_one()

# Concilia e roda de novo: a versao adiada deve entrar sozinha.
with engine.begin() as conn:
    conn.execute(
        text(
            "DELETE FROM atendimentos_clinicos WHERE id = ("
            " SELECT MAX(id) FROM atendimentos_clinicos WHERE agendamento_id = 4242)"
        )
    )

applied_apos_conciliacao = run_migrations()
status_final = get_migration_status()

with engine.begin() as conn:
    indices_atendimento = {item["name"] for item in inspect(conn).get_indexes("atendimentos_clinicos")}

print(json.dumps({
    "deferred_reportado": deferred_reportado,
    "deferred_motivos": deferred_motivos,
    "deferred_apos_conciliacao": [v for v, _m in get_deferred_migrations()],
    "applied": applied,
    "pending_versions": status.get("pending_versions"),
    "versoes_aplicadas": versoes_aplicadas,
    "duplicatas": duplicatas,
    "applied_apos_conciliacao": applied_apos_conciliacao,
    "pending_final": status_final.get("pending_versions"),
    "tem_indice_unico": "ux_atendimentos_clinicos_agendamento_unico" in indices_atendimento,
}))
"""

VERSAO_ADIADA = "20260730_59"

# Erro real (nao pendencia de dados) tem de continuar abortando a esteira: se o
# schema ficou em estado desconhecido, seguir aplicando e pior que parar.
SCRIPT_ERRO_REAL = r"""
import json

from app.db.database import Base, engine
import app.models  # noqa: F401
import app.models.configuracao  # noqa: F401
from migrations import runner
from migrations.exceptions import MigrationDeferred

Base.metadata.create_all(bind=engine)


def _upgrade_ok(connection, dialect):
    return None


def _upgrade_erro(connection, dialect):
    raise ValueError("falha real de migracao")


def _upgrade_adiada(connection, dialect):
    raise MigrationDeferred("pendencia de dados")


def _fake(version, upgrade):
    return runner.Migration(
        version=version,
        description=f"fake {version}",
        upgrade=upgrade,
        source=runner.VERSIONS_DIR / f"{version}_fake.py",
    )


runner._discover_migrations = lambda: [
    _fake("99999999_01", _upgrade_adiada),
    _fake("99999999_02", _upgrade_erro),
    _fake("99999999_03", _upgrade_ok),
]

erro = None
try:
    runner.run_migrations()
except ValueError as exc:
    erro = str(exc)

status = runner.get_migration_status()
print(json.dumps({
    "erro": erro,
    "pending": status.get("pending_versions"),
    "unknown_applied": status.get("unknown_applied_versions"),
}))
"""


class MigrationDeferredNaoBloqueiaEsteiraTest(unittest.TestCase):
    def _run(self, script: str = SCRIPT) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migration-deferred.db"
            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite:///{db_path}"
            env["SECRET_KEY"] = "migration-deferred-test-secret-key-1234567890"

            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=BACKEND_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_pendencia_de_dados_nao_impede_migracoes_seguintes(self) -> None:
        payload = self._run()

        # A esteira nao abortou.
        self.assertGreater(payload["applied"], 0)

        # A versao com pendencia de dados ficou de fora e segue pendente.
        self.assertNotIn(VERSAO_ADIADA, payload["versoes_aplicadas"])
        self.assertIn(VERSAO_ADIADA, payload["pending_versions"])

        # E as migracoes POSTERIORES a ela foram aplicadas — o ponto da correcao.
        posteriores = [v for v in payload["versoes_aplicadas"] if v > VERSAO_ADIADA]
        self.assertTrue(
            posteriores,
            msg=f"nenhuma migracao posterior a {VERSAO_ADIADA} foi aplicada: {payload}",
        )

        # Nenhum registro clinico foi apagado ou alterado para "resolver" a duplicidade.
        self.assertEqual(payload["duplicatas"], 2)

    def test_runner_reporta_o_que_adiou_com_diagnostico_acionavel(self) -> None:
        payload = self._run()

        self.assertIn(VERSAO_ADIADA, payload["deferred_reportado"])
        # O motivo tem de dizer QUAL agendamento conciliar, senao o aviso e inutil.
        self.assertTrue(
            any("agendamento 4242" in motivo for motivo in payload["deferred_motivos"]),
            msg=payload["deferred_motivos"],
        )

    def test_relatorio_de_adiadas_zera_apos_a_conciliacao(self) -> None:
        payload = self._run()
        self.assertEqual(payload["deferred_apos_conciliacao"], [])

    def test_erro_real_continua_abortando_a_esteira(self) -> None:
        payload = self._run(SCRIPT_ERRO_REAL)

        # O erro propaga: nao foi convertido em "adiada".
        self.assertEqual(payload["erro"], "falha real de migracao")

        # A adiada anterior ao erro seguiu pendente, e a migracao DEPOIS do erro
        # nao foi aplicada.
        self.assertIn("99999999_01", payload["pending"])
        self.assertIn("99999999_02", payload["pending"])
        self.assertIn("99999999_03", payload["pending"])

    def test_apos_conciliacao_a_versao_adiada_entra_no_proximo_deploy(self) -> None:
        payload = self._run()

        self.assertEqual(payload["applied_apos_conciliacao"], 1)
        self.assertNotIn(VERSAO_ADIADA, payload["pending_final"])
        self.assertTrue(payload["tem_indice_unico"])


if __name__ == "__main__":
    unittest.main()
