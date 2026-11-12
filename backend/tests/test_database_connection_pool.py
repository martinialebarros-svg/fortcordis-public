import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "database-connection-pool-test-secret-key-1234567890")

from app.core.config import Settings
from app.db import database


class DatabaseConnectionPoolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pool_settings = SimpleNamespace(
            DATABASE_CONNECT_TIMEOUT_SECONDS=10,
            DATABASE_POOL_PRE_PING=True,
            DATABASE_POOL_SIZE=5,
            DATABASE_MAX_OVERFLOW=5,
            DATABASE_POOL_TIMEOUT_SECONDS=15,
            DATABASE_POOL_RECYCLE_SECONDS=1800,
        )

    def test_postgresql_options_bound_capacity_and_waits(self) -> None:
        options = database.build_database_engine_options(
            "postgresql+psycopg2://fortcordis:secret@db.example.test:5432/fortcordis",
            self.pool_settings,
        )

        self.assertEqual(
            options,
            {
                "connect_args": {"connect_timeout": 10},
                "pool_pre_ping": True,
                "pool_size": 5,
                "max_overflow": 5,
                "pool_timeout": 15,
                "pool_recycle": 1800,
                "poolclass": database.ObservedQueuePool,
            },
        )

    def test_sqlite_keeps_only_its_thread_compatibility_option(self) -> None:
        options = database.build_database_engine_options(
            "sqlite:///./fortcordis.db",
            self.pool_settings,
        )

        self.assertEqual(options, {"connect_args": {"check_same_thread": False}})

    def test_engine_factory_delegates_the_postgresql_options(self) -> None:
        database_url = "postgresql+psycopg2://fortcordis:secret@db.example.test:5432/fortcordis"
        with patch("app.db.database.create_engine") as create_engine:
            database.create_database_engine(database_url, self.pool_settings)

        create_engine.assert_called_once_with(
            database_url,
            connect_args={"connect_timeout": 10},
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=15,
            pool_recycle=1800,
            poolclass=database.ObservedQueuePool,
        )

    def test_settings_reject_invalid_pool_capacity(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                DATABASE_URL="sqlite:///./fortcordis.db",
                DATABASE_POOL_SIZE=0,
            )


if __name__ == "__main__":
    unittest.main()
