"""Contrato HTTP/admin, escrita isolada e revisão concorrente, sem banco remoto."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "gestao-local-synthetic-test-secret-key-123456")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.api.v1.endpoints import gestao
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.gestao import GestaoPremissas
from app.schemas.gestao import PremissasGestao

CONTEXT = {"data_inicio": "2026-10-01", "data_fim": "2026-10-03", "clinica_id": None, "regiao": None}


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (GestaoPremissas.__table__, AuditoriaEvento.__table__, Clinica.__table__):
        table.create(engine)
    session = sessionmaker(bind=engine)()
    user = SimpleNamespace(id=12, nome="Administrador sintético", email="admin@example.test", tem_papel=lambda role: role == "admin")
    app = FastAPI()
    app.include_router(gestao.router, prefix="/gestao")
    app.dependency_overrides[gestao.get_db] = lambda: session
    app.dependency_overrides[gestao.get_current_user] = lambda: user
    with TestClient(app) as http:
        yield http, session, user
    session.close()
    engine.dispose()


def test_admin_required_before_any_read_or_write(client):
    http, db, user = client
    user.tem_papel = lambda role: False
    for method, path, data in (
        ("get", "/gestao/premissas", None),
        ("post", "/gestao/painel", CONTEXT),
        ("put", "/gestao/premissas", {"expected_revision": 0, "contexto": CONTEXT, "values": {}}),
    ):
        response = getattr(http, method)(path, **({"json": data} if data else {}))
        assert response.status_code == 403
    assert db.query(GestaoPremissas).count() == 0
    assert db.query(AuditoriaEvento).count() == 0


def test_empty_read_does_not_seed_and_explicit_save_audits_atomically(client):
    http, db, _ = client
    initial = http.get("/gestao/premissas").json()
    assert initial["revision"] == 0
    assert initial["values"]["saldo_inicial"] is None
    assert initial["values"]["custos_variaveis"] is None
    assert db.query(GestaoPremissas).count() == 0
    saved = http.put("/gestao/premissas", json={"expected_revision": 0, "contexto": CONTEXT, "values": {"saldo_inicial": -200, "horas_laudos": 0}})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["contexto"] == CONTEXT
    assert saved.json()["values"]["saldo_inicial"] == -200
    assert saved.json()["updated_by_id"] == 12
    assert saved.json()["updated_at"].endswith("+00:00")
    assert db.query(AuditoriaEvento).count() == 1
    assert db.query(Clinica).count() == 0


def test_stale_revision_and_creation_race_cannot_overwrite(client):
    http, db, _ = client
    body = {"expected_revision": 0, "contexto": CONTEXT, "values": {"saldo_inicial": 80}}
    assert http.put("/gestao/premissas", json=body).status_code == 200
    body["values"]["saldo_inicial"] = 200
    assert http.put("/gestao/premissas", json=body).status_code == 409
    body["expected_revision"] = 1
    assert http.put("/gestao/premissas", json=body).status_code == 200
    body["values"]["saldo_inicial"] = 300
    assert http.put("/gestao/premissas", json=body).status_code == 409
    assert http.get("/gestao/premissas").json()["values"]["saldo_inicial"] == 200
    assert db.query(AuditoriaEvento).count() == 2


def test_audit_failure_rolls_back_assumptions(client):
    from sqlalchemy.exc import OperationalError
    http, db, _ = client
    with patch.object(gestao, "registrar_auditoria", side_effect=OperationalError("synthetic", {}, Exception("test"))):
        result = http.put("/gestao/premissas", json={"expected_revision": 0, "contexto": CONTEXT, "values": {}})
    assert result.status_code == 503
    assert db.query(GestaoPremissas).count() == 0


@pytest.mark.parametrize("change", [
    {"data_fim": "2026-09-30"}, {"data_fim": "2028-01-01"}, {"data_inicio": "bad-date"},
    {"premissas": {"tributos_percentual": -1}}, {"premissas": {"taxas_percentual": 101}},
    {"premissas": {"horas_atendimento": -3}}, {"premissas": {"inventado": 10}},
    {"premissas": {"saldo_inicial": True}},
    {"premissas": {"movimentos": [{"data": "2026-10-01", "tipo": "entrada", "valor": True, "descricao": "Teste"}]}},
    {"premissas": {"movimentos": [{"data": "2026-10-01", "tipo": "entrada", "valor": 1, "descricao": "   "}]}},
    {"premissas": {"movimentos": [{"data": "2026-10-01", "tipo": "entrada", "valor": 0, "descricao": "Teste"}]}},
])
def test_input_bounds(client, change):
    http, _, _ = client
    assert http.post("/gestao/painel", json={**CONTEXT, **change}).status_code == 422


def test_equivalent_previous_window_and_no_assumption_leak_or_writes(client):
    http, db, _ = client
    db.add(Clinica(id=1, nome="Clínica sintética", ativo=False, regiao_operacional="Norte"))
    db.add(Clinica(id=2, nome="Clínica sintética B", ativo=True, regiao_operacional="   ", cidade="Caucaia"))
    db.commit()
    with patch.object(gestao, "build_financial_metrics", return_value={"contribuicao": {"por_hora": None}}) as finance, patch.object(gestao, "build_agenda_metrics", return_value={"ocupacao": {"taxa_agendada_pct": None}}) as agenda:
        result = http.post("/gestao/painel", json={**CONTEXT, "premissas": {"horas_atendimento": 7, "saldo_inicial": 10}})
    assert result.status_code == 200
    body = result.json()
    assert body["periodo"]["anterior_inicio"] == "2026-09-28"
    assert body["periodo"]["anterior_fim"] == "2026-09-30"
    assert finance.call_args_list[0].args[5]["horas_atendimento"] == 7
    assert finance.call_args_list[1].args[5] == {}
    assert agenda.call_count == 2
    assert body["filtros"]["clinicas"][0]["ativo"] is False
    assert body["filtros"]["regioes"] == ["Caucaia", "Norte", "Não informada"]
    assert db.query(GestaoPremissas).count() == 0
    assert db.query(AuditoriaEvento).count() == 0
    assert "paciente" not in str(body).lower()


def test_non_finite_values_rejected():
    from pydantic import ValidationError
    for value in (float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            PremissasGestao(saldo_inicial=value)


def test_migration_is_idempotent_and_has_no_seed():
    path = Path(__file__).parents[1] / "migrations/versions/20261025_101_gestao_premissas.py"
    spec = importlib.util.spec_from_file_location("gestao_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        module.upgrade(connection, "sqlite")
        module.upgrade(connection, "sqlite")
        assert connection.execute(text("SELECT COUNT(*) FROM gestao_premissas")).scalar() == 0
    source = path.read_text()
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL ON TABLE" in source
    assert '"anon", "authenticated"' in source
    engine.dispose()


def test_real_aggregators_http_contract_and_database_immutability(client):
    from datetime import datetime
    from sqlalchemy import event
    from app.models.agenda_bloqueio import AgendaBloqueio
    from app.models.agendamento import Agendamento
    from app.models.configuracao import Configuracao
    from app.models.financeiro import ContaPagar, ContaReceber, CreditoFinanceiro, OrdemServicoPagamento, Transacao
    from app.models.ordem_servico import OrdemServico
    http, db, _ = client
    for model in (AgendaBloqueio, Agendamento, Configuracao, ContaPagar, ContaReceber, CreditoFinanceiro, OrdemServicoPagamento, Transacao, OrdemServico):
        model.__table__.create(db.bind, checkfirst=True)
    db.add(Clinica(id=1, nome="Parceiro sintético", regiao_operacional="Norte"))
    db.add(OrdemServico(id=1, numero_os="TESTE-1", paciente_id=999, servico_id=1, agendamento_id=1, clinica_id=1,
                        data_atendimento=datetime(2026, 10, 1, 9), valor_final=100, status="Pendente"))
    db.add(Agendamento(id=1, clinica_id=1, data="2026-10-01", hora="09:00", inicio=datetime(2026, 10, 1, 9), fim=datetime(2026, 10, 1, 10), status="Realizado", paciente="NÃO EXPOR", tutor="NÃO EXPOR"))
    db.add(Agendamento(id=2, clinica_id=1, data="2026-10-01", hora="10:00", inicio=datetime(2026, 10, 1, 10), fim=datetime(2026, 10, 1, 11), status="Cancelado"))
    db.commit()
    statements = []
    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().upper())
    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        result = http.post("/gestao/painel", json={**CONTEXT, "premissas": {"tributos_percentual": 10, "taxas_percentual": 0,
                            "repasses_percentual": 0, "custos_variaveis": 20, "horas_atendimento": 1, "horas_laudos": 1, "horas_deslocamento": 0,
                            "movimentos": [{"data": "2026-09-02", "tipo": "saida", "valor": 80,
                                            "recorrencia": "mensal", "descricao": "  Equipamento & materiais  "}]}})
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert result.status_code == 200, result.text
    body = result.json()
    assert set(body["atual"]) == {"contribuicao", "recebimento", "concentracao", "caixa", "ocupacao", "cancelamentos"}
    assert body["atual"]["contribuicao"]["por_hora"] == 35
    assert body["atual"]["cancelamentos"]["taxa_pct"] == 50
    assert body["atual"]["concentracao"]["top1_pct"] == 100
    assert body["atual"]["caixa"]["saldo_final"] is None
    cash_details = body["atual"]["caixa"]["detalhes"]
    assert [(row["data"], row["descricao"]) for row in cash_details if row["fonte"] == "premissa"] == [
        ("2026-10-02", "Equipamento & materiais"),
    ]
    assert body["atual"]["caixa"]["saidas_premissas"] == 80
    assert not any(row["fonte"] == "premissa" for row in body["anterior"]["caixa"]["detalhes"])
    assert body["anterior"]["contribuicao"]["por_hora"] is None
    assert "NÃO EXPOR" not in result.text
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE")) for s in statements)
