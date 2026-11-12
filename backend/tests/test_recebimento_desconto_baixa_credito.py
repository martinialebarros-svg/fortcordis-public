import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "credito-baixa-test-secret-key-1234567890")
from app.api.v1.endpoints import financeiro, ordens_servico
from app.db.database import get_db
from app.core.security import get_current_user
from app.models.auditoria_evento import AuditoriaEvento
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao, ConfiguracaoUsuario
from app.models.financeiro import (CreditoFinanceiro, Transacao, OrdemServicoPagamento,
                                   FormaPagamentoConfiguracao, BandeiraCartao)
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


@pytest.fixture(params=["sqlite", "postgres"])
def ambiente(tmp_path, request):
    admin = None
    schema = None
    if request.param == "postgres":
        url = os.environ.get("OS_BATCH_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Defina OS_BATCH_TEST_POSTGRES_URL para Postgres local descartavel")
        parsed = make_url(url)
        assert parsed.get_backend_name() == "postgresql"
        assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "os_batch_test"
        schema = "credito_baixa_test_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=8000 -cstatement_timeout=15000"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'teste.db'}", connect_args={"check_same_thread": False})
    for model in (Tutor, Paciente, Clinica, Servico, Configuracao, ConfiguracaoUsuario, Agendamento,
                  OrdemServico, CreditoFinanceiro, Transacao, OrdemServicoPagamento,
                  FormaPagamentoConfiguracao, BandeiraCartao, AuditoriaEvento):
        model.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, autoflush=False)()
    tutor = Tutor(nome="Tutor sintetico", ativo=1)
    db.add(tutor)
    db.flush()
    paciente = Paciente(nome="Pet sintetico", tutor_id=tutor.id, especie="Canina", ativo=1)
    outro_pet = Paciente(nome="Outro pet", tutor_id=tutor.id, especie="Canina", ativo=1)
    clinica = Clinica(nome="Clinica sintetica")
    servico = Servico(nome="Servico sintetico", ativo=True)
    db.add_all([paciente, outro_pet, clinica, servico])
    db.flush()
    ag = Agendamento(paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=clinica.id,
                     servico_id=servico.id, inicio=datetime(2099, 1, 1, 8),
                     fim=datetime(2099, 1, 1, 9), status="Realizado")
    db.add(ag)
    db.flush()
    ordem = OrdemServico(agendamento_id=ag.id, numero_os="OS-TESTE-340", paciente_id=paciente.id, clinica_id=clinica.id,
                         servico_id=servico.id, valor_servico=Decimal("340"), desconto=0,
                         valor_final=340, status="Pendente", data_atendimento=datetime(2099, 1, 1))
    db.add(ordem)
    db.commit()
    user = SimpleNamespace(id=1, nome="Admin teste", tem_papel=lambda papel: papel == "admin")
    app = FastAPI()
    app.include_router(financeiro.router, prefix="/financeiro")
    app.include_router(ordens_servico.router, prefix="/ordens-servico")
    def session():
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: user
    with patch.object(financeiro, "registrar_auditoria"), patch.object(ordens_servico, "registrar_auditoria"), \
         patch.object(ordens_servico, "send_financeiro_push_notification"), \
         patch.object(ordens_servico, "cancel_pending_os_payment_reminder"):
        with TestClient(app) as client:
            yield SimpleNamespace(db=db, client=client, user=user, app=app, ordem=ordem,
                                  paciente=paciente, outro_pet=outro_pet, tutor=tutor, clinica=clinica)
    db.close()
    engine.dispose()
    if admin:
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def credito(a, valor=100, tipo="cliente", **kwargs):
    item = CreditoFinanceiro(tipo_destino=tipo, paciente_id=a.paciente.id if tipo == "cliente" else None,
                             tutor_id=a.tutor.id if tipo == "cliente" else None,
                             clinica_id=a.clinica.id if tipo == "clinica" else None,
                             valor=valor, status="Ativo", origem="manual", **kwargs)
    a.db.add(item)
    a.db.commit()
    return item


def baixa(a, valor=40, **kwargs):
    return {"tipo_destino": "cliente", "paciente_id": a.paciente.id, "valor": valor,
            "motivo": "Ajuste administrativo solicitado", "idempotency_key": str(uuid4()), **kwargs}


def test_desconto_340_90_recebe_250_sem_credito(ambiente):
    a = ambiente
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={
        "desconto": 90, "pagamentos": [{"forma_pagamento": "pix", "valor": 250}],
        "destino_credito_excedente": "nenhum"})
    assert r.status_code == 200, r.text
    assert r.json()["valor_os"] == 250
    assert r.json()["credito_gerado_id"] is None
    assert a.db.query(Transacao).one().valor == 250
    assert a.db.query(CreditoFinanceiro).count() == 0
    a.db.refresh(a.ordem)
    assert a.ordem.desconto == 90
    assert a.ordem.status == "Pago"


def test_desconto_integral_sem_entrada_ficticia(ambiente):
    a = ambiente
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={"desconto": 340, "pagamentos": []})
    assert r.status_code == 200, r.text
    assert a.db.query(Transacao).count() == 0
    assert a.db.query(CreditoFinanceiro).count() == 0


@pytest.mark.parametrize("tipo", ["cliente", "clinica"])
def test_baixa_independente_nao_movimenta_caixa_e_pode_desfazer(ambiente, tipo):
    a = ambiente
    original = credito(a, tipo=tipo)
    dados = baixa(a, tipo_destino=tipo, clinica_id=a.clinica.id if tipo == "clinica" else None)
    r = a.client.post("/financeiro/creditos/baixar", json=dados)
    assert r.status_code == 200, r.text
    assert r.json()["saldo"] == 60
    movimento = a.db.get(CreditoFinanceiro, r.json()["movimento_id"])
    assert movimento.valor == -40
    assert movimento.origem == "baixa_sem_contrapartida"
    assert movimento.ordem_servico_id is None and movimento.transacao_id is None
    assert movimento.criado_por_id == 1
    assert a.db.query(Transacao).count() == 0
    assert a.db.query(OrdemServicoPagamento).count() == 0
    a.db.refresh(a.ordem)
    assert a.ordem.status == "Pendente"
    assert original.status == "Ativo"
    url = f"/financeiro/creditos/{movimento.id}/desfazer-baixa"
    assert a.client.post(url).json()["saldo"] == 100
    assert a.client.post(url).json()["saldo"] == 100
    assert a.db.query(CreditoFinanceiro).count() == 2


def test_retry_idempotente_e_conflito_de_payload(ambiente):
    a = ambiente
    credito(a)
    dados = baixa(a)
    r1 = a.client.post("/financeiro/creditos/baixar", json=dados)
    r2 = a.client.post("/financeiro/creditos/baixar", json=dados)
    assert r1.json() == r2.json()
    assert a.db.query(CreditoFinanceiro).count() == 2
    assert a.client.post("/financeiro/creditos/baixar", json={**dados, "valor": 50}).status_code == 409


@pytest.mark.parametrize("valor", [0, -1, 100.01, "NaN", "Infinity", "0.001"])
def test_rejeita_valor_invalido_ou_acima_do_saldo(ambiente, valor):
    a = ambiente
    credito(a)
    assert a.client.post("/financeiro/creditos/baixar", json=baixa(a, valor)).status_code in (400, 422)
    assert a.db.query(CreditoFinanceiro).count() == 1


def test_sem_saldo_motivo_e_permissao(ambiente):
    a = ambiente
    assert a.client.post("/financeiro/creditos/baixar", json=baixa(a)).status_code == 400
    credito(a)
    assert a.client.post("/financeiro/creditos/baixar", json=baixa(a, motivo="   ")).status_code == 422
    a.user.tem_papel = lambda _: False
    assert a.client.post("/financeiro/creditos/baixar", json=baixa(a)).status_code == 403
    assert a.client.post("/financeiro/creditos/1/desfazer-baixa").status_code == 403
    assert a.db.query(CreditoFinanceiro).count() == 1


def test_saldo_compartilhado_por_tutor_e_consumo_apos_baixa(ambiente):
    a = ambiente
    credito(a)
    r = a.client.get("/financeiro/creditos/disponivel", params={"tipo_destino": "cliente", "paciente_id": a.outro_pet.id})
    assert r.json()["saldo"] == 100
    assert a.client.post("/financeiro/creditos/baixar", json=baixa(a, 60)).status_code == 200
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={
        "pagamentos": [{"forma_pagamento": "pix", "valor": 290}], "valor_credito_utilizado": 50})
    assert r.status_code == 400
    assert a.db.query(Transacao).count() == 0
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={
        "pagamentos": [{"forma_pagamento": "pix", "valor": 300}], "valor_credito_utilizado": 40})
    assert r.status_code == 200, r.text
    assert a.client.get("/financeiro/creditos/disponivel", params={"tipo_destino": "cliente", "paciente_id": a.paciente.id}).json()["saldo"] == 0


def test_desfazer_os_bloqueia_saldo_negativo_apos_baixa(ambiente):
    a = ambiente
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={
        "pagamentos": [{"forma_pagamento": "pix", "valor": 440}], "destino_credito_excedente": "cliente"})
    assert r.status_code == 200, r.text
    r = a.client.post("/financeiro/creditos/baixar", json=baixa(a, 40))
    assert r.status_code == 200
    baixa_id = r.json()["movimento_id"]
    assert a.client.patch(f"/ordens-servico/{a.ordem.id}/desfazer-recebimento").status_code == 400
    assert a.client.post(f"/financeiro/creditos/{baixa_id}/desfazer-baixa").status_code == 200
    assert a.client.patch(f"/ordens-servico/{a.ordem.id}/desfazer-recebimento").status_code == 200


@pytest.mark.parametrize("mesma_chave,valor,saldo_final", [(True, 40, 60), (False, 60, 40)])
def test_baixas_simultaneas(ambiente, mesma_chave, valor, saldo_final):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.schemas.financeiro import CreditoBaixaInput
    from app.services.credito_baixa_service import baixar_credito

    a = ambiente
    credito(a)
    dados = baixa(a, valor)
    outro = dados if mesma_chave else {**dados, "idempotency_key": str(uuid4())}
    engine = a.db.get_bind()
    barrier = Barrier(2)
    def enviar(payload):
        db = sessionmaker(bind=engine, autoflush=False)()
        try:
            barrier.wait(timeout=5)
            result = baixar_credito(db, CreditoBaixaInput(**payload), a.user)
            return result[0].id
        except HTTPException as exc:
            assert exc.status_code == 400
            return None
        finally:
            db.rollback()
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(enviar, [dados, outro]))
    assert len({id for id in resultados if id is not None}) == 1
    assert (resultados[0] == resultados[1]) if mesma_chave else (resultados.count(None) == 1)
    r = a.client.get("/financeiro/creditos/disponivel", params={"tipo_destino": "cliente", "paciente_id": a.paciente.id})
    assert r.json()["saldo"] == saldo_final


def test_excedente_real_continua_gerando_credito(ambiente):
    a = ambiente
    r = a.client.patch(f"/ordens-servico/{a.ordem.id}/receber", json={
        "desconto": 90, "pagamentos": [{"forma_pagamento": "pix", "valor": 340}],
        "destino_credito_excedente": "cliente"})
    assert r.status_code == 200, r.text
    assert r.json()["credito_gerado_valor"] == 90
    assert a.db.query(Transacao).one().valor == 340
    assert a.db.query(CreditoFinanceiro).one().valor == 90
