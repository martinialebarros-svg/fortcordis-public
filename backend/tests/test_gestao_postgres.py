"""Gestao em PostgreSQL local descartavel, sem aceitar banco operacional.

GESTAO_TEST_POSTGRES_URL aponta exclusivamente para gestao_test em loopback.
Localmente exige porta nao padrao, usuario gestao_test_owner e data_directory
igual a GESTAO_TEST_POSTGRES_DATA_DIR, cluster gestao-postgres-test- temporario.
No GitHub Actions aceita o service efemero com usuario postgres.
Cada teste usa e remove somente seu schema.
"""
import importlib.util
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "gestao-postgres-synthetic-secret-key-20261106")

from app.api.v1.endpoints import gestao
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.financeiro import (
    ContaPagar, ContaReceber, CreditoFinanceiro, OrdemServicoPagamento, Transacao,
)
from app.models.gestao import GestaoPremissas
from app.models.ordem_servico import OrdemServico
from migrations import runner

CONTEXT = {"data_inicio": "2026-10-01", "data_fim": "2026-10-03", "clinica_id": None, "regiao": None}
OPERATIONAL_MODELS = (
    Clinica, Configuracao, AgendaBloqueio, Agendamento, ContaPagar, ContaReceber,
    CreditoFinanceiro, OrdemServicoPagamento, Transacao, OrdemServico,
)


def _migration():
    path = Path(__file__).parents[1] / "migrations/versions/20261025_101_gestao_premissas.py"
    spec = importlib.util.spec_from_file_location("gestao_postgres_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg():
    url = os.environ.get("GESTAO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Configure o cluster PostgreSQL local descartavel de Gestao")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database == "gestao_test"
    assert not parsed.query, "Opcoes de conexao externas nao sao permitidas"
    on_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    data_dir = None
    if on_github_actions:
        assert parsed.username == "postgres"
    else:
        assert parsed.port and parsed.port != 5432 and parsed.username == "gestao_test_owner"
        data_dir = Path(os.environ["GESTAO_TEST_POSTGRES_DATA_DIR"]).resolve()
        assert data_dir.name == "data" and data_dir.parent.name.startswith("gestao-postgres-test-")
        assert data_dir.parent.parent == Path(os.environ.get("TMPDIR", "/tmp")).resolve()
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    schema = "gestao_test_" + uuid4().hex
    engine = None
    created = False
    try:
        with admin.begin() as connection:
            if data_dir is not None:
                observed = Path(connection.execute(text("SHOW data_directory")).scalar_one()).resolve()
                assert observed == data_dir, "Servidor diferente do cluster temporario autorizado"
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            created = True
        engine = create_engine(url, connect_args={
            "connect_timeout": 5,
            "options": f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=15000",
        })
        factory = sessionmaker(bind=engine, autoflush=False)
        yield SimpleNamespace(engine=engine, factory=factory, schema=schema)
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def api(pg):
    with pg.engine.begin() as connection:
        _migration().upgrade(connection, "postgresql")
        for model in (AuditoriaEvento, *OPERATIONAL_MODELS):
            model.__table__.create(connection)
    user = SimpleNamespace(id=12, nome="Admin sintetico", email="admin@example.invalid", tem_papel=lambda role: role == "admin")
    app = FastAPI()
    app.include_router(gestao.router, prefix="/api/v1/gestao")

    def get_test_db():
        with pg.factory() as db:
            yield db

    app.dependency_overrides[gestao.get_db] = get_test_db
    app.dependency_overrides[gestao.get_current_user] = lambda: user
    return SimpleNamespace(app=app, user=user, pg=pg)


def _save(http, revision, value, context=CONTEXT):
    return http.put("/api/v1/gestao/premissas", json={
        "expected_revision": revision, "contexto": context,
        "values": {"saldo_inicial": value, "horas_laudos": 0},
    })


def _snapshot(engine):
    with engine.connect() as connection:
        return {model.__tablename__: connection.execute(text(
            f"SELECT row_to_json(t)::text FROM {model.__tablename__} t ORDER BY id"
        )).scalars().all() for model in (GestaoPremissas, AuditoriaEvento, *OPERATIONAL_MODELS)}


def test_postgres_migration_idempotent_preserves_rows_and_revokes_direct_access(pg):
    migration = _migration()
    with pg.engine.connect() as connection:
        transaction = connection.begin()
        try:
            # CREATE ROLE and all grants are rolled back even on failure. Roles
            # already used by another synthetic CI step remain untouched.
            for role in ("anon", "authenticated"):
                exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar()
                if not exists:
                    connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            migration.upgrade(connection, "postgresql")
            assert connection.execute(text("SELECT COUNT(*) FROM gestao_premissas")).scalar_one() == 0
            connection.execute(text("""INSERT INTO gestao_premissas
                (id, revision, contexto_json, values_json, updated_at, updated_by_id)
                VALUES (1, 7, '{}', '{"saldo_inicial": 123}', CURRENT_TIMESTAMP, 12)"""))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {pg.schema} TO anon, authenticated"))
            connection.execute(text("GRANT ALL ON gestao_premissas TO PUBLIC, anon, authenticated"))
            migration.upgrade(connection, "postgresql")
            assert connection.execute(text("SELECT revision FROM gestao_premissas")).scalar_one() == 7
            assert connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid='gestao_premissas'::regclass")).scalar_one() is True
            assert connection.execute(text("""SELECT COUNT(*) FROM pg_class c,
                LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a
                WHERE c.oid='gestao_premissas'::regclass AND a.grantee=0""")).scalar_one() == 0
            for role in ("anon", "authenticated"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert connection.execute(text("SELECT has_table_privilege(:role, 'gestao_premissas', :privilege)"),
                                              {"role": role, "privilege": privilege}).scalar_one() is False
                nested = connection.begin_nested()
                try:
                    connection.execute(text(f"SET LOCAL ROLE {role}"))
                    with pytest.raises(DBAPIError) as denied:
                        connection.execute(text("SELECT * FROM gestao_premissas"))
                    assert denied.value.orig.pgcode == "42501"
                finally:
                    nested.rollback()
        finally:
            transaction.rollback()


def test_postgres_save_reopens_in_new_session_and_preserves_context(api):
    context = {**CONTEXT, "clinica_id": 22, "regiao": "Sul"}
    before_save = datetime.now(timezone.utc)
    with TestClient(api.app) as http:
        empty = http.get("/api/v1/gestao/premissas")
        assert empty.status_code == 200 and empty.json()["revision"] == 0
        saved = _save(http, 0, -200, context)
        assert saved.status_code == 200
    with TestClient(api.app) as reopened:
        payload = reopened.get("/api/v1/gestao/premissas").json()
        assert payload["revision"] == 1 and payload["contexto"] == context
        assert payload["values"]["saldo_inicial"] == -200
        assert payload["values"]["horas_laudos"] == 0
        assert payload["values"]["custos_variaveis"] is None
        persisted_at = datetime.fromisoformat(payload["updated_at"])
        assert payload["updated_by_id"] == 12 and persisted_at.tzinfo is not None
        assert before_save <= persisted_at <= datetime.now(timezone.utc)
        assert persisted_at == datetime.fromisoformat(saved.json()["updated_at"])
    with api.pg.factory() as db:
        audit = db.query(AuditoriaEvento).one()
        details = json.loads(audit.detalhes_json)
        assert audit.acao == "ATUALIZAR_PREMISSAS" and audit.entidade_id == "1"
        assert details["revision"] == 1 and details["contexto"] == context
        assert details["values"] == payload["values"]


@pytest.mark.parametrize("starting_revision", [0, 1], ids=["creation", "update"])
def test_postgres_concurrent_writes_have_one_winner_and_one_conflict(api, starting_revision):
    if starting_revision:
        with TestClient(api.app) as http:
            assert _save(http, 0, 10).status_code == 200
    gate = Barrier(2)
    backend_pids = set()
    operation = "INSERT INTO GESTAO_PREMISSAS" if starting_revision == 0 else "UPDATE GESTAO_PREMISSAS"

    def before_write(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith(operation):
            backend_pids.add(connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            gate.wait(timeout=10)

    def request(index):
        with TestClient(api.app) as http:
            response = _save(http, starting_revision, index * 100)
            return index, response.status_code, response.json()

    event.listen(api.pg.engine, "before_cursor_execute", before_write)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, [1, 2]))
    finally:
        event.remove(api.pg.engine, "before_cursor_execute", before_write)
    assert len(backend_pids) == 2
    assert sorted(status for _, status, _ in results) == [200, 409]
    winner = next(index for index, status, _ in results if status == 200)
    with api.pg.factory() as db:
        row = db.get(GestaoPremissas, 1)
        assert row.revision == starting_revision + 1
        assert json.loads(row.values_json)["saldo_inicial"] == winner * 100
        assert db.query(AuditoriaEvento).count() == starting_revision + 1
        latest = db.query(AuditoriaEvento).order_by(AuditoriaEvento.id.desc()).first()
        assert json.loads(latest.detalhes_json)["values"]["saldo_inicial"] == winner * 100


@pytest.mark.parametrize("starting_revision", [0, 1], ids=["creation", "update"])
def test_postgres_audit_failure_rolls_back_row_revision_and_audit(api, monkeypatch, starting_revision):
    with TestClient(api.app) as http:
        if starting_revision:
            assert _save(http, 0, 80).status_code == 200
        before = _snapshot(api.pg.engine)
        original = gestao.registrar_auditoria

        def fail_after_flush(**kwargs):
            original(**kwargs)
            raise OperationalError("synthetic failure after audit flush", {}, Exception("synthetic"))

        monkeypatch.setattr(gestao, "registrar_auditoria", fail_after_flush)
        result = _save(http, starting_revision, 999)
        assert result.status_code == 503
        assert "synthetic failure" not in result.text
    assert _snapshot(api.pg.engine) == before


def test_postgres_non_admin_has_no_sql_or_side_effects(api):
    api.user.tem_papel = lambda role: False
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    before = _snapshot(api.pg.engine)
    event.listen(api.pg.engine, "before_cursor_execute", observe)
    try:
        with TestClient(api.app) as http:
            assert http.get("/api/v1/gestao/premissas").status_code == 403
            assert _save(http, 0, 10).status_code == 403
            assert http.post("/api/v1/gestao/painel", json=CONTEXT).status_code == 403
    finally:
        event.remove(api.pg.engine, "before_cursor_execute", observe)
    assert statements == []
    assert _snapshot(api.pg.engine) == before


def test_postgres_simulation_exercises_six_aggregators_without_persistence(api):
    with api.pg.factory() as db:
        db.add(Clinica(id=1, nome="Parceiro sintetico", regiao_operacional="Norte"))
        db.add(OrdemServico(id=1, numero_os="GESTAO-PG-1", paciente_id=999, servico_id=1,
                           agendamento_id=1, clinica_id=1, data_atendimento=datetime(2026, 10, 1, 9),
                           valor_final=100, status="Pendente"))
        db.add_all([
            Agendamento(id=1, clinica_id=1, data="2026-10-01", hora="09:00",
                        inicio=datetime(2026, 10, 1, 9), fim=datetime(2026, 10, 1, 10),
                        status="Realizado", paciente="PRIVATE-SYNTHETIC", tutor="PRIVATE-SYNTHETIC"),
            Agendamento(id=2, clinica_id=1, data="2026-10-01", hora="10:00",
                        inicio=datetime(2026, 10, 1, 10), fim=datetime(2026, 10, 1, 11), status="Cancelado"),
        ])
        db.commit()
    before = _snapshot(api.pg.engine)
    statements = []

    def observe(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().upper())

    event.listen(api.pg.engine, "before_cursor_execute", observe)
    try:
        with TestClient(api.app) as http:
            assert http.get("/api/v1/gestao/premissas").status_code == 200
            response = http.post("/api/v1/gestao/painel", json={**CONTEXT, "premissas": {
                "tributos_percentual": 10, "taxas_percentual": 0, "repasses_percentual": 0,
                "custos_variaveis": 20, "horas_atendimento": 1, "horas_laudos": 1, "horas_deslocamento": 0,
                "movimentos": [{"data": "2026-09-02", "tipo": "saida", "valor": 80,
                                "recorrencia": "mensal", "descricao": "Material sintetico"}],
            }})
    finally:
        event.remove(api.pg.engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["atual"]) == {"contribuicao", "recebimento", "concentracao", "caixa", "ocupacao", "cancelamentos"}
    assert body["atual"]["contribuicao"]["por_hora"] == 35
    assert body["atual"]["concentracao"]["top1_pct"] == 100
    assert body["atual"]["cancelamentos"]["taxa_pct"] == 50
    assert body["atual"]["caixa"]["saidas_premissas"] == 80
    assert body["anterior"]["contribuicao"]["por_hora"] is None
    assert not any(item["fonte"] == "premissa" for item in body["anterior"]["caixa"]["detalhes"])
    assert "PRIVATE-SYNTHETIC" not in response.text
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for statement in statements)
    assert _snapshot(api.pg.engine) == before


def test_postgres_runner_applies_missing_101_after_107_without_replaying_applied_versions(pg, monkeypatch):
    migrations = runner.list_migrations()
    target = next(m for m in migrations if m.version == "20261025_101")
    assert any(m.version == "20261105_107" for m in migrations)
    latest_version = max(migration.version for migration in migrations)
    with pg.engine.begin() as connection:
        runner._ensure_schema_migrations_table(connection)
        for migration in migrations:
            if migration.version != target.version:
                connection.execute(text("INSERT INTO schema_migrations (version, description) VALUES (:v, :d)"),
                                   {"v": migration.version, "d": migration.description})
        connection.execute(text("CREATE TABLE preservation_probe (id integer PRIMARY KEY, value text)"))
        connection.execute(text("INSERT INTO preservation_probe VALUES (1, 'synthetic preserved value')"))
        before = connection.execute(text("SELECT version, description, applied_at FROM schema_migrations ORDER BY version")).all()

    def already_applied_must_not_run(connection, dialect):
        raise AssertionError("Uma migracao ja registrada foi executada novamente")

    migrations = [
        migration if migration.version == target.version
        else replace(migration, upgrade=already_applied_must_not_run)
        for migration in migrations
    ]
    monkeypatch.setattr(runner, "engine", pg.engine)
    monkeypatch.setattr(runner, "_discover_migrations", lambda: migrations)
    before_status = runner.get_migration_status()
    assert before_status["pending_versions"] == [target.version]
    assert before_status["current_version"] == latest_version
    assert runner.run_migrations() == 1
    assert runner.run_migrations() == 0
    status = runner.get_migration_status()
    assert status["pending_count"] == 0
    assert status["current_version"] == status["latest_version"] == latest_version
    assert status["applied_count"] == len(migrations)
    with pg.engine.connect() as connection:
        after = connection.execute(text("SELECT version, description, applied_at FROM schema_migrations WHERE version <> :v ORDER BY version"),
                                   {"v": target.version}).all()
        assert after == before
        assert connection.execute(text("SELECT COUNT(*) FROM gestao_premissas")).scalar_one() == 0
        assert connection.execute(text("SELECT value FROM preservation_probe WHERE id=1")).scalar_one() == "synthetic preserved value"
