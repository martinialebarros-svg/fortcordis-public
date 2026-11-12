import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationCICycleTest(unittest.TestCase):
    def test_run_migrations_up_down_up_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migration-ci-cycle.db"
            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite:///{db_path}"
            env["SECRET_KEY"] = "migration-ci-cycle-test-secret-key-1234567890"

            script = r"""
import json
from sqlalchemy import inspect, text

from app.db.database import engine
from app.db.database import Base
import app.models  # noqa: F401
import app.models.configuracao  # noqa: F401
from migrations.runner import get_migration_status, run_migrations

Base.metadata.create_all(bind=engine)
applied_first = run_migrations()
status_first = get_migration_status()

with engine.begin() as conn:
    if conn.dialect.name == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=OFF"))
    insp = inspect(conn)
    tables = [name for name in insp.get_table_names() if not name.startswith("sqlite_")]
    for table_name in tables:
        safe_name = table_name.replace('"', '""')
        conn.execute(text(f'DROP TABLE IF EXISTS "{safe_name}"'))

Base.metadata.create_all(bind=engine)
applied_second = run_migrations()
status_second = get_migration_status()

payload = {
    "applied_first": applied_first,
    "applied_second": applied_second,
    "status_first": {
        "discovered_count": status_first.get("discovered_count"),
        "applied_count": status_first.get("applied_count"),
        "pending_count": status_first.get("pending_count"),
    },
    "status_second": {
        "discovered_count": status_second.get("discovered_count"),
        "applied_count": status_second.get("applied_count"),
        "pending_count": status_second.get("pending_count"),
    },
}
print(json.dumps(payload))
"""

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

            last_line = result.stdout.strip().splitlines()[-1]
            payload = json.loads(last_line)

            self.assertGreater(payload["applied_first"], 0)
            self.assertGreater(payload["applied_second"], 0)
            self.assertEqual(payload["status_first"]["pending_count"], 0)
            self.assertEqual(payload["status_second"]["pending_count"], 0)
            self.assertEqual(
                payload["status_first"]["discovered_count"],
                payload["status_first"]["applied_count"],
            )
            self.assertEqual(
                payload["status_second"]["discovered_count"],
                payload["status_second"]["applied_count"],
            )


if __name__ == "__main__":
    unittest.main()
