"""Real transaction checks against an explicitly configured disposable database."""
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "lote-postgres-synthetic-tests-only")
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote
from app.services import atendimento_assistente_lotes as service


@pytest.fixture
def database(monkeypatch):
    url = os.environ.get("LOTE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires disposable local LOTE_TEST_POSTGRES_URL")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "lote_test"
    schema = "lote_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        for role in ("anon", "authenticated"):
            if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migration_path = Path(__file__).resolve().parents[1] / "migrations/versions/20261108_109_atendimento_assistente_lotes.py"
    spec = importlib.util.spec_from_file_location("lote_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        migration.upgrade(conn, "postgresql")
        migration.upgrade(conn, "postgresql")
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(service, "SessionLocal", sessions)
    try:
        yield engine, sessions, schema
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(sessions, status="queued"):
    now = datetime.utcnow()
    identifier = str(uuid4())
    with sessions() as db:
        db.add(Lote(id=identifier, request_id=str(uuid4()), usuario_id=1,
            atendimento_id=1, paciente_id=1, manifest_hash="0" * 64,
            context_json="{}", transcricao="", status=status, created_at=now,
            expires_at=now + timedelta(hours=24),
            lease_token="old" if status == "processing" else None,
            lease_until=now - timedelta(seconds=1) if status == "processing" else None))
        db.commit()
    return identifier


@pytest.mark.parametrize("initial", ["queued", "processing"])
def test_only_one_worker_claims_and_stale_token_cannot_publish(database, initial):
    _, sessions, _ = database
    identifier = seed(sessions, initial)
    barrier = Barrier(2)
    def claim():
        barrier.wait(timeout=5)
        return service._claim()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    winners = [result for result in results if result]
    assert len(winners) == 1
    assert winners[0][0] == identifier
    with sessions() as db:
        assert service._lease_job(db, identifier, "old") is None
        assert service._lease_job(db, *winners[0]).id == identifier


def test_private_tables_have_rls_and_no_browser_role_privileges(database):
    engine, _, schema = database
    with engine.connect() as conn:
        for table in ("atendimento_assistente_lotes", "atendimento_assistente_lote_arquivos"):
            relation = f"{schema}.{table}"
            assert conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),
                                {"table": relation}).scalar() is True
            for role in ("anon", "authenticated"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert conn.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                        {"role": role, "table": relation, "privilege": privilege}).scalar() is False
