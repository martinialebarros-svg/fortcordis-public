import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "fiscal-numero-unico-test-secret-key-1234567890")

from app.models.fiscal import NotaFiscal
from app.schemas.fiscal import NotaFiscalCreate
from app.services import fiscal_service

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260512_34_fiscal_numero_unico.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260512_34", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class FiscalNumeroUnicoTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "fiscal-numero-unico.db"
        engine = create_engine(f"sqlite:///{db_path}")
        NotaFiscal.__table__.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _payload(self) -> NotaFiscalCreate:
        return NotaFiscalCreate(
            os_id=1,
            tipo_cliente="PJ",
            cliente_nome="Clinica A",
            cliente_documento="11.111.111/0001-11",
            valor_servico=120.0,
            valor_desconto=20.0,
            atividade_cnae="7500-1/00",
            descricao_servico="Servico veterinario",
            natureza_operacao="Tributação no município",
            aliquota_iss=5.0,
        )

    def test_criar_nota_retries_when_numero_conflicts(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            db.add(
                NotaFiscal(
                    numero="NFO-2026-00001",
                    serie="1",
                    tipo_cliente="PJ",
                    cliente_nome="Ja existente",
                    cliente_documento="00.000.000/0001-00",
                    valor_servico=100,
                    valor_desconto=0,
                    valor_final=100,
                    aliquota_iss=5,
                    valor_iss=5,
                    natureza_operacao="Tributação no município",
                    status="rascunho",
                    created_at="2026-05-12 08:00:00",
                )
            )
            db.commit()

            with patch.object(
                fiscal_service,
                "_gerar_numero",
                side_effect=["NFO-2026-00001", "NFO-2026-00002"],
            ):
                nota = fiscal_service.criar_nota_fiscal(db, self._payload())

            self.assertEqual(nota.numero, "NFO-2026-00002")
            total = db.query(NotaFiscal).count()
            self.assertEqual(total, 2)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


class FiscalNumeroUnicoMigrationTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "fiscal-numero-migration.db"
        engine = create_engine(f"sqlite:///{db_path}")
        return tmpdir, engine

    def _create_table(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE notas_fiscais (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        numero TEXT
                    )
                    """
                )
            )

    def _index_exists(self, engine, name: str) -> bool:
        with engine.connect() as conn:
            rows = conn.execute(text("PRAGMA index_list('notas_fiscais')")).fetchall()
        return any(str(row[1]) == name for row in rows)

    def test_upgrade_fails_when_duplicate_numero_exists(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            self._create_table(engine)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO notas_fiscais (numero) VALUES (:n1), (:n2)"
                    ),
                    {"n1": "NFO-2026-00001", "n2": "NFO-2026-00001"},
                )

            with self.assertRaises(RuntimeError) as ctx:
                with engine.begin() as conn:
                    MIGRATION.upgrade(conn, "sqlite")

            self.assertIn("duplicidades", str(ctx.exception).lower())
            self.assertFalse(self._index_exists(engine, "uq_notas_fiscais_numero"))
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_upgrade_creates_unique_index_and_blocks_new_duplicates(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            self._create_table(engine)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO notas_fiscais (numero) VALUES (:n1), (:n2), (:n3), (:n4)"
                    ),
                    {
                        "n1": "NFO-2026-00001",
                        "n2": "NFO-2026-00002",
                        "n3": "",
                        "n4": "",
                    },
                )

            with engine.begin() as conn:
                MIGRATION.upgrade(conn, "sqlite")

            self.assertTrue(self._index_exists(engine, "uq_notas_fiscais_numero"))

            with self.assertRaises(IntegrityError):
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO notas_fiscais (numero) VALUES (:numero)"),
                        {"numero": "NFO-2026-00001"},
                    )

            # Valores em branco seguem permitidos pela condicao do indice parcial.
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO notas_fiscais (numero) VALUES (:numero)"),
                    {"numero": ""},
                )
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
