import os
import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "tutor-schema-pool-test-secret-key-1234567890")

from app.api.v1.endpoints import tutores


class TutorSchemaPoolTest(unittest.TestCase):
    def test_schema_check_reuses_connection_and_preserves_legacy_support(self):
        for schema in (None, "id INTEGER PRIMARY KEY", (
            "id INTEGER PRIMARY KEY, latitude FLOAT, longitude FLOAT, "
            "place_id TEXT, endereco_normalizado TEXT"
        )):
            with self.subTest(schema=schema):
                engine = create_engine(
                    "sqlite:///:memory:", poolclass=QueuePool,
                    pool_size=1, max_overflow=0, pool_timeout=0.05,
                )
                try:
                    with engine.begin() as connection:
                        if schema:
                            connection.execute(text(f"CREATE TABLE tutores ({schema})"))
                    with Session(engine) as db:
                        # Authentication has already checked out the only connection.
                        db.execute(text("SELECT 1"))
                        tutores._ensure_tutores_georef_columns(db)
                        tutores._ensure_tutores_georef_columns(db)
                        if schema:
                            columns = {
                                column["name"]
                                for column in inspect(db.connection()).get_columns("tutores")
                            }
                            self.assertTrue({
                                "latitude", "longitude", "place_id", "endereco_normalizado"
                            }.issubset(columns))
                    self.assertEqual(engine.pool.checkedout(), 0)
                finally:
                    engine.dispose()


if __name__ == "__main__":
    unittest.main()
