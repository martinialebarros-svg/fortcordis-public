"""Review locking/replay on disposable localhost PostgreSQL only."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from tests.test_atendimento_assistente_lotes_postgres import database
from tests.test_atendimento_revisao_raca import CONTEXT, create_users, seed_job, load_migration
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote
from app.models.user import User
from app.schemas.atendimento_assistente_lote import RevisaoRacaEntrada, RevogacaoRevisaoRacaEntrada
from app.services import atendimento_assistente_lotes as service
from app.services import atendimento_assistente_lote_provider as provider


@pytest.fixture
def review_database(database, tmp_path, monkeypatch):
    engine, sessions, schema = database
    create_users(engine, sessions)
    identifier = seed_job(sessions, tmp_path)
    monkeypatch.setattr(service, "_contexto", lambda *args: copy.deepcopy(CONTEXT))
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    return engine, sessions, schema, identifier


def request_for(sessions, identifier, *, revoke=False):
    with sessions() as db:
        job = service.get_job(db, 8, 3, identifier)
        files = service._files(db, identifier)
        data = dict(request_id=str(uuid4()), revisao_token=service._review_token(job, files),
                    arquivo_ids=[item.id for item in files])
        if revoke:
            return RevogacaoRevisaoRacaEntrada(**data)
        return RevisaoRacaEntrada(**data, confirmo_mesmo_paciente=True, confirmo_apenas_raca=True,
                                  consentimento=True)


def apply(sessions, identifier, data, *, revoke=False):
    with sessions() as db:
        job = service.get_job(db, 8, 3, identifier, lock=True)
        value, event = service.review_race(db, job, data, SimpleNamespace(id=3), revoke=revoke)
        return value.status, event


def test_concurrent_same_request_records_once_and_schedules_once(review_database):
    _, sessions, _, identifier = review_database
    data = request_for(sessions, identifier)
    barrier = Barrier(2)
    def submit():
        barrier.wait(timeout=5)
        return apply(sessions, identifier, data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert all(status == "queued" for status, _ in outcomes)
    assert sum(event is not None for _, event in outcomes) == 1
    with sessions() as db:
        state = json.loads(db.get(Lote, identifier).revisoes_identidade_json)
        assert len(state["solicitacoes"]) == 1 and len(state["revisoes"]) == 2
    first = service._claim()
    assert first and first[0] == identifier
    assert service._claim() is None


def test_competing_new_requests_cannot_use_one_stale_review_token(review_database):
    _, sessions, _, identifier = review_database
    first = request_for(sessions, identifier)
    second = first.model_copy(update={"request_id": uuid4()})
    barrier = Barrier(2)
    def submit(payload):
        barrier.wait(timeout=5)
        try:
            apply(sessions, identifier, payload)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (first, second)))
    assert sorted(outcomes) == [200, 409]
    with sessions() as db:
        assert len(json.loads(db.get(Lote, identifier).revisoes_identidade_json)["solicitacoes"]) == 1


def test_revocation_cannot_race_an_active_synthesis(review_database, monkeypatch):
    _, sessions, _, identifier = review_database
    apply(sessions, identifier, request_for(sessions, identifier))
    claimed = service._claim()
    assert claimed
    entered, release = Event(), Event()
    calls = []
    def synthesis(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(timeout=8)
        return {"avisos": [], "bloqueado_integracao": False, "revisao_obrigatoria": True}
    monkeypatch.setattr(provider, "sintetizar_lote", synthesis)
    def unexpected(**kwargs):
        raise AssertionError("Cached PDF must never be sent again")
    monkeypatch.setattr(provider, "processar_exame", unexpected)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.process_job, *claimed)
        try:
            assert entered.wait(timeout=8)
            data = request_for(sessions, identifier, revoke=True)
            with pytest.raises(HTTPException) as error:
                apply(sessions, identifier, data, revoke=True)
            assert error.value.status_code == 409
            with sessions() as db:
                job = db.get(Lote, identifier)
                assert job.status == "processing" and job.lease_token == claimed[1]
        finally:
            release.set()
        future.result(timeout=8)
    assert len(calls) == 1
    with sessions() as db:
        job = db.get(Lote, identifier)
        assert job.status == "completed" and job.resultado_json
        assert len(json.loads(job.revisoes_identidade_json)["revisoes"]) == 2


def test_additive_migration_from_existing_109_keeps_rows_and_private_grants(review_database):
    engine, sessions, schema, identifier = review_database
    with engine.begin() as connection:
        before = connection.execute(text("SELECT resultado_json FROM atendimento_assistente_lotes WHERE id=:id"), {"id": identifier}).scalar()
        connection.execute(text("ALTER TABLE atendimento_assistente_lotes DROP COLUMN revisoes_identidade_json"))
        migration = load_migration()
        migration.upgrade(connection, "postgresql")
        migration.upgrade(connection, "postgresql")
        columns = [column["name"] for column in inspect(connection).get_columns("atendimento_assistente_lotes")]
        assert columns.count("revisoes_identidade_json") == 1
        row = connection.execute(text("SELECT resultado_json,revisoes_identidade_json FROM atendimento_assistente_lotes WHERE id=:id"), {"id": identifier}).one()
        assert tuple(row) == (before, None)
        relation = f"{schema}.atendimento_assistente_lotes"
        assert connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"), {"table": relation}).scalar() is True
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert connection.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                    {"role": role, "table": relation, "privilege": privilege}).scalar() is False
