"""Synthetic records only; PostgreSQL parity uses a disposable local server."""
from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlparse
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-paciente-mesclagem-local-secret-123456789")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import pacientes
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_access import PortalAccessChallenge
from app.models.tutor import Tutor

migration = importlib.import_module("migrations.versions.20261106_108_pacientes_mesclagens")
BASE = "/pacientes/mesclagens"
PAR = {"principal_id": 1, "secundario_id": 2}


@pytest.fixture(params=("sqlite", "postgresql"))
def engine(request, tmp_path: Path):
    if request.param == "sqlite":
        db = create_engine(f"sqlite:///{tmp_path}/pacientes.db")
        yield db
        db.dispose()
        return
    url = os.environ.get("PACIENTES_MERGE_TEST_POSTGRES_URL") or os.environ.get("DOCUMENT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PostgreSQL descartável local não configurado")
    assert urlparse(url).hostname in {"localhost", "127.0.0.1"}
    root = create_engine(url)
    schema = "teste_mesclagem_" + uuid.uuid4().hex
    with root.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    db = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield db
    finally:
        db.dispose()
        with root.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


@pytest.fixture
def cenario(engine):
    for model in (Paciente, Tutor, Agendamento, AtendimentoClinico, AnexoAtendimento, Exame, Laudo, PortalAccessChallenge):
        model.__table__.create(engine)
    # Modelled as a pre-108 database; only the migration may add the column,
    # guards, indexes and audit table. Reapplication must be safe.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE pacientes DROP COLUMN mesclado_em_id"))
        migration.upgrade(conn, conn.dialect.name)
        migration.upgrade(conn, conn.dialect.name)
    Session = sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with Session.begin() as db:
        db.add(Tutor(id=15, nome="Tutor de teste", ativo=1))
        db.add_all([
            Paciente(id=1, nome="Pet antigo", tutor_id=15, ativo=1, especie="Canina", sexo="Fêmea"),
            Paciente(id=2, nome="Pet novo", tutor_id=15, ativo=1, especie="Canina", sexo="Femea"),
            Paciente(id=3, nome="Outro animal", tutor_id=15, ativo=1, especie="Canina"),
            Agendamento(id=10, paciente_id=2, tutor_id=15, inicio=now, status="Realizado", paciente="Snapshot original"),
            AtendimentoClinico(id=20, paciente_id=2, tutor_id=15, veterinario_id=7, agendamento_id=10,
                               status="Concluido", anamnese="Anamnese original", data_atendimento=now),
            Laudo(id=30, paciente_id=2, veterinario_id=7, agendamento_id=10, tipo="Ecocardiograma",
                  titulo="Laudo sintético", diagnostico="Texto original", status="Finalizado", data_laudo=now),
            Exame(id=40, paciente_id=2, laudo_id=30, atendimento_id=20, tipo_exame="Ecocardiograma",
                  resultado="Resultado original", status="Concluido", data_solicitacao=now),
            Exame(id=41, paciente_id=1, tipo_exame="Eletrocardiograma", status="Concluido", data_solicitacao=now),
            AnexoAtendimento(id=50, atendimento_id=20, exame_id=40, tipo="documento", url="/fixture/issued.pdf",
                             caminho_arquivo="/fixture/issued.pdf", arquivo_hash="a" * 64),
        ])
    admin = SimpleNamespace(id=7, nome="Admin sintético", tem_papel=lambda role: role == "admin")
    operator = SimpleNamespace(id=8, nome="Recepção sintética", tem_papel=lambda role: False)
    app = FastAPI()
    app.include_router(pacientes.router, prefix="/pacientes")

    def get_test_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, engine=engine, operator=operator, now=now)


def previa(c):
    r = c.client.post(f"{BASE}/previa", json=PAR)
    assert r.status_code == 200, r.text
    return r.json()


def payload(c, **changes):
    return {**PAR, "token_previa": previa(c)["token_previa"],
            "motivo": "Mesmo animal conferido pela equipe", "confirmar": True, **changes}


def scalar(c, sql):
    with c.engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def alterar(c, sql, params=None):
    with c.engine.begin() as conn:
        conn.execute(text(sql), params or {})


def test_preview_defer_resume_merge_and_replay_preserve_content(cenario):
    c = cenario
    pre = previa(c)
    assert pre["bloqueios"] == []
    assert pre["vinculos"]["exames"] == {"principal": 1, "secundario": 1}
    assert pre["registros"]["laudos"][0]["titulo"] == "Laudo sintético"
    assert pre["registros"]["atendimentos_clinicos"][0]["id"] == 20
    assert "resultado" not in pre["registros"]["exames"][0]
    assert scalar(c, "SELECT COUNT(*) FROM pacientes_mesclagens") == 0
    adiado = c.client.post(f"{BASE}/adiar", json=PAR)
    assert adiado.status_code == 200
    assert c.client.post(f"{BASE}/adiar", json=PAR).json()["id"] == adiado.json()["id"]
    assert c.client.get(BASE, params={"paciente_id": 2}).json()["items"][0]["estado"] == "pendente"
    assert scalar(c, "SELECT paciente_id FROM exames WHERE id=40") == 2
    body = payload(c)
    merged = c.client.post(f"{BASE}/confirmar", json=body)
    assert merged.status_code == 200, merged.text
    assert merged.json()["evidencia"]["movidos"]["exames"] == [40]
    assert merged.json()["id"] == adiado.json()["id"]
    assert c.client.post(f"{BASE}/confirmar", json=body).json() == merged.json()
    assert c.client.get(BASE).json()["items"] == []
    assert c.client.get(BASE, params={"estado": "historico"}).json()["items"] == [
        {**merged.json(), "principal_nome": "Pet antigo", "secundario_nome": "Pet novo"}]
    assert scalar(c, "SELECT mesclado_em_id FROM pacientes WHERE id=2") == 1
    assert [r["id"] for r in c.client.get("/pacientes").json()["items"] if r["id"] in (1, 2)] == [1]
    for tabela, id_ in (("exames", 40), ("laudos", 30), ("atendimentos_clinicos", 20), ("agendamentos", 10)):
        assert scalar(c, f"SELECT paciente_id FROM {tabela} WHERE id={id_}") == 1
    assert scalar(c, "SELECT resultado FROM exames WHERE id=40") == "Resultado original"
    assert scalar(c, "SELECT atendimento_id FROM exames WHERE id=40") == 20
    assert scalar(c, "SELECT diagnostico FROM laudos WHERE id=30") == "Texto original"
    assert scalar(c, "SELECT anamnese FROM atendimentos_clinicos WHERE id=20") == "Anamnese original"
    assert scalar(c, "SELECT paciente FROM agendamentos WHERE id=10") == "Snapshot original"
    assert scalar(c, "SELECT exame_id FROM anexos_atendimentos WHERE id=50") == 40
    assert scalar(c, "SELECT caminho_arquivo FROM anexos_atendimentos WHERE id=50") == "/fixture/issued.pdf"
    assert scalar(c, "SELECT arquivo_hash FROM anexos_atendimentos WHERE id=50") == "a" * 64
    for sql in ("UPDATE pacientes SET ativo=1 WHERE id=2", "DELETE FROM pacientes WHERE id=2",
                "UPDATE exames SET paciente_id=2 WHERE id=40",
                "INSERT INTO exames(id,paciente_id,tipo_exame) VALUES(42,2,'Teste')"):
        with pytest.raises(DBAPIError, match="mesclado"):
            alterar(c, sql)
    assert c.client.put("/pacientes/2", json={"nome": "Não editar"}).status_code == 409
    assert c.client.delete("/pacientes/1").status_code == 409
    if c.engine.dialect.name == "postgresql":
        assert scalar(c, "SELECT relrowsecurity FROM pg_class WHERE oid='pacientes_mesclagens'::regclass") is True
        for role in ("anon", "authenticated"):
            if scalar(c, f"SELECT 1 FROM pg_roles WHERE rolname='{role}'"):
                assert not scalar(c, f"SELECT has_table_privilege('{role}', 'pacientes_mesclagens', 'SELECT')")
                assert not scalar(c, f"SELECT has_sequence_privilege('{role}', 'pacientes_mesclagens_id_seq', 'USAGE')")


def test_no_access_without_admin(cenario):
    c = cenario
    c.app.dependency_overrides[get_current_user] = lambda: c.operator
    assert c.client.get(BASE).status_code == 403
    assert c.client.get(BASE, params={"estado": "historico"}).status_code == 403
    for path in ("previa", "adiar", "confirmar"):
        data = {**PAR, "token_previa": "0"*64, "motivo": "Motivo sintético", "confirmar": True}
        assert c.client.post(f"{BASE}/{path}", json=data).status_code == 403
    assert scalar(c, "SELECT COUNT(*) FROM pacientes_mesclagens") == 0


def test_stale_preview_and_missing_confirmation(cenario):
    c = cenario
    body = payload(c)
    assert c.client.post(f"{BASE}/confirmar", json={**body, "confirmar": False}).status_code == 422
    alterar(c, "INSERT INTO exames(id,paciente_id,tipo_exame) VALUES(42,2,'Novo exame')")
    res = c.client.post(f"{BASE}/confirmar", json=body)
    assert res.status_code == 409 and "mudaram" in res.text
    assert scalar(c, "SELECT paciente_id FROM exames WHERE id=40") == 2
    assert scalar(c, "SELECT COUNT(*) FROM pacientes_mesclagens") == 0


def test_identity_and_open_consultation_block_but_can_defer(cenario):
    c = cenario
    alterar(c, "UPDATE pacientes SET microchip='123' WHERE id=1")
    alterar(c, "UPDATE pacientes SET microchip='456' WHERE id=2")
    alterar(c, "UPDATE atendimentos_clinicos SET status='Triagem' WHERE id=20")
    p = previa(c)
    assert any("microchip" in msg for msg in p["bloqueios"])
    assert any("em aberto" in msg for msg in p["bloqueios"])
    assert c.client.post(f"{BASE}/adiar", json=PAR).status_code == 200
    assert c.client.post(f"{BASE}/confirmar", json=payload(c)).status_code == 409
    assert scalar(c, "SELECT paciente_id FROM exames WHERE id=40") == 2


def test_guardian_external_portal_and_cross_patient_links(cenario):
    c = cenario
    alterar(c, "UPDATE pacientes SET tutor_id=99 WHERE id=2")
    assert any("mesmo tutor" in msg for msg in previa(c)["bloqueios"])
    alterar(c, "UPDATE pacientes SET tutor_id=15 WHERE id=2")
    alterar(c, "UPDATE exames SET paciente_id=3 WHERE id=40")
    assert any("outro paciente" in msg for msg in previa(c)["bloqueios"])
    alterar(c, "UPDATE exames SET paciente_id=2 WHERE id=40")
    alterar(c, """INSERT INTO portal_access_challenges(id,challenge_id,actor_type,actor_id,paciente_id,
              canal,contato_mascarado,scope_json,contexto_json,code_hash,status,failed_attempts,max_attempts,expires_at)
              VALUES(1,'id-ficticio','tutor',15,1,'email','x','[]','{}','x','consumed',0,3,:exp)""",
            {"exp": c.now + timedelta(minutes=5)})
    assert any("portal" in msg for msg in previa(c)["bloqueios"])
    assert c.client.post(f"{BASE}/confirmar", json=payload(c)).status_code == 409


def test_unknown_references_and_failed_write_roll_back(cenario):
    c = cenario
    alterar(c, "CREATE TABLE integracao_nao_mapeada (id integer primary key, patient_id integer)")
    alterar(c, "INSERT INTO integracao_nao_mapeada VALUES (1,2)")
    assert any("não pode transferir" in msg for msg in previa(c)["bloqueios"])
    alterar(c, "DROP TABLE integracao_nao_mapeada")
    adiado = c.client.post(f"{BASE}/adiar", json=PAR)
    body = payload(c)
    if c.engine.dialect.name == "sqlite":
        alterar(c, """CREATE TRIGGER falhar_laudo BEFORE UPDATE OF paciente_id ON laudos
                     BEGIN SELECT RAISE(ABORT,'falha forçada'); END""")
    else:
        alterar(c, """CREATE FUNCTION falhar_laudo() RETURNS trigger LANGUAGE plpgsql AS $$
                     BEGIN RAISE EXCEPTION 'falha forçada'; END; $$""")
        alterar(c, """CREATE TRIGGER falhar_laudo BEFORE UPDATE OF paciente_id ON laudos
                     FOR EACH ROW EXECUTE FUNCTION falhar_laudo()""")
    assert c.client.post(f"{BASE}/confirmar", json=body).status_code == 409
    assert scalar(c, "SELECT paciente_id FROM exames WHERE id=40") == 2
    assert scalar(c, "SELECT mesclado_em_id FROM pacientes WHERE id=2") is None
    assert c.client.get(BASE).json()["items"] == [
        {**adiado.json(), "principal_nome": "Pet antigo", "secundario_nome": "Pet novo"}]


def test_postgres_confirm_does_not_wait_for_active_writer(cenario):
    c = cenario
    if c.engine.dialect.name != "postgresql":
        pytest.skip("Teste específico de lock PostgreSQL")
    body = payload(c)
    with c.engine.connect() as conn:
        tx = conn.begin()
        conn.execute(text("UPDATE exames SET status='Em andamento' WHERE id=40"))
        try:
            assert c.client.post(f"{BASE}/confirmar", json=body).status_code == 409
        finally:
            tx.rollback()
    assert scalar(c, "SELECT mesclado_em_id FROM pacientes WHERE id=2") is None
