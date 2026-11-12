"""A correcao publicada afeta apenas a linha canina transcrita de Cornell."""

import importlib.util
import os
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select


BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "referencia-eco-primary-test-secret-key-1234567890")

from app.models.referencia_eco import ReferenciaEco  # noqa: E402


MIGRATION_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260928_93_eco_cornell_25kg_dived.py"
)
spec = importlib.util.spec_from_file_location("eco_cornell_25kg_dived", MIGRATION_PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class ReferenciaEcoPrimaryCorrectionTest(unittest.TestCase):
    def test_somente_linha_cornell_transcrita_e_corrigida(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        ReferenciaEco.__table__.create(engine)
        try:
            with engine.begin() as connection:
                connection.execute(ReferenciaEco.__table__.insert(), [
                    {"especie": "Canina", "peso_kg": 25.0,
                     "lvid_d_min": 33.0, "lvid_d_max": 42.0},
                    {"especie": "Canina", "peso_kg": 25.0,
                     "lvid_d_min": 30.0, "lvid_d_max": 42.0},
                    {"especie": "Felina", "peso_kg": 25.0,
                     "lvid_d_min": 33.0, "lvid_d_max": 42.0},
                    {"especie": "Canina", "peso_kg": 20.0,
                     "lvid_d_min": 33.0, "lvid_d_max": 42.0},
                ])
                migration.upgrade(connection, "sqlite")
                migration.upgrade(connection, "sqlite")

            with engine.connect() as connection:
                rows = connection.execute(
                    select(
                        ReferenciaEco.especie,
                        ReferenciaEco.peso_kg,
                        ReferenciaEco.lvid_d_min,
                        ReferenciaEco.lvid_d_max,
                    ).order_by(ReferenciaEco.id)
                ).all()
            self.assertEqual([row.lvid_d_max for row in rows], [48.0, 42.0, 42.0, 42.0])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
