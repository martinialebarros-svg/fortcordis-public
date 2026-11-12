import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))


def _carregar(nome: str, arquivo: str):
    caminho = BACKEND_DIR / "migrations" / "versions" / arquivo
    spec = importlib.util.spec_from_file_location(nome, caminho)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar migracao: {caminho}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# A 75 cria a tabela com `modo TEXT NOT NULL DEFAULT 'suggest'`; a 78 e a que
# converte. Partir da 75 e o unico jeito de testar a conversao de verdade -
# criar a tabela pelo model produziria uma coluna que ja nasce anulavel.
MIGRACAO_75 = _carregar("migration_20260820_75", "20260820_75_whatsapp_bot_atendimento.py")
MIGRACAO_78 = _carregar(
    "migration_20260825_78", "20260825_78_whatsapp_bot_conversa_modo_nulo.py"
)

TABELA = "whatsapp_bot_conversa_estado"


class WhatsAppBotConversaModoNuloMigrationTest(unittest.TestCase):
    def _engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'modo-nulo.db'}")
        return tmpdir, engine

    def _modo_nullable(self, engine) -> bool:
        for coluna in inspect(engine).get_columns(TABELA):
            if coluna["name"] == "modo":
                return bool(coluna.get("nullable", True))
        raise AssertionError("coluna 'modo' nao encontrada")

    def test_converte_coluna_e_zera_suggest_incidental(self) -> None:
        tmpdir, engine = self._engine()
        try:
            with engine.begin() as conn:
                MIGRACAO_75.upgrade(conn, "sqlite")
            self.assertFalse(self._modo_nullable(engine), "a 75 deve criar NOT NULL")

            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {TABELA} (wa_identity, modo, handoff_motivo) "
                        "VALUES ('5585900000001', 'suggest', 'emergencia')"
                    )
                )
                conn.execute(
                    text(
                        f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000002', 'off')"
                    )
                )
                conn.execute(
                    text(
                        f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000003', 'auto')"
                    )
                )

            with engine.begin() as conn:
                MIGRACAO_78.upgrade(conn, "sqlite")

            self.assertTrue(self._modo_nullable(engine), "a 78 deve tornar anulavel")

            with engine.begin() as conn:
                linhas = dict(
                    conn.execute(text(f"SELECT wa_identity, modo FROM {TABELA}")).all()
                )
                preservado = conn.execute(
                    text(f"SELECT handoff_motivo FROM {TABELA} WHERE wa_identity = '5585900000001'")
                ).scalar()

            # O 'suggest' incidental vira NULL - e o que devolve a conversa ao
            # portao do piloto. `off` e `auto` sao decisao de gente e ficam.
            self.assertIsNone(linhas["5585900000001"])
            self.assertEqual(linhas["5585900000002"], "off")
            self.assertEqual(linhas["5585900000003"], "auto")
            # O rebuild do SQLite copia coluna a coluna: se alguma ficar de
            # fora, o DROP TABLE seguinte apaga o dado em silencio.
            self.assertEqual(preservado, "emergencia")
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_aceita_null_depois_da_conversao(self) -> None:
        tmpdir, engine = self._engine()
        try:
            with engine.begin() as conn:
                MIGRACAO_75.upgrade(conn, "sqlite")
                MIGRACAO_78.upgrade(conn, "sqlite")
                conn.execute(
                    text(f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000004', NULL)")
                )
                gravado = conn.execute(
                    text(f"SELECT modo FROM {TABELA} WHERE wa_identity = '5585900000004'")
                ).scalar()
            self.assertIsNone(gravado)
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_segundo_run_nao_apaga_override_deliberado(self) -> None:
        """Idempotencia com dente.

        Rodar de novo nao pode zerar um 'suggest' escolhido DEPOIS da
        conversao - por isso a guarda sai cedo quando a coluna ja e anulavel,
        em vez de repetir o UPDATE.
        """
        tmpdir, engine = self._engine()
        try:
            with engine.begin() as conn:
                MIGRACAO_75.upgrade(conn, "sqlite")
                MIGRACAO_78.upgrade(conn, "sqlite")
                conn.execute(
                    text(
                        f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000005', 'suggest')"
                    )
                )
                MIGRACAO_78.upgrade(conn, "sqlite")
                gravado = conn.execute(
                    text(f"SELECT modo FROM {TABELA} WHERE wa_identity = '5585900000005'")
                ).scalar()
            self.assertEqual(gravado, "suggest")
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_tabela_inexistente_e_no_op(self) -> None:
        tmpdir, engine = self._engine()
        try:
            with engine.begin() as conn:
                MIGRACAO_78.upgrade(conn, "sqlite")
            self.assertNotIn(TABELA, inspect(engine).get_table_names())
        finally:
            engine.dispose()
            tmpdir.cleanup()


# O Migration CI roda com DATABASE_URL sqlite (migrations-ci.yml:37), entao o
# ramo PostgreSQL nao e exercitado la. Este teste fecha esse buraco quando ha um
# Postgres a mao, e pula quando nao ha - em vez de deixar o ramo sem cobertura
# nenhuma e o check verde dando falso conforto.
#
#   POSTGRES_TEST_URL=postgresql+psycopg2://postgres@127.0.0.1:5432/postgres pytest ...
POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "").strip()


@unittest.skipUnless(POSTGRES_TEST_URL, "POSTGRES_TEST_URL nao definida")
class WhatsAppBotConversaModoNuloPostgresTest(unittest.TestCase):
    """Mesma conversao, no dialeto que producao usa de verdade.

    O SQLite passa por rebuild da tabela; o Postgres por ALTER. Sao caminhos
    diferentes do mesmo arquivo, e so este cobre o `DROP DEFAULT` - sem ele um
    INSERT que apenas OMITA a coluna ressuscita 'suggest'.

    Cada teste roda num schema proprio, fixado no engine por `search_path`, de
    modo que a migracao nao precise saber que esta isolada.
    """

    def setUp(self) -> None:
        self.schema = f"modo_nulo_{uuid.uuid4().hex[:12]}"
        admin = create_engine(POSTGRES_TEST_URL)
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {self.schema}"))
        admin.dispose()
        self.engine = create_engine(
            POSTGRES_TEST_URL,
            connect_args={"options": f"-csearch_path={self.schema}"},
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        admin = create_engine(POSTGRES_TEST_URL)
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE"))
        admin.dispose()

    def _coluna_modo(self):
        with self.engine.begin() as conn:
            return conn.execute(
                text(
                    "SELECT is_nullable, column_default FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t AND column_name = 'modo'"
                ),
                {"s": self.schema, "t": TABELA},
            ).one()

    def test_alter_converte_e_derruba_o_default(self) -> None:
        with self.engine.begin() as conn:
            MIGRACAO_75.upgrade(conn, "postgresql")
        is_nullable, default = self._coluna_modo()
        self.assertEqual(is_nullable, "NO", "a 75 deve criar NOT NULL")
        self.assertIsNotNone(default, "a 75 deve criar com DEFAULT")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {TABELA} (wa_identity, modo, handoff_motivo) "
                    "VALUES ('5585900000001', 'suggest', 'emergencia')"
                )
            )
            conn.execute(
                text(f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000002', 'off')")
            )

        with self.engine.begin() as conn:
            MIGRACAO_78.upgrade(conn, "postgresql")

        is_nullable, default = self._coluna_modo()
        self.assertEqual(is_nullable, "YES", "DROP NOT NULL nao pegou")
        self.assertIsNone(default, "DROP DEFAULT nao pegou")

        with self.engine.begin() as conn:
            linhas = dict(conn.execute(text(f"SELECT wa_identity, modo FROM {TABELA}")).all())
            preservado = conn.execute(
                text(f"SELECT handoff_motivo FROM {TABELA} WHERE wa_identity = '5585900000001'")
            ).scalar()
        self.assertIsNone(linhas["5585900000001"])
        self.assertEqual(linhas["5585900000002"], "off")
        self.assertEqual(preservado, "emergencia")

        # Com o DEFAULT de pe, este INSERT gravaria 'suggest' e o furo
        # continuaria aberto por outro caminho.
        with self.engine.begin() as conn:
            conn.execute(text(f"INSERT INTO {TABELA} (wa_identity) VALUES ('5585900000003')"))
            omitido = conn.execute(
                text(f"SELECT modo FROM {TABELA} WHERE wa_identity = '5585900000003'")
            ).scalar()
        self.assertIsNone(omitido)

    def test_segundo_run_nao_apaga_override_deliberado(self) -> None:
        with self.engine.begin() as conn:
            MIGRACAO_75.upgrade(conn, "postgresql")
            MIGRACAO_78.upgrade(conn, "postgresql")
            conn.execute(
                text(f"INSERT INTO {TABELA} (wa_identity, modo) VALUES ('5585900000004', 'suggest')")
            )
            MIGRACAO_78.upgrade(conn, "postgresql")
            gravado = conn.execute(
                text(f"SELECT modo FROM {TABELA} WHERE wa_identity = '5585900000004'")
            ).scalar()
        self.assertEqual(gravado, "suggest")


if __name__ == "__main__":
    unittest.main()
