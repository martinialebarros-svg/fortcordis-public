"""Concorrencia real em PostgreSQL local descartavel (OS_BATCH_TEST_POSTGRES_URL).

O banco deve se chamar os_batch_test e estar em loopback. Cada caso cria e remove
um schema proprio, utiliza somente dados sinteticos e bloqueia efeitos externos.
"""

import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "os-batch-concurrency-test-secret-key-123456")

from app.api.v1.endpoints import ordens_servico as endpoint
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.financeiro import (
    BandeiraCartao, CreditoFinanceiro, FormaPagamentoConfiguracao,
    OrdemServicoPagamento, Transacao,
)
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


@pytest.fixture
def synthetic_postgres(monkeypatch):
    url = os.environ.get("OS_BATCH_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Defina OS_BATCH_TEST_POSTGRES_URL para PostgreSQL local descartavel")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "os_batch_test"
    schema = "os_batch_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={
        "options": f"-csearch_path={schema} -clock_timeout=8000 -cstatement_timeout=15000",
    })
    factory = sessionmaker(bind=engine, autoflush=False)
    user = SimpleNamespace(id=1, nome="Operador sintetico", email="test@example.invalid")
    request = Request({
        "type": "http", "method": "PATCH", "path": "/api/v1/ordens-servico/receber-lote",
        "headers": [], "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        "scheme": "http", "query_string": b"",
    })
    for name in ("registrar_auditoria", "send_financeiro_push_notification", "cancel_pending_os_payment_reminder"):
        monkeypatch.setattr(endpoint, name, lambda *args, **kwargs: None)
    try:
        for model in (Tutor, Paciente, Clinica, Servico, OrdemServico, Transacao,
                      OrdemServicoPagamento, CreditoFinanceiro, BandeiraCartao,
                      FormaPagamentoConfiguracao, AuditoriaEvento):
            model.__table__.create(engine)
        with factory() as db:
            tutor = Tutor(nome="Tutor sintetico", ativo=1)
            clinica = Clinica(nome="Clinica sintetica")
            servico = Servico(nome="Servico sintetico", preco=Decimal("100.00"))
            db.add_all([tutor, clinica, servico])
            db.flush()
            paciente = Paciente(nome="Paciente sintetico", especie="Canina", tutor_id=tutor.id, ativo=1)
            db.add(paciente)
            db.flush()
            orders = [OrdemServico(
                numero_os=f"OS-TEST-{index}", paciente_id=paciente.id,
                clinica_id=clinica.id, servico_id=servico.id,
                data_atendimento=datetime(2099, 1, 1, 10), tipo_horario="comercial",
                valor_servico=Decimal("100.00"), desconto=Decimal("0.00"),
                valor_final=Decimal("100.00"), status="Pendente",
                observacoes="Dado exclusivamente sintetico de teste",
            ) for index in range(1, 4)]
            db.add_all(orders)
            db.flush()
            ids = [order.id for order in orders]
            db.commit()
        yield SimpleNamespace(engine=engine, admin=admin, factory=factory, ids=ids, user=user, request=request)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _operate(ctx, db, operation, ids):
    if operation == "batch":
        return endpoint.receber_ordens_lote(
            endpoint.OrdensServicoReceberLoteInput(
                ordens=[{"os_id": os_id, "valor_final_esperado": "100.00"} for os_id in ids],
                pagamentos=[{"forma_pagamento": "dinheiro", "valor": 100 * len(ids)}],
            ), ctx.request, db=db, current_user=ctx.user,
        )
    os_id = ids[0]
    if operation == "payment":
        return endpoint.receber_ordem(os_id, endpoint.OrdemServicoReceberInput(
            forma_pagamento="dinheiro", valor_final_esperado="100.00",
        ), ctx.request, db=db, current_user=ctx.user)
    if operation == "cancel":
        return endpoint.atualizar_ordem(os_id, endpoint.OrdemServicoUpdate(status="Cancelado"),
                                      ctx.request, db=db, current_user=ctx.user)
    if operation == "adjust":
        return endpoint.ajustar_valor_ordem(os_id, endpoint.OrdemServicoAjustarValorInput(
            valor_final_esperado="100.00", novo_valor_final="90.00", motivo="Ajuste sintetico",
        ), ctx.request, db=db, current_user=ctx.user)
    if operation == "delete":
        return endpoint.deletar_ordem(os_id, ctx.request, db=db, current_user=ctx.user)
    if operation == "undo":
        return endpoint.desfazer_recebimento_ordem(os_id, ctx.request, db=db, current_user=ctx.user)
    raise AssertionError(operation)


def _race(ctx, winner_operation, winner_ids, loser_operation, loser_ids, shared_id):
    winner_locked, loser_loaded, release_winner = Event(), Event(), Event()
    loser_pid = []

    def run_winner():
        with ctx.factory() as db:
            endpoint._bloquear_os_para_escrita(db, shared_id)
            winner_locked.set()
            assert release_winner.wait(10), "Segunda sessao nao chegou ao bloqueio PostgreSQL"
            return _operate(ctx, db, winner_operation, winner_ids)

    def run_loser():
        with ctx.factory() as db:
            # Mantem referencias no identity map para provar a recarga apos o lock.
            preloaded = db.query(OrdemServico).filter(OrdemServico.id.in_(loser_ids)).all()
            assert all(order.status == "Pendente" for order in preloaded)
            loser_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            loser_loaded.set()
            try:
                return 200, _operate(ctx, db, loser_operation, loser_ids)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_winner)
        assert winner_locked.wait(5)
        second = pool.submit(run_loser)
        try:
            assert loser_loaded.wait(5)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with ctx.admin.connect() as connection:
                    blocked = connection.execute(text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": loser_pid[0]}).scalar()
                if blocked:
                    break
                if second.done():
                    second.result()
                    break
                time.sleep(0.01)
            assert blocked, "Operacao concorrente nao aguardou o lock real da OS"
        finally:
            release_winner.set()
        return first.result(timeout=15), second.result(timeout=15)


@pytest.mark.parametrize("winner", ["payment", "cancel", "adjust", "delete", "batch"])
def test_lote_concorrente_aborta_integralmente_apos_outra_operacao(synthetic_postgres, winner):
    ctx = synthetic_postgres
    one, shared, untouched = ctx.ids
    winner_ids = [shared, one] if winner == "batch" else [shared]
    result, (status_code, _) = _race(ctx, winner, winner_ids, "batch", [untouched, shared], shared)
    assert status_code == 409
    with ctx.factory() as db:
        assert db.get(OrdemServico, untouched).status == "Pendente"
        assert db.query(OrdemServicoPagamento).filter_by(ordem_servico_id=untouched).count() == 0
        assert db.query(CreditoFinanceiro).count() == 0
        expected_payments = 2 if winner == "batch" else int(winner == "payment")
        assert db.query(Transacao).filter_by(status="Recebido").count() == expected_payments
        assert db.query(OrdemServicoPagamento).count() == expected_payments
        if winner == "batch":
            assert sorted(result["os_ids"]) == sorted(winner_ids)
            assert all(db.get(OrdemServico, os_id).status == "Pago" for os_id in winner_ids)
        elif winner == "delete":
            assert db.get(OrdemServico, shared) is None
        elif winner == "cancel":
            assert db.get(OrdemServico, shared).status == "Cancelado"
        elif winner == "adjust":
            assert db.get(OrdemServico, shared).valor_final == Decimal("90.00")


@pytest.mark.parametrize("loser,expected_status", [
    ("payment", 400), ("cancel", 409), ("adjust", 409), ("delete", 409), ("undo", 200),
])
def test_lote_vencedor_serializa_escritores_individuais(synthetic_postgres, loser, expected_status):
    ctx = synthetic_postgres
    one, shared, _ = ctx.ids
    result, (status_code, _) = _race(ctx, "batch", [shared, one], loser, [shared], shared)
    assert status_code == expected_status
    assert sorted(result["os_ids"]) == sorted([one, shared])
    with ctx.factory() as db:
        assert db.get(OrdemServico, one).status == "Pago"
        assert db.get(OrdemServico, shared).status == ("Pendente" if loser == "undo" else "Pago")
        assert db.query(OrdemServicoPagamento).count() == 2
        assert db.query(Transacao).filter_by(status="Recebido").count() == (1 if loser == "undo" else 2)
        assert db.query(Transacao).filter_by(status="Cancelado").count() == int(loser == "undo")
        assert db.query(CreditoFinanceiro).count() == 0
