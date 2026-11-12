"""Synthetic review decisions: strict identity, immutable readings and one synthesis."""
import copy
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "race-review-synthetic-tests-only")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api.v1.endpoints import atendimento_assistente_lotes as endpoint
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote, AtendimentoAssistenteLoteArquivo as Arquivo
from app.models.papel import Papel, usuario_papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User
from app.schemas.atendimento_assistente_lote import RevisaoRacaEntrada, RevogacaoRevisaoRacaEntrada
from app.services import atendimento_assistente_lotes as service
from app.services import atendimento_assistente_lote_provider as provider

CONTEXT = {"atendimento_id": 8, "paciente": {"id": 17, "nome": "Paciente Fictício", "especie": "Canina", "raca": "Raça cadastrada"}, "consulta": {"anamnese": ""}}


def create_users(engine, sessions):
    for table in (User.__table__, Papel.__table__, usuario_papel, PapelPermissao.__table__):
        table.create(engine, checkfirst=True)
    with sessions() as db:
        medico = Papel(id=1, nome="medico")
        admin = Papel(id=2, nome="admin")
        reception = Papel(id=3, nome="recepcao")
        db.add_all([
            User(id=3, nome="Veterinário de teste", email="vet@example.test", ativo=1, papeis=[medico]),
            User(id=4, nome="Outro teste", email="other@example.test", ativo=1, papeis=[medico]),
            User(id=11, nome="Administrador de teste", email="admin@example.test", ativo=1, papeis=[admin]),
            User(id=12, nome="Recepção de teste", email="desk@example.test", ativo=1, papeis=[reception]),
            PapelPermissao(papel=medico, modulo="atendimento_clinico", visualizar=1, editar=1),
            PapelPermissao(papel=reception, modulo="atendimento_clinico", visualizar=1, editar=1),
        ])
        db.commit()


def seed_job(sessions, directory, *, owner=3, count=2):
    identifier = str(uuid4())
    now = datetime.utcnow()
    with sessions() as db:
        job = Lote(id=identifier, request_id=str(uuid4()), usuario_id=owner, atendimento_id=8,
                   paciente_id=17, manifest_hash="1" * 64, context_json=service._json(CONTEXT),
                   transcricao="Relato fictício preservado.", status="completed", created_at=now,
                   expires_at=now + timedelta(hours=24),
                   resultado_json=service._json({"bloqueado_integracao": True, "fontes": [], "avisos": []}))
        db.add(job)
        for index in range(count):
            file_id = str(uuid4())
            content = b"%PDF-1.4\nSynthetic original " + str(index).encode()
            path = directory / file_id
            path.write_bytes(content)
            normalized = f"{index + 1:02d}_exame.pdf"
            reading = {"arquivo": {"nome": normalized, "mime": "application/pdf", "paginas": 1},
                       "analise": {"campos": [], "fontes": [{"arquivo": normalized,
                           "paciente_nome": CONTEXT["paciente"]["nome"], "especie": "Canino",
                           "data_exame": None, "identidade": "divergente", "motivo": "Raça requer conferência."}],
                           "achados_exames": [], "sugestoes": [], "pendencias": ["Conferir raça."], "avisos": []}}
            db.add(Arquivo(lote_id=identifier, id=file_id, ordem=index, nome="exame.pdf", tipo="exame",
                           tamanho=len(content), mime="application/pdf", status="completed",
                           sha256=hashlib.sha256(content).hexdigest(), caminho=str(path),
                           resultado_json=service._json(reading)))
        db.commit()
    return identifier


@pytest.fixture
def case(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "review.db"), connect_args={"check_same_thread": False})
    sessions = sessionmaker(engine, expire_on_commit=False)
    create_users(engine, sessions)
    Lote.__table__.create(engine)
    Arquivo.__table__.create(engine)
    identifier = seed_job(sessions, tmp_path)
    context = copy.deepcopy(CONTEXT)
    monkeypatch.setattr(service, "SessionLocal", sessions)
    monkeypatch.setattr(service, "_contexto", lambda *args: copy.deepcopy(context))
    monkeypatch.setattr(endpoint, "_contexto", lambda *args: copy.deepcopy(context))
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    audit = Mock()
    monkeypatch.setattr(endpoint, "_auditar", audit)
    with sessions() as db:
        actor = db.get(User, 3)
        actor.papeis
        db.expunge(actor)
    current = {"actor": actor}
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1/atendimentos")
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: current["actor"]
    with TestClient(app) as client:
        value = SimpleNamespace(engine=engine, sessions=sessions, id=identifier, directory=tmp_path,
                                context=context, client=client, current=current, audit=audit)
        value.path = f"/api/v1/atendimentos/8/assistente/lotes/{identifier}"
        with sessions() as db:
            value.originals = {item.id: (item.sha256, item.resultado_json) for item in service._files(db, identifier)}
        yield value
    engine.dispose()


def state(case):
    response = case.client.get(case.path)
    assert response.status_code == 200, response.text
    return response.json()


def payload(case, selected=None, *, revoke=False):
    review = state(case)["revisao_raca"]
    data = {"request_id": str(uuid4()), "revisao_token": review["token"],
            "arquivo_ids": selected or [source["arquivo_id"] for source in review["fontes"]]}
    if not revoke:
        data.update(confirmo_mesmo_paciente=True, confirmo_apenas_raca=True, consentimento=True)
    return data


def confirm(case, data=None):
    return case.client.post(case.path + "/revisar-raca", json=data or payload(case))


def assert_originals(case):
    with case.sessions() as db:
        current = {item.id: (item.sha256, item.resultado_json) for item in service._files(db, case.id)}
        assert current == case.originals
        assert all(item.status == "completed" for item in service._files(db, case.id))
        assert db.get(Lote, case.id).context_json == service._json(CONTEXT)


def synthesize(case, monkeypatch, side_effect=None):
    output = {"campos": [], "fontes": [], "achados_exames": [], "sugestoes": [], "pendencias": [],
              "avisos": [], "bloqueado_integracao": False, "revisao_obrigatoria": True,
              "raca_pendente_revisao": True}
    synth = Mock(side_effect=side_effect, return_value=output)
    audio, exam = Mock(), Mock()
    monkeypatch.setattr(provider, "sintetizar_lote", synth)
    monkeypatch.setattr(provider, "processar_audio", audio)
    monkeypatch.setattr(provider, "processar_exame", exam)
    claimed = service._claim()
    assert claimed and claimed[0] == case.id
    service.process_job(*claimed)
    audio.assert_not_called()
    exam.assert_not_called()
    return synth


def test_explicit_review_persists_separately_and_synthesizes_cached_prefixed_sources(case, monkeypatch):
    initial = state(case)
    assert initial["revisao_raca"]["pode_revisar"] is True
    assert initial["revisao_raca"]["raca_cadastrada"] == "Raça cadastrada"
    assert all(source["elegivel"] and not source["confirmada"] for source in initial["revisao_raca"]["fontes"])
    data = payload(case)
    response = confirm(case, data)
    assert response.status_code == 200, response.text
    queued = response.json()
    assert queued["status"] == "queued" and queued["resultado"] is None
    assert all(source["confirmada"] for source in queued["revisao_raca"]["fontes"])
    assert queued["revisao_raca"]["token"] != data["revisao_token"]
    with case.sessions() as db:
        review = json.loads(db.get(Lote, case.id).revisoes_identidade_json)
        assert len(review["solicitacoes"]) == 1
        for file_id, entry in review["revisoes"].items():
            assert entry["usuario_id"] == 3 and entry["registrado_em"].endswith("Z")
            assert entry["arquivo_sha256"] == case.originals[file_id][0]
            assert entry["resultado_sha256"] == service._digest(case.originals[file_id][1])
    assert_originals(case)
    assert state(case)["revisao_raca"]["fontes"] == queued["revisao_raca"]["fontes"]
    synth = synthesize(case, monkeypatch)
    synth.assert_called_once()
    assert set(synth.call_args.kwargs["revisoes_raca"]) == {"01_exame.pdf", "02_exame.pdf"}
    assert state(case)["status"] == "completed"
    assert state(case)["resultado"]["raca_pendente_revisao"] is True
    assert_originals(case)
    assert case.audit.call_count == 1
    assert set(case.audit.call_args.args[-1]) == {"lote_id", "request_id", "acao", "arquivo_ids"}


def test_exact_replay_returns_processing_or_completed_without_another_queue(case, monkeypatch):
    data = payload(case)
    assert confirm(case, data).status_code == 200
    assert confirm(case, data).json()["status"] == "queued"
    assert case.audit.call_count == 1
    synthesize(case, monkeypatch)
    assert confirm(case, data).json()["status"] == "completed"
    assert case.audit.call_count == 1
    assert service._claim() is None
    assert_originals(case)


def test_conflicting_request_replay_is_rejected(case):
    data = payload(case)
    assert confirm(case, data).status_code == 200
    changed = {**data, "arquivo_ids": data["arquivo_ids"][:1]}
    assert confirm(case, changed).status_code == 409
    assert case.audit.call_count == 1


def test_partial_review_stays_blocked_and_second_explicit_review_queues(case, monkeypatch):
    files = [source["arquivo_id"] for source in state(case)["revisao_raca"]["fontes"]]
    response = confirm(case, payload(case, files[:1]))
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert service._claim() is None
    assert case.client.post(case.path + "/retomar").status_code == 409
    assert confirm(case, payload(case, files[1:])).json()["status"] == "queued"
    synthesize(case, monkeypatch).assert_called_once()
    assert_originals(case)


@pytest.mark.parametrize("field,value", [("paciente_nome", "Outro Paciente"), ("paciente_nome", None),
                                        ("especie", "Felina"), ("especie", None)])
def test_name_or_species_mismatch_cannot_be_reviewed_as_breed(case, field, value):
    with case.sessions() as db:
        item = service._files(db, case.id)[0]
        reading = json.loads(item.resultado_json)
        reading["analise"]["fontes"][0][field] = value
        item.resultado_json = service._json(reading)
        db.commit()
    current = state(case)
    assert current["revisao_raca"]["fontes"][0]["elegivel"] is False
    assert confirm(case).status_code == 409
    with case.sessions() as db:
        assert db.get(Lote, case.id).revisoes_identidade_json is None


def test_reading_reason_is_not_classified_from_keywords(case):
    with case.sessions() as db:
        item = service._files(db, case.id)[0]
        reading = json.loads(item.resultado_json)
        reading["analise"]["fontes"][0]["motivo"] = "Mensagem opaca sem palavra raça."
        item.resultado_json = service._json(reading)
        db.commit()
    assert state(case)["revisao_raca"]["fontes"][0]["elegivel"] is True
    assert state(case)["revisao_raca"]["fontes"][0]["confirmada"] is False


@pytest.mark.parametrize("owner,status", [(4, 404), (12, 403)])
def test_other_owner_or_non_veterinary_role_is_rejected(case, owner, status):
    data = payload(case)
    with case.sessions() as db:
        user = db.get(User, owner)
        user.papeis
        db.expunge(user)
        if owner == 12:
            db.get(Lote, case.id).usuario_id = owner
            db.commit()
    case.current["actor"] = user
    assert confirm(case, data).status_code == status


@pytest.mark.parametrize("change", ["inactive", "permission"])
def test_role_and_edit_permission_are_rechecked(case, change):
    data = payload(case)
    with case.sessions() as db:
        if change == "inactive":
            db.get(User, 3).ativo = 0
        else:
            db.query(PapelPermissao).filter_by(papel_id=1).one().editar = 0
        db.commit()
    assert confirm(case, data).status_code == 403
    assert state(case)["revisao_raca"]["pode_revisar"] is False


@pytest.mark.parametrize("change", ["context", "source_hash", "reading", "source_bytes", "expired", "token"])
def test_changed_context_source_expiry_or_stale_token_fails_closed(case, change):
    data = payload(case)
    expected = 409
    with case.sessions() as db:
        job, item = db.get(Lote, case.id), service._files(db, case.id)[0]
        if change == "context":
            case.context["consulta"]["anamnese"] = "Contexto alterado."
        elif change == "source_hash":
            item.sha256 = "f" * 64
        elif change == "reading":
            item.resultado_json += " "
        elif change == "source_bytes":
            Path(item.caminho).write_bytes(b"changed")
        elif change == "expired":
            job.expires_at = datetime.utcnow() - timedelta(seconds=1)
            expected = 410
        else:
            data["revisao_token"] = "0" * 64
        db.commit()
    assert confirm(case, data).status_code == expected
    with case.sessions() as db:
        assert db.get(Lote, case.id).revisoes_identidade_json is None


@pytest.mark.parametrize("field", ["confirmo_mesmo_paciente", "confirmo_apenas_raca", "consentimento"])
def test_explicit_confirmations_are_required(case, field):
    data = payload(case)
    data[field] = False
    assert confirm(case, data).status_code == 422


def test_duplicate_document_and_forged_user_metadata_are_refused(case):
    data = payload(case)
    data["arquivo_ids"] = data["arquivo_ids"][:1] * 2
    assert confirm(case, data).status_code == 422
    data = payload(case)
    data["usuario_id"] = 11
    assert confirm(case, data).status_code == 422


@pytest.mark.parametrize("change", ["permission", "source", "context"])
def test_worker_revalidates_after_synthesis_before_accepting_result(case, monkeypatch, change):
    assert confirm(case).status_code == 200
    def complete(**kwargs):
        if change == "context":
            case.context["consulta"]["anamnese"] = "Mudança durante síntese."
        else:
            with case.sessions() as db:
                if change == "permission":
                    db.query(PapelPermissao).filter_by(papel_id=1).one().editar = 0
                else:
                    service._files(db, case.id)[0].resultado_json += " "
                db.commit()
        return {"avisos": [], "bloqueado_integracao": False}
    synthesize(case, monkeypatch, complete).assert_called_once()
    with case.sessions() as db:
        job = db.get(Lote, case.id)
        assert job.status == "failed" and job.resultado_json is None


def test_worker_checks_reviewer_role_again_before_provider(case, monkeypatch):
    assert confirm(case).status_code == 200
    with case.sessions() as db:
        # Reception retains edit permission but cannot author a veterinary review.
        db.get(User, 3).papeis = [db.get(Papel, 3)]
        db.commit()
    synthesize(case, monkeypatch).assert_not_called()
    with case.sessions() as db:
        assert db.get(Lote, case.id).status == "failed"


def test_synthesis_failure_retries_only_synthesis_and_retains_review(case, monkeypatch):
    assert confirm(case).status_code == 200
    synthesize(case, monkeypatch, RuntimeError("synthetic provider failure")).assert_called_once()
    assert state(case)["status"] == "failed"
    assert all(source["confirmada"] for source in state(case)["revisao_raca"]["fontes"])
    assert case.client.post(case.path + "/retomar").json()["status"] == "queued"
    synthesize(case, monkeypatch).assert_called_once()
    assert_originals(case)


def test_revoke_invalidates_aggregate_without_scheduling_or_changing_readings(case, monkeypatch):
    assert confirm(case).status_code == 200
    synthesize(case, monkeypatch)
    data = payload(case, revoke=True)
    response = case.client.post(case.path + "/revogar-revisao-raca", json=data)
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["status"] == "failed" and current["resultado"] is None
    assert not any(source["confirmada"] for source in current["revisao_raca"]["fontes"])
    assert service._claim() is None
    assert case.client.post(case.path + "/revogar-revisao-raca", json=data).status_code == 200
    assert case.audit.call_count == 2
    assert_originals(case)


def test_revoke_while_processing_is_rejected_without_clearing_lease(case):
    assert confirm(case).status_code == 200
    claim = service._claim()
    data = payload(case, revoke=True)
    assert case.client.post(case.path + "/revogar-revisao-raca", json=data).status_code == 409
    with case.sessions() as db:
        job = db.get(Lote, case.id)
        assert job.status == "processing" and job.lease_token == claim[1]


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261109_110_atendimento_revisao_raca.py"
    spec = importlib.util.spec_from_file_location("race_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_additive_migration_preserves_existing_row_and_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE atendimento_assistente_lotes (id TEXT PRIMARY KEY, resultado_json TEXT)"))
        connection.execute(text("INSERT INTO atendimento_assistente_lotes VALUES ('synthetic','original')"))
        migration = load_migration()
        migration.upgrade(connection, "sqlite")
        migration.upgrade(connection, "sqlite")
        assert [c["name"] for c in inspect(connection).get_columns("atendimento_assistente_lotes")].count("revisoes_identidade_json") == 1
        assert connection.execute(text("SELECT resultado_json,revisoes_identidade_json FROM atendimento_assistente_lotes")).one() == ("original", None)
    engine.dispose()


@pytest.mark.parametrize("change", ["permission", "role", "context", "reading", "source_bytes"])
def test_completed_read_withholds_aggregate_when_manual_review_loses_validity(case, monkeypatch, change):
    data = payload(case)
    assert confirm(case, data).status_code == 200
    synthesize(case, monkeypatch)
    with case.sessions() as db:
        stored = db.get(Lote, case.id).resultado_json
        if change == "permission":
            db.query(PapelPermissao).filter_by(papel_id=1).one().editar = 0
        elif change == "role":
            db.get(User, 3).papeis = [db.get(Papel, 3)]
        elif change == "context":
            case.context["paciente"]["raca"] = "Raça modificada após conclusão"
        elif change == "reading":
            service._files(db, case.id)[0].resultado_json += " "
        else:
            Path(service._files(db, case.id)[0].caminho).write_bytes(b"modified")
        db.commit()
    current = state(case)
    assert current["status"] == "completed"
    assert current["resultado"] is None and current["erro"]
    assert not any(source["confirmada"] for source in current["revisao_raca"]["fontes"])
    with case.sessions() as db:
        assert db.get(Lote, case.id).resultado_json == stored
