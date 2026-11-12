#!/usr/bin/env python3
"""Canário fiscal isolado de stage; não emite NF nem envia mensagens.

Somente fixtures novas são alteradas. Tokens e dados cadastrais não são impressos.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

STAGE_ROOT = Path("/var/www/fortcordis-stage")
STAGE_PROJECT_REF = "dtguubpzjrkvqjryazjq"
PRODUCTION_PROJECT_REF = "wycxoueogfxdhyouhfhw"


def _validar_destino(root: Path, app_env: str, database_url: str) -> None:
    """Falhar antes de abrir sessão em produção ou em um destino desconhecido."""
    if root.resolve() != STAGE_ROOT.resolve() or app_env != "stage":
        raise RuntimeError("Canário permitido somente no checkout e ambiente de stage.")
    try:
        parsed = urllib.parse.urlsplit(database_url)
        hostname = (parsed.hostname or "").lower()
        username = urllib.parse.unquote(parsed.username or "").lower()
    except ValueError as exc:
        raise RuntimeError("Destino do banco não reconhecido; conexão recusada.") from exc
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
        raise RuntimeError("Formato de conexão PostgreSQL não reconhecido.")
    refs = set()
    for value in (hostname, username):
        refs.update(re.findall(r"(?<![a-z0-9])([a-z]{20})(?![a-z0-9])", value))
    if PRODUCTION_PROJECT_REF in refs:
        raise RuntimeError("Projeto de produção recusado pelo canário.")
    if refs != {STAGE_PROJECT_REF} or not hostname.endswith((".supabase.co", ".supabase.com")):
        raise RuntimeError("Projeto de stage não confirmado; conexão recusada.")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if root != STAGE_ROOT:
        raise RuntimeError("Canário permitido somente no checkout de stage.")
    backend = root / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(root / "scripts"))
    from app.core.config import settings

    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)

    from pypdf import PdfReader
    from app.db.database import SessionLocal
    from app.models.agendamento import Agendamento
    from app.models.clinica import Clinica
    from app.models.fiscal import FiscalAndamentoEvento, FiscalFechamento, FiscalFechamentoOS, FiscalRotinaPreferencia, NotaFiscal
    from app.models.laudo import Laudo
    from app.models.ordem_servico import OrdemServico
    from app.models.paciente import Paciente
    from app.models.servico import Servico
    from app.models.tutor import Tutor
    from deploy_authenticated_canary import _token_from_internal_backend
    from jose import jwt
    import zipfile

    token = _token_from_internal_backend(str(backend))
    actor_id = int(jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])["user_id"])
    base = "http://127.0.0.1:8001/api/v1/fiscal"

    def request(path: str, payload: dict | None = None, method: str | None = None):
        headers = {"Authorization": "Bearer " + token}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def get_json(path: str):
        status, raw, _ = request(path)
        assert status == 200, "Consulta fiscal indisponível"
        return json.loads(raw)

    nonce = uuid4().hex[:16]
    fixtures: dict[str, list[int]] = {name: [] for name in ("clinica", "tutor", "paciente", "servico", "agenda", "laudo", "os")}
    package_keys: list[str] = []
    checks: dict[str, bool] = {}
    db = SessionLocal()
    try:
        tutor = Tutor(nome="QA-TUTOR-PRIVADO-" + nonce, nome_key="qatutorprivado" + nonce, ativo=0)
        servico = Servico(nome="QA Rotina - serviço sintético " + nonce, ativo=False, duracao_minutos=1)
        own = Clinica(nome="QA Rotina " + nonce, razao_social="QA Rotina sintética",
                      cnpj="12.345.678/0001-95", endereco="Rua de teste", numero="1", bairro="Teste",
                      cidade="Fortaleza", estado="CE", cep="60000-000", telefone="85000000000",
                      email="qa@example.invalid", ativo=False)
        other = Clinica(nome="QA-OUTRO-TOMADOR-PRIVADO-" + nonce, cnpj="123", ativo=False)
        db.add_all([tutor, servico, own, other])
        db.flush()
        fixtures["tutor"].append(tutor.id)
        fixtures["servico"].append(servico.id)
        fixtures["clinica"].extend([own.id, other.id])
        paciente = Paciente(nome="QA-PACIENTE-PRIVADO-" + nonce, nome_key="qapacienteprivado" + nonce,
                            tutor_id=tutor.id, especie="Canina", ativo=0)
        db.add(paciente)
        db.flush()
        fixtures["paciente"].append(paciente.id)
        agenda = Agendamento(paciente_id=paciente.id, tutor_id=tutor.id, clinica_id=own.id,
                              servico_id=servico.id, inicio=datetime.fromisoformat("2026-08-01T10:00:00-03:00"),
                              fim=datetime.fromisoformat("2026-08-01T10:30:00-03:00"),
                              updated_at=datetime.now(timezone.utc),
                              status="Realizado", origem_atendimento="clinica_parceira")
        laudo = Laudo(paciente_id=paciente.id, veterinario_id=actor_id, clinic_id=own.id,
                      tipo="eletrocardiograma", titulo="QA Rotina " + nonce, status="Finalizado",
                      data_exame=datetime.fromisoformat("2026-08-25T10:00:00-03:00"))
        unrelated = Laudo(paciente_id=paciente.id, veterinario_id=actor_id, clinic_id=own.id,
                          tipo="eletrocardiograma", titulo="QA vínculo ausente " + nonce, status="Finalizado",
                          data_exame=datetime.fromisoformat("2026-08-20T10:00:00-03:00"))
        db.add_all([agenda, laudo, unrelated])
        db.flush()
        fixtures["agenda"].append(agenda.id)
        fixtures["laudo"].extend([laudo.id, unrelated.id])
        for suffix, date, clinic_id, agenda_id, laudo_id, value in (
            ("agenda", "2026-08-01", own.id, agenda.id, None, "100.10"),
            ("laudo", "2026-08-25", own.id, None, laudo.id, "200.20"),
            ("semprova", "2026-08-20", own.id, None, None, "50.00"),
            ("outro", "2026-08-20", other.id, None, None, "900.00"),
        ):
            row = OrdemServico(numero_os=f"QA-ROTINA-{nonce}-{suffix}", paciente_id=paciente.id,
                               clinica_id=clinic_id, servico_id=servico.id, agendamento_id=agenda_id,
                               laudo_id=laudo_id, origem_atendimento="clinica_parceira",
                               data_atendimento=datetime.fromisoformat(date + "T10:00:00-03:00"),
                               valor_servico=Decimal(value), desconto=Decimal("0.00"),
                               valor_final=Decimal(value), status="Pendente")
            db.add(row)
            db.flush()
            fixtures["os"].append(row.id)
        db.commit()
        os_agenda, os_laudo, os_sem_prova, os_outro = fixtures["os"]

        status, raw, _ = request(f"/rotinas/clinicas/{own.id}", {"modo": "semanal", "pagamento_depende_nf": True, "versao_esperada": 0}, "PUT")
        assert status == 200 and json.loads(raw)["versao"] == 1
        query = f"?competencia=2026-08&modo=semanal&data_corte=2026-08-30&clinica_id={own.id}"
        preview = get_json("/rotinas/previa" + query)
        items = {item["os_id"]: item for item in preview["items"]}
        assert set(items).issubset(set(fixtures["os"]) - {os_outro})
        assert items[os_agenda]["elegivel"] and items[os_laudo]["elegivel"]
        assert items[os_agenda]["fonte_realizacao"] == "agenda" and items[os_laudo]["fonte_realizacao"] == "laudo"
        assert not items[os_sem_prova]["realizacao_confirmada"] and not items[os_sem_prova]["elegivel"]
        assert preview["rotina"]["automatico"] is False
        assert preview["rotina"]["corte_em"] == "2026-08-30T17:00:00-03:00"
        assert items[os_agenda]["pagamento_depende_nf"] is True
        checks["backlog_corte_fortaleza_e_escopo_clinica"] = True
        checks["prova_direta_sem_inferencia_paciente_data"] = True

        status, raw, _ = request(f"/rotinas/clinicas/{own.id}", {"modo": "por_servico", "pagamento_depende_nf": True, "versao_esperada": 1}, "PUT")
        assert status == 200 and json.loads(raw)["versao"] == 2
        stale = request(f"/rotinas/clinicas/{own.id}", {"modo": "semanal", "pagamento_depende_nf": False, "versao_esperada": 1}, "PUT")
        assert stale[0] == 409
        checks["preferencia_cas_sem_sobrescrita_stale"] = True

        key = str(uuid4())
        package_keys.append(key)
        payload = {"competencia": "2026-08", "modo": "por_servico", "clinica_id": own.id,
                   "os_ids": [os_agenda], "chave_idempotencia": key, "confirmar_datas_prestacao": True}
        for name, changes in (("batch", {"os_ids": [os_agenda, os_laudo]}),
                              ("sem_prova", {"os_ids": [os_sem_prova]}),
                              ("outra_clinica", {"os_ids": [os_outro]}),
                              ("corte_fora_semanal", {"data_corte": "2026-08-30"})):
            bad_key = str(uuid4())
            package_keys.append(bad_key)
            assert request("/rotinas/preparar", {**payload, **changes, "chave_idempotencia": bad_key})[0] in (409, 422), name
        checks["batch_semprova_escopo_invalido_recusados"] = True
        status, content, headers = request("/rotinas/preparar", payload)
        assert status == 200, "Preparação por serviço indisponível"
        package_id = int(next(value for key, value in headers.items() if key.lower() == "x-fechamento-id"))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read("manifesto.json"))
            assert manifest["os_ids"] == [os_agenda] and manifest["totais"]["valor_final"] == "100.10"
            texts = [archive.read("manifesto.json").decode(), archive.read("mensagem_contador.txt").decode()]
            texts.extend(page.extract_text() for page in PdfReader(io.BytesIO(archive.read("conferencia_contador.pdf"))).pages)
            with zipfile.ZipFile(io.BytesIO(archive.read("servicos_contador.xlsx"))) as workbook:
                texts.extend(workbook.read(name).decode(errors="replace") for name in workbook.namelist() if name.endswith(".xml"))
            text = "\n".join(texts)
            for forbidden in ("QA-PACIENTE-PRIVADO-", "QA-TUTOR-PRIVADO-", "QA-OUTRO-TOMADOR-PRIVADO-"):
                assert forbidden not in text
        checks["pacote_single_os_sem_outros_dados"] = True

        initial = get_json(f"/fechamentos/{package_id}/andamentos")["items"]
        assert len(initial) == 1 and initial[0]["etapa"] == "preparado" and initial[0]["versao"] == 0 and initial[0]["eventos"] == []
        for version, destination in enumerate(("enviado_contador", "nota_recebida", "nota_encaminhada")):
            event_key = str(uuid4())
            event = {"destino": destination, "versao_esperada": version, "chave_idempotencia": event_key,
                     "confirmar_acao_manual": True}
            if destination == "nota_recebida":
                event["referencia_nota"] = "QA-REF-SINTETICA-" + nonce
            status, raw, _ = request(f"/os/{os_agenda}/andamento", event)
            assert status == 200 and json.loads(raw)["versao"] == version + 1
            assert request(f"/os/{os_agenda}/andamento", event)[0] == 200
        state = get_json(f"/fechamentos/{package_id}/andamentos")["items"][0]
        assert state["etapa"] == "nota_encaminhada" and state["versao"] == 3 and len(state["eventos"]) == 3
        assert [event["versao"] for event in state["eventos"]] == [1, 2, 3]
        assert request(f"/os/{os_agenda}/andamento", {"destino": "enviado_contador", "versao_esperada": 0,
                       "chave_idempotencia": str(uuid4()), "confirmar_acao_manual": True})[0] == 409
        checks["andamento_manual_append_only_idempotente_cas"] = True
        retry_status, retry, _ = request("/rotinas/preparar", payload)
        download_status, download, _ = request(f"/fechamentos/{package_id}/download")
        assert retry_status == download_status == 200 and retry == download == content
        checks["pacote_imutavel_apos_andamento"] = True
        db.expire_all()
        persisted = db.get(FiscalFechamento, package_id)
        assert persisted.checksum == hashlib.sha256(content).hexdigest()
        assert "QA-OUTRO-TOMADOR-PRIVADO-" not in persisted.snapshot_json
        assert db.query(NotaFiscal).filter(NotaFiscal.os_id.in_(fixtures["os"])).count() == 0
        assert db.query(OrdemServico).filter(OrdemServico.id.in_(fixtures["os"]), OrdemServico.status != "Pendente").count() == 0
        checks["sem_nota_fiscal_sem_alterar_recebimento"] = True
    finally:
        db.rollback()
        db.close()
        # Outra conexão espera os handlers de preparação/andamento finalizarem.
        with SessionLocal() as clean:
            if fixtures["os"]:
                clean.query(OrdemServico.id).filter(OrdemServico.id.in_(fixtures["os"])).order_by(OrdemServico.id).with_for_update().all()
                clean.query(FiscalFechamentoOS.os_id).filter(FiscalFechamentoOS.os_id.in_(fixtures["os"])).order_by(FiscalFechamentoOS.os_id).with_for_update().all()
                clean.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.os_id.in_(fixtures["os"])).delete(synchronize_session=False)
            packages = [row.id for row in clean.query(FiscalFechamento.id).filter(FiscalFechamento.chave_idempotencia.in_(package_keys))] if package_keys else []
            if packages:
                clean.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.fechamento_id.in_(packages)).delete(synchronize_session=False)
                clean.query(FiscalFechamento).filter(FiscalFechamento.id.in_(packages)).delete(synchronize_session=False)
            clean.query(FiscalRotinaPreferencia).filter(FiscalRotinaPreferencia.clinica_id.in_(fixtures["clinica"])).delete(synchronize_session=False)
            for key, model in (("os", OrdemServico), ("laudo", Laudo), ("agenda", Agendamento),
                               ("paciente", Paciente), ("tutor", Tutor), ("servico", Servico), ("clinica", Clinica)):
                if fixtures[key]:
                    clean.query(model).filter(model.id.in_(fixtures[key])).delete(synchronize_session=False)
            clean.commit()
        with SessionLocal() as verify:
            remaining = []
            for key, model in (("os", OrdemServico), ("laudo", Laudo), ("agenda", Agendamento),
                               ("paciente", Paciente), ("tutor", Tutor), ("servico", Servico), ("clinica", Clinica)):
                remaining.append(verify.query(model).filter(model.id.in_(fixtures[key])).count())
            remaining += [verify.query(FiscalRotinaPreferencia).filter(FiscalRotinaPreferencia.clinica_id.in_(fixtures["clinica"])).count(),
                          verify.query(FiscalAndamentoEvento).filter(FiscalAndamentoEvento.os_id.in_(fixtures["os"])).count(),
                          verify.query(FiscalFechamentoOS).filter(FiscalFechamentoOS.os_id.in_(fixtures["os"])).count()]
            if package_keys:
                remaining.append(verify.query(FiscalFechamento).filter(FiscalFechamento.chave_idempotencia.in_(package_keys)).count())
            if any(remaining):
                raise RuntimeError("Limpeza das fixtures da rotina fiscal não foi confirmada.")
    print(json.dumps({"fiscal_rotina_stage_canary": "passed", "checks": checks, "fixtures_cleaned": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
