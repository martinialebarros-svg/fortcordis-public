#!/usr/bin/env python3
"""Canário restrito a stage, com fixtures próprias e limpeza obrigatória.

Não chama emissão fiscal nem mensageria. Não imprime tokens ou cadastros reais.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if root != Path("/var/www/fortcordis-stage"):
        raise RuntimeError("Canário permitido somente no checkout de stage.")
    backend = root / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(root / "scripts"))
    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.models.clinica import Clinica
    from app.models.fiscal import FiscalFechamento, FiscalFechamentoOS, NotaFiscal
    from app.models.ordem_servico import OrdemServico
    from app.models.paciente import Paciente
    from app.models.servico import Servico
    from app.models.tutor import Tutor
    from deploy_authenticated_canary import _token_from_internal_backend

    if settings.APP_ENV != "stage":
        raise RuntimeError("APP_ENV precisa ser stage.")
    token = _token_from_internal_backend(str(backend))
    base = "http://127.0.0.1:8001/api/v1/fiscal"

    def request(path: str, payload: dict | None = None):
        headers = {"Authorization": "Bearer " + token}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    # numero_os tem limite de 50 caracteres inclusive nos bancos legados.
    nonce = uuid4().hex[:20]
    db = SessionLocal()
    os_ids: list[int] = []
    fixture_ids: dict[str, int] = {}
    created_key = None
    request_keys: list[str] = []
    checks: dict[str, bool] = {}
    cleanup_ok = False
    try:
        tutor = Tutor(nome="QA-TUTOR-PRIVADO-" + nonce, nome_key="qatutorprivado" + nonce, ativo=0)
        servico = Servico(nome="QA Fiscal - serviço sintético " + nonce, ativo=False, duracao_minutos=1)
        clinica = Clinica(nome="QA Fiscal " + nonce, razao_social="QA Fiscal sintético",
                          cnpj="12.345.678/0001-95", endereco="Rua de teste", numero="1",
                          bairro="Teste", cidade="Fortaleza", estado="CE", cep="60000-000",
                          telefone="85000000000", email="qa@example.invalid", ativo=False)
        db.add_all([tutor, servico, clinica])
        db.flush()
        fixture_ids.update(tutor=tutor.id, servico=servico.id, clinica=clinica.id)
        paciente = Paciente(nome="QA-PACIENTE-PRIVADO-" + nonce, nome_key="qapacienteprivado" + nonce,
                            tutor_id=tutor.id, especie="", ativo=0)
        db.add(paciente)
        db.flush()
        fixture_ids["paciente"] = paciente.id
        for suffix, date, status in (("apta", "2026-08-31", "Pendente"),
                                     ("cancelada", "2026-08-31", "Cancelado"),
                                     ("setembro", "2026-09-01", "Pago")):
            row = OrdemServico(numero_os=f"QA-FISCAL-{nonce}-{suffix}", agendamento_id=None,
                               paciente_id=paciente.id, clinica_id=clinica.id, servico_id=servico.id,
                               data_atendimento=datetime.fromisoformat(date + "T10:00:00-03:00"),
                               valor_servico=Decimal("250.00"), desconto=Decimal("0.00"),
                               valor_final=Decimal("250.00"), status=status)
            db.add(row)
            db.flush()
            os_ids.append(row.id)
        db.commit()
        status, raw, _ = request("/fechamentos/previa?competencia=2026-08")
        assert status == 200, "Prévia indisponível"
        items = {item["os_id"]: item for item in json.loads(raw)["items"] if item["os_id"] in os_ids}
        assert items[os_ids[0]]["elegivel"] and not items[os_ids[1]]["elegivel"]
        assert os_ids[2] not in items
        checks["competencia_canceladas_clinica_inativa"] = True

        created_key = str(uuid4())
        request_keys.append(created_key)
        payload = {"competencia": "2026-08", "os_ids": [os_ids[0]],
                   "chave_idempotencia": created_key, "confirmar_datas_prestacao": True}
        for name, invalid_ids in (("cancelada", [os_ids[1]]), ("outro_mes", [os_ids[2]]),
                                  ("ids_repetidos", [os_ids[0], os_ids[0]]),
                                  ("selecao_parcial", [os_ids[0], 2147483647])):
            bad = {**payload, "os_ids": invalid_ids, "chave_idempotencia": str(uuid4())}
            request_keys.append(bad["chave_idempotencia"])
            assert request("/fechamentos", bad)[0] == 422, name
            checks[name + "_recusada"] = True
        status, content, headers = request("/fechamentos", payload)
        assert status == 200, "Preparação indisponível"
        fechamento_id = int(next(value for key, value in headers.items() if key.lower() == "x-fechamento-id"))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert set(archive.namelist()) == {"servicos_contador.xlsx", "conferencia_contador.pdf", "mensagem_contador.txt", "manifesto.json"}
            manifest = json.loads(archive.read("manifesto.json"))
            assert manifest["competencia"] == "2026-08"
            assert manifest["totais"]["valor_final"] == "250.00"
            for member in ("mensagem_contador.txt", "manifesto.json"):
                assert b"QA-PACIENTE-PRIVADO-" not in archive.read(member)
                assert b"QA-TUTOR-PRIVADO-" not in archive.read(member)
            with zipfile.ZipFile(io.BytesIO(archive.read("servicos_contador.xlsx"))) as workbook:
                xml = b"".join(workbook.read(name) for name in workbook.namelist() if name.endswith(".xml"))
                assert b"QA-PACIENTE-PRIVADO-" not in xml and b"QA-TUTOR-PRIVADO-" not in xml
        checks["pacote_totais"] = True
        checks["dados_clinicos_omitidos"] = True
        retry_status, retry, _ = request("/fechamentos", payload)
        download_status, download, _ = request(f"/fechamentos/{fechamento_id}/download")
        assert retry_status == download_status == 200 and retry == download == content
        checks["retry_segunda_via_mesmos_bytes"] = True
        conflict_key = str(uuid4())
        request_keys.append(conflict_key)
        assert request("/fechamentos", {**payload, "chave_idempotencia": conflict_key})[0] == 409
        assert request("/os/exportar-lote", {"os_ids": [os_ids[0]], "formato": "xlsx"})[0] == 422
        checks["duplicidade_e_rota_legada_bloqueadas"] = True
        db.expire_all()
        assert db.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia == created_key).count() == 1
        assert db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id.in_(os_ids)).count() == 1
        assert db.query(NotaFiscal).filter(NotaFiscal.os_id.in_(os_ids)).count() == 0
        checks["persistencia_sem_nota_fiscal"] = True
        checks["checksum"] = hashlib.sha256(content).hexdigest() == db.query(FiscalFechamento.checksum).filter(FiscalFechamento.id == fechamento_id).scalar()
        assert checks["checksum"], "Checksum do pacote não corresponde aos bytes servidos"
    finally:
        db.rollback()
        # Um timeout HTTP não cancela o handler. Esperar os locks da fixture
        # antes de consultar o pacote permite enxergar seu commit final.
        if os_ids:
            db.query(OrdemServico.id).filter(OrdemServico.id.in_(os_ids)).order_by(OrdemServico.id).with_for_update().all()
        if request_keys:
            ids = [row.id for row in db.query(FiscalFechamento.id).filter(FiscalFechamento.chave_idempotencia.in_(request_keys))]
            if ids:
                db.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.fechamento_id.in_(ids)).delete(synchronize_session=False)
                db.query(FiscalFechamento).filter(FiscalFechamento.id.in_(ids)).delete(synchronize_session=False)
        if os_ids:
            db.query(OrdemServico).filter(OrdemServico.id.in_(os_ids), OrdemServico.numero_os.like(f"QA-FISCAL-{nonce}-%")).delete(synchronize_session=False)
        for name, model in (("paciente", Paciente), ("tutor", Tutor), ("servico", Servico), ("clinica", Clinica)):
            if name in fixture_ids:
                db.query(model).filter(model.id == fixture_ids[name]).delete(synchronize_session=False)
        db.commit()
        db.close()
        with SessionLocal() as verify:
            cleanup_ok = verify.query(OrdemServico).filter(OrdemServico.numero_os.like(f"QA-FISCAL-{nonce}-%")).count() == 0
            if request_keys:
                cleanup_ok = cleanup_ok and verify.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia.in_(request_keys)).count() == 0
            if os_ids:
                cleanup_ok = cleanup_ok and verify.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id.in_(os_ids)).count() == 0
            for name, model in (("paciente", Paciente), ("tutor", Tutor), ("servico", Servico), ("clinica", Clinica)):
                if name in fixture_ids:
                    cleanup_ok = cleanup_ok and verify.query(model).filter(model.id == fixture_ids[name]).count() == 0
        if not cleanup_ok:
            raise RuntimeError("Limpeza da fixture não foi confirmada.")
    print(json.dumps({"fiscal_stage_canary": "passed", "checks": checks, "fixtures_cleaned": cleanup_ok}, ensure_ascii=False))


if __name__ == "__main__":
    main()
