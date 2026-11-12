import importlib.util
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "fiscal-sequence-test-secret-key-1234567890")

from app.models.fiscal import FiscalNumeroSequencia, NotaFiscal
from app.schemas.fiscal import NotaFiscalCreate
from app.services import fiscal_service

MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260512_35_fiscal_numero_sequence.py"
)
SPEC = importlib.util.spec_from_file_location("migration_20260512_35", MIGRATION_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Nao foi possivel carregar migracao: {MIGRATION_PATH}")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class FiscalNumeroSequenceTest(unittest.TestCase):
    def _build_engine(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "fiscal-numero-sequence.db"
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        return tmpdir, engine

    def _payload(self, idx: int) -> NotaFiscalCreate:
        return NotaFiscalCreate(
            os_id=idx,
            tipo_cliente="PJ",
            cliente_nome=f"Clinica {idx}",
            cliente_documento=f"11.111.111/0001-{idx:02d}",
            valor_servico=120.0,
            valor_desconto=20.0,
            atividade_cnae="7500-1/00",
            descricao_servico="Servico veterinario",
            natureza_operacao="Tributação no município",
            aliquota_iss=5.0,
        )

    def test_migration_backfills_sequence_table_with_existing_numbers(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            NotaFiscal.__table__.create(engine, checkfirst=True)

            ano_atual = datetime.now().year
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO notas_fiscais (numero)
                        VALUES (:n1), (:n2), (:n3), (:n4)
                        """
                    ),
                    {
                        "n1": f"NFO-{ano_atual}-00002",
                        "n2": f"NFO-{ano_atual}-00007",
                        "n3": f"NFO-{ano_atual - 1}-00009",
                        "n4": "NF-INVALIDA",
                    },
                )
                MIGRATION.upgrade(conn, "sqlite")

            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT ano, ultimo_numero FROM fiscal_numero_sequencias ORDER BY ano"
                    )
                ).fetchall()

            self.assertEqual(rows, [(ano_atual - 1, 9), (ano_atual, 7)])
        finally:
            engine.dispose()
            tmpdir.cleanup()

    def test_concurrent_creations_generate_unique_numbers(self) -> None:
        tmpdir, engine = self._build_engine()
        try:
            NotaFiscal.__table__.create(engine, checkfirst=True)
            FiscalNumeroSequencia.__table__.create(engine, checkfirst=True)
            SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            def _worker(idx: int) -> str:
                session = SessionLocal()
                try:
                    nota = fiscal_service.criar_nota_fiscal(session, self._payload(idx))
                    return str(nota.numero)
                finally:
                    session.close()

            total = 12
            with ThreadPoolExecutor(max_workers=6) as executor:
                numeros = list(executor.map(_worker, range(1, total + 1)))

            self.assertEqual(len(numeros), total)
            self.assertEqual(len(set(numeros)), total)

            ano_atual = datetime.now().year
            for numero in numeros:
                self.assertTrue(numero.startswith(f"NFO-{ano_atual}-"))

            with engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM notas_fiscais")).scalar_one()
                seq = conn.execute(
                    text(
                        "SELECT ultimo_numero FROM fiscal_numero_sequencias WHERE ano = :ano"
                    ),
                    {"ano": ano_atual},
                ).scalar_one()

            self.assertEqual(count, total)
            self.assertEqual(seq, total)
        finally:
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
