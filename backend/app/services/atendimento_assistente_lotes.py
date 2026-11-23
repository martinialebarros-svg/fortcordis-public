"""Durable draft pipeline. Every provider call runs outside a DB transaction."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
import threading
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import _authorize_request_by_matrix
from app.models.user import User
from app.db.database import SessionLocal
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote, AtendimentoAssistenteLoteArquivo as Arquivo
from app.schemas.atendimento_assistente_lote import LoteEntrada
from app.schemas.atendimento_assistente_lote_limites import MAX_AUDIO_BYTES, MAX_AUDIO_PART_BYTES, MAX_EXAMES
from app.services.atendimento_assistente import AssistenteError, require_enabled, validar_audio, validar_arquivo
from app.services.atendimento_assistente_identidade import ERROS_IDENTIDADE_LEGADOS, normalizar_vinculo_anexos
from app.services.atendimento_assistente_identidade import (
    DECISAO_NOME_IDADE, DECISAO_RACA_PENDENTE, impedimento_revisao_identidade,
    impedimento_revisao_raca, revisao_identidade_aplicavel, revisao_raca_aplicavel,
)

logger = logging.getLogger(__name__)
LEASE_SECONDS = 300
RETENTION_HOURS = 24
_worker_thread = None
_stop = threading.Event()
_worker_lock = threading.Lock()
MAX_REVIEW_REQUESTS = 100


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _files(db, job_id):
    return db.query(Arquivo).filter(Arquivo.lote_id == job_id).order_by(Arquivo.ordem).all()


def _contexto(db, atendimento_id):
    # Keep the existing authoritative clinical context contract in one place.
    from app.api.v1.endpoints.atendimento_assistente import _contexto as context
    return context(db, atendimento_id)


def _authorize_actor(db, job):
    user = db.get(User, job.usuario_id)
    if not user or user.ativo != 1:
        raise HTTPException(403, "A conta solicitante precisa estar ativa para processar o conjunto.")
    path = f"/api/v1/atendimentos/{job.atendimento_id}/assistente/lotes"
    # This local request only maps the worker action to the existing permission
    # matrix. Starlette still needs a complete HTTP scope to construct its URL.
    request = Request({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode("ascii"), "root_path": "",
        "query_string": b"", "headers": [], "client": None, "server": None,
    })
    _authorize_request_by_matrix(request, db, user)


def _validate_patient(db, job):
    context = _contexto(db, job.atendimento_id)
    patient = context["paciente"]
    if patient["id"] != job.paciente_id:
        raise HTTPException(409, "O paciente mudou. Prepare um novo conjunto para revisar o contexto correto.")
    return context


def _stored_context(job):
    context = json.loads(job.context_json)
    mode = context.pop("_modo_assistente", "analise")
    return context, mode


def _job_context(context, mode):
    return _json({**context, "_modo_assistente": mode} if mode == "transcricao" else context)


def _clinical_snapshot(context):
    # The registered patient ID binds uploads. Demographics may be corrected
    # independently while the saved clinical narrative remains versioned.
    return {**context, "paciente": {"id": context["paciente"]["id"]}}


def _validate_snapshot(db, job):
    context = _validate_patient(db, job)
    saved, mode = _stored_context(job)
    if mode == "analise" and _clinical_snapshot(context) != _clinical_snapshot(saved):
        raise HTTPException(409, "O atendimento salvo mudou durante a análise. Retome a análise com o contexto atualizado e os arquivos já processados.")


def get_job(db, atendimento_id, usuario_id, job_id, *, lock=False, validate_patient=True, allow_expired=False, allow_deleting=False):
    query = db.query(Lote).filter(Lote.id == job_id, Lote.usuario_id == usuario_id, Lote.atendimento_id == atendimento_id)
    job = (query.with_for_update() if lock else query).first()
    if not job:
        raise HTTPException(404, "Conjunto não encontrado.")
    if job.status == "deleting" and not allow_deleting:
        raise HTTPException(410, "Este conjunto está aguardando exclusão dos arquivos. A limpeza será tentada novamente.")
    if not allow_expired and job.expires_at <= datetime.utcnow():
        raise HTTPException(410, "O conjunto expirou após 24 horas. Carregue as fontes novamente.")
    if validate_patient:
        _validate_patient(db, job)
    return job


def _digest(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _review_state(job):
    if not job.revisoes_identidade_json:
        return {"version": 1, "revisoes": {}, "solicitacoes": []}
    try:
        if len(job.revisoes_identidade_json) > 500_000:
            raise ValueError()
        state = json.loads(job.revisoes_identidade_json)
        if (not isinstance(state, dict)
                or set(state) - {"contexto_revalidado"} != {"version", "revisoes", "solicitacoes"}
                or type(state.get("contexto_revalidado", False)) is not bool
                or state["version"] != 1 or not isinstance(state["revisoes"], dict)
                or len(state["revisoes"]) > MAX_EXAMES or not isinstance(state["solicitacoes"], list)
                or len(state["solicitacoes"]) > MAX_REVIEW_REQUESTS
                or not all(isinstance(item, dict) for item in state["solicitacoes"])):
            raise ValueError()
        return state
    except (TypeError, ValueError):
        raise HTTPException(409, "O registro da revisão precisa ser conferido antes de continuar.") from None


def _source_identity(item):
    if item.tipo != "exame" or item.status != "completed" or not item.resultado_json:
        return None
    try:
        reading = json.loads(item.resultado_json)
        analysis = reading["analise"]
        normalized_name = reading["arquivo"]["nome"]
        sources = analysis["fontes"]
        if (not isinstance(normalized_name, str) or not normalized_name
                or not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict)
                or sources[0].get("arquivo") != normalized_name
                or sources[0].get("identidade") not in {"compativel", "divergente", "nao_confirmada"}):
            return None
        return sources[0]
    except (KeyError, TypeError, ValueError):
        return None


def _review_binding(job, item):
    return {"contexto_sha256": _digest(job.context_json), "arquivo_sha256": item.sha256,
            "resultado_sha256": _digest(item.resultado_json)}


def _review_matches(job, item, review, context):
    source = _source_identity(item)
    return bool(source and isinstance(review, dict)
                and type(review.get("usuario_id")) is int and review["usuario_id"] == job.usuario_id
                and all(review.get(key) == value for key, value in _review_binding(job, item).items())
                and (revisao_raca_aplicavel(source, context, review) or revisao_identidade_aplicavel(source, context, review)))


def _authorize_review_actor(db, job, actor):
    if getattr(actor, "id", None) != job.usuario_id:
        raise HTTPException(404, "Conjunto não encontrado.")
    user = db.get(User, job.usuario_id)
    if not user or user.ativo != 1 or not (user.tem_papel("admin") or user.tem_papel("medico")):
        raise HTTPException(403, "A revisão de identificação exige um médico-veterinário autorizado.")
    # Keep the application permission matrix authoritative in addition to role.
    _authorize_actor(db, job)
    return user


def _review_actor_allowed(db, job, actor):
    # Internal serializers and legacy test fixtures do not authenticate a reviewer.
    if actor is None or not callable(getattr(actor, "tem_papel", None)):
        return False
    try:
        _authorize_review_actor(db, job, actor)
        return True
    except HTTPException:
        return False


def _review_token(job, files, *, current_context=None):
    return _digest(_json({
        "lote_id": job.id, "status": job.status, "contexto": _digest(job.context_json),
        **({"contexto_atual": _digest(_json(current_context))} if current_context is not None else {}),
        "resultado": _digest(job.resultado_json), "revisoes": _digest(job.revisoes_identidade_json),
        "fontes": [{"id": item.id, "nome": item.nome, "tipo": item.tipo, "status": item.status,
                    "sha256": item.sha256, "resultado": _digest(item.resultado_json)} for item in files],
    }))


def _source_bytes_intact(item):
    try:
        return bool(item.sha256 and item.caminho and Path(item.caminho).is_file()
                    and hashlib.sha256(Path(item.caminho).read_bytes()).hexdigest() == item.sha256)
    except OSError:
        return False


def _source_version(files):
    return _digest(_json([
        {"id": item.id, "status": item.status, "sha256": item.sha256,
         "resultado_sha256": _digest(item.resultado_json)} for item in files
    ]))


def _reviews_for_synthesis(db, job, files=None):
    """Load only server-bound decisions; never trust a review from the AI output."""
    state = _review_state(job)
    if not state["revisoes"]:
        return {}
    from types import SimpleNamespace
    _authorize_review_actor(db, job, SimpleNamespace(id=job.usuario_id))
    context = json.loads(job.context_json)
    by_id = {item.id: item for item in (files if files is not None else _files(db, job.id))}
    result = {}
    for file_id, review in state["revisoes"].items():
        item = by_id.get(file_id)
        if (not item or not _review_matches(job, item, review, context)
                or not _source_bytes_intact(item)):
            raise HTTPException(409, "A fonte ou o contexto da revisão mudou. Confira novamente a identificação.")
        result[_source_identity(item)["arquivo"]] = {
            key: review[key] for key in ("decisao", "usuario_id", "registrado_em")}
    return result


def _identity_requires_review(source, context):
    return source["identidade"] != "compativel" or impedimento_revisao_raca(source, context) is not None


def _has_unreviewed_identity(files, reviews, context, *, revalidated=False):
    for item in files:
        if item.tipo != "exame":
            continue
        source = _source_identity(item)
        if not source:
            return True
        if source["arquivo"] in reviews:
            continue
        if revalidated or _identity_requires_review(source, context):
            return True
    return False


def _serialize_identity_reviews(db, job, files, actor):
    context, mode = _stored_context(job)
    allowed = _review_actor_allowed(db, job, actor)
    valid_snapshot = job.expires_at > datetime.utcnow()
    current = None
    invalid_review = None
    try:
        state = _review_state(job)
    except HTTPException as exc:
        state, valid_snapshot, invalid_review = {"revisoes": {}}, False, exc.detail
    if (allowed or state["revisoes"]) and valid_snapshot:
        try:
            live = _validate_patient(db, job)
            if mode == "analise" and _clinical_snapshot(live) != _clinical_snapshot(context):
                current = live
                raise HTTPException(409, "O contexto da revisão mudou. Confira novamente a identificação.")
        except HTTPException as exc:
            valid_snapshot, invalid_review = False, exc.detail
    if state["revisoes"]:
        try:
            if not valid_snapshot:
                raise HTTPException(409, "O contexto da revisão mudou. Confira novamente a identificação.")
            _reviews_for_synthesis(db, job, files)
        except HTTPException as exc:
            invalid_review = exc.detail
    race_sources, identity_sources = [], []
    identity_context = current if current is not None else context
    revalidated = state.get("contexto_revalidado", False)
    for item in files:
        if item.tipo != "exame":
            continue
        source = _source_identity(item)
        impediment = (impedimento_revisao_raca(source, context) if source else
                      "Aguarde a leitura completa deste documento para conferir sua identificação.")
        review = state["revisoes"].get(item.id)
        confirmed = bool(review and not invalid_review and valid_snapshot
                         and _review_matches(job, item, review, context))
        if review and not confirmed:
            impediment = "A fonte ou o contexto da revisão mudou. Confira novamente a identificação."
        common = {"arquivo_id": item.id, "nome": item.nome,
                  "paciente_nome": source.get("paciente_nome") if source else None,
                  "especie": source.get("especie") if source else None,
                  "identidade": source["identidade"] if source else "nao_confirmada",
                  "motivo": source.get("motivo", "") if source else ""}
        race_confirmed = confirmed and review["decisao"] == DECISAO_RACA_PENDENTE
        identity_confirmed = confirmed and review["decisao"] == DECISAO_NOME_IDADE
        race_sources.append({**common, "elegivel": impediment is None and not identity_confirmed,
                             "impedimento": impediment, "confirmada": race_confirmed,
                             "registrado_em": review["registrado_em"] if race_confirmed else None})
        if source:
            identity_impediment = impedimento_revisao_identidade(source, identity_context)
            identity_pending = current is not None or revalidated or _identity_requires_review(source, identity_context)
            if identity_confirmed or (identity_pending and not race_confirmed):
                identity_sources.append({**common, "data_exame": source.get("data_exame"),
                    "elegivel": identity_impediment is None, "impedimento": identity_impediment,
                    "confirmada": identity_confirmed,
                    "registrado_em": review["registrado_em"] if identity_confirmed else None})
    ready = bool(allowed and job.status in {"completed", "failed"} and files
                 and all(item.status == "completed" for item in files))
    token = _review_token(job, files)
    race = {"token": token, "pode_revisar": ready and valid_snapshot,
            "raca_cadastrada": context.get("paciente", {}).get("raca"), "fontes": race_sources}
    patient = identity_context.get("paciente", {})
    identity = {"token": _review_token(job, files, current_context=current) if current is not None else token,
                "pode_revisar": ready and (current is not None or (valid_snapshot and not invalid_review)),
                "contexto_mudou": current is not None, "paciente_nome": patient.get("nome"),
                "paciente_idade": patient.get("idade"), "fontes": identity_sources}
    return race, identity, invalid_review


def review_race(db, job, payload, actor, *, revoke=False):
    return review_identity(db, job, payload, actor, decision=DECISAO_RACA_PENDENTE, revoke=revoke)


def review_identity(db, job, payload, actor, *, decision=DECISAO_NOME_IDADE, revoke=False):
    """Record a decision and queue synthesis only after resolving every source."""
    require_enabled()
    _authorize_review_actor(db, job, actor)
    if job.expires_at <= datetime.utcnow():
        raise HTTPException(410, "O conjunto expirou após 24 horas. Carregue as fontes novamente.")
    current = _validate_patient(db, job)
    context, mode = _stored_context(job)
    updating = mode == "analise" and current != context
    confirm_identity = decision == DECISAO_NOME_IDADE and not revoke
    if not confirm_identity:
        _validate_snapshot(db, job)
    state = _review_state(job)
    selection = sorted(str(value) for value in payload.arquivo_ids)
    action = "revogar" if revoke else "confirmar"
    fingerprint = _digest(_json({"acao": action, **payload.model_dump(mode="json"), "arquivo_ids": selection}))
    request_id = str(payload.request_id)
    previous = next((entry for entry in state["solicitacoes"] if entry.get("request_id") == request_id), None)
    if previous:
        if previous.get("payload_sha256") != fingerprint:
            raise HTTPException(409, "Esta solicitação de revisão já foi usada com outra decisão.")
        return job, None
    if len(state["solicitacoes"]) >= MAX_REVIEW_REQUESTS:
        raise HTTPException(409, "O limite de revisões deste conjunto foi atingido. Prepare um novo conjunto.")
    if confirm_identity and updating != payload.atualizar_contexto:
        raise HTTPException(409, "O contexto da revisão mudou. Confira novamente a identificação.")
    files = _files(db, job.id)
    if job.status not in {"completed", "failed"} or not files or any(item.status != "completed" for item in files):
        raise HTTPException(409, "Aguarde a conclusão de todos os arquivos antes de revisar a identificação.")
    if payload.revisao_token != _review_token(job, files, current_context=current if updating else None):
        raise HTTPException(409, "A revisão mudou em outra tela. Consulte o estado atual e confira novamente.")
    by_id = {item.id: item for item in files}
    previous_context = _digest(job.context_json)
    if updating:
        # Current patient ID, name and species were checked against the saved lot.
        # Never carry confirmations or automatic matches over to the new context.
        context = current
        job.context_json = _job_context(current, mode)
        state["revisoes"].clear()
        state["contexto_revalidado"] = True
    now = datetime.utcnow().isoformat() + "Z"
    selected, changed = {}, False
    review_impediment = impedimento_revisao_identidade if decision == DECISAO_NOME_IDADE else impedimento_revisao_raca
    for file_id in selection:
        item = by_id.get(file_id)
        source = _source_identity(item) if item else None
        if not item or not source or not _source_bytes_intact(item):
            raise HTTPException(409, "O documento selecionado não está disponível para esta revisão.")
        impediment = review_impediment(source, context)
        if impediment is not None:
            raise HTTPException(409, impediment)
        binding = _review_binding(job, item)
        selected[file_id] = binding
        previous_review = state["revisoes"].get(file_id)
        if previous_review and previous_review.get("decisao") != decision:
            raise HTTPException(409, "Retire a confirmação anterior deste documento antes de registrar outra.")
        if revoke:
            if not previous_review:
                raise HTTPException(409, "Este documento não tem uma confirmação ativa para desfazer.")
            del state["revisoes"][file_id]
            changed = True
        elif not _review_matches(job, item, previous_review, context):
            if confirm_identity and not state.get("contexto_revalidado") and not _identity_requires_review(source, context):
                raise HTTPException(409, "A identificação deste documento já é compatível.")
            state["revisoes"][file_id] = {"decisao": decision,
                "usuario_id": actor.id, "registrado_em": now, **binding}
            changed = True
    event = {"request_id": request_id, "payload_sha256": fingerprint, "acao": action,
             "usuario_id": actor.id, "registrado_em": now, "fontes": selected}
    if decision == DECISAO_NOME_IDADE:
        event["decisao"] = decision
    if updating:
        event["contexto_anterior_sha256"] = previous_context
    state["solicitacoes"].append(event)
    job.revisoes_identidade_json = _json(state)
    if changed:
        job.resultado_json, job.lease_token, job.lease_until = None, None, None
        reviews = _reviews_for_synthesis(db, job, files)
        if revoke or _has_unreviewed_identity(files, reviews, context, revalidated=state.get("contexto_revalidado", False)):
            job.status, job.erro = "failed", "Há identificações pendentes. Confira os documentos antes de continuar a análise."
        else:
            job.status, job.erro = "queued", None
    db.commit()
    return job, {"request_id": request_id, "acao": action, "arquivo_ids": selection}


def _sintese_pendente(job, files, *, context_changed=False):
    if _stored_context(job)[1] != "analise" or any(item.status != "completed" for item in files):
        return False
    if job.status == "failed":
        return True
    return bool(job.status == "completed" and (context_changed or not job.resultado_json
                or json.loads(job.resultado_json).get("bloqueado_integracao")))


def serialize(db, job, actor=None):
    files = _files(db, job.id)
    # Legacy decisions remain available as audit metadata, but are no longer an
    # authorization requirement for documents attached to this patient's visit.
    race_review, identity_review, _ = _serialize_identity_reviews(db, job, files, actor)
    texts = [job.transcricao] if job.status != "deleting" else []
    transcript_reviews = []
    for item in files:
        if job.status != "deleting" and item.tipo == "audio" and item.status == "completed":
            result = json.loads(item.resultado_json)
            texts.append(result["texto"])
            if isinstance(result.get("revisao_transcricao"), dict):
                transcript_reviews.append({"arquivo_id": item.id, "nome": item.nome,
                                           "revisao_transcricao": result["revisao_transcricao"]})
    result = normalizar_vinculo_anexos(json.loads(job.resultado_json)) if job.resultado_json and job.status != "deleting" else None
    saved, mode = _stored_context(job)
    current = _validate_patient(db, job)
    error = None if job.erro in ERROS_IDENTIDADE_LEGADOS else job.erro
    context_changed = mode == "analise" and _clinical_snapshot(current) != _clinical_snapshot(saved)
    if result and (
        (result.get("fontes_versao") and result["fontes_versao"] != _source_version(files))
        or any(not _source_bytes_intact(item) for item in files)
    ):
        result, error = None, "As fontes do conjunto mudaram. Confira os arquivos antes de continuar."
    if result and context_changed:
        result.update(revisao_desatualizada=True, bloqueado_integracao=True)
    return {
        "id": job.id, "atendimento_id": job.atendimento_id, "paciente_id": job.paciente_id,
        "status": "failed" if job.status == "deleting" else job.status, "erro": error,
        "expires_at": job.expires_at.isoformat() + "Z",
        "arquivos": [{"id": f.id, "nome": f.nome, "tipo": f.tipo, "tamanho": f.tamanho, "status": f.status, "erro": f.erro,
                       **(_upload_progress(job.id, f) if f.tipo == "audio" and f.status == "pending" else {})} for f in files],
        "resultado": result,
        "transcricao": "\n\n".join(t.strip() for t in texts if t.strip()),
        "modo": mode,
        "sintese_pendente": _sintese_pendente(job, files, context_changed=context_changed),
        "revisoes_transcricao": transcript_reviews,
        "revisao_raca": race_review,
        "revisao_identidade": identity_review,
    }


def create_job(db, context, usuario_id, manifest: LoteEntrada):
    payload = manifest.model_dump(mode="json", exclude={"consentimento"})
    if manifest.modo == "analise":
        payload.pop("modo")  # Preserve idempotency for existing manifests.
    fingerprint = hashlib.sha256(_json(payload).encode()).hexdigest()
    request_id = str(manifest.request_id)
    previous = db.query(Lote).filter(Lote.usuario_id == usuario_id, Lote.request_id == request_id).first()
    if previous:
        if previous.manifest_hash != fingerprint or previous.atendimento_id != context["atendimento_id"]:
            raise HTTPException(409, "Este pedido já foi usado com outras fontes.")
        return get_job(db, context["atendimento_id"], usuario_id, previous.id)
    now = datetime.utcnow()
    job = Lote(id=str(uuid4()), request_id=request_id, usuario_id=usuario_id,
               atendimento_id=context["atendimento_id"], paciente_id=context["paciente"]["id"],
               manifest_hash=fingerprint, context_json=_job_context(context, manifest.modo), transcricao=manifest.transcricao.strip(),
               status="uploading", created_at=now, expires_at=now + timedelta(hours=RETENTION_HOURS))
    db.add(job)
    for order, item in enumerate(manifest.arquivos):
        db.add(Arquivo(lote_id=job.id, id=str(item.id), ordem=order, nome=Path(item.nome.replace("\\", "/")).name,
                       tipo=item.tipo, tamanho=item.tamanho, mime=item.mime, status="pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.query(Lote).filter(Lote.usuario_id == usuario_id, Lote.request_id == request_id).first()
        if not previous:
            raise
        if previous.manifest_hash != fingerprint or previous.atendimento_id != context["atendimento_id"]:
            raise HTTPException(409, "Este pedido já foi usado com outras fontes.")
        return get_job(db, context["atendimento_id"], usuario_id, previous.id)
    return job


def storage_root(*, create=True):
    # Deliberately outside UPLOAD_DIR, which may be publicly served by Nginx.
    path = Path(__file__).resolve().parents[2] / "generated" / "atendimento_assistente_lotes"
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    return path


def _audio_partial(job_id, file_id):
    return next(iter((storage_root(create=False) / job_id).glob(f"parte-{file_id}-*")), None)


def _upload_progress(job_id, item):
    part = _audio_partial(job_id, item.id)
    if part is None:
        return {}
    try:
        return {"bytes_recebidos": part.stat().st_size, "upload_sha256": part.name.split("-")[-1]}
    except FileNotFoundError:
        return {}


def upload_audio_part(db, job, file_id, content, offset, expected_hash):
    item = db.get(Arquivo, (job.id, file_id))
    if not item or item.tipo != "audio":
        raise HTTPException(404, "Áudio não encontrado neste conjunto.")
    if item.sha256:
        if item.sha256 != expected_hash:
            raise HTTPException(409, "O conteúdo difere do arquivo recebido.")
        return job
    if job.status != "uploading":
        raise HTTPException(409, "O conjunto já foi iniciado.")
    if not content or len(content) > MAX_AUDIO_PART_BYTES or offset + len(content) > item.tamanho:
        raise HTTPException(413, "A parte excede o tamanho do áudio selecionado.")

    directory = storage_root() / job.id
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / f"parte-{file_id}-{expected_hash}"
    existing = _audio_partial(job.id, file_id)
    if existing and existing != target:
        raise HTTPException(409, "Selecione o mesmo áudio original para continuar o envio.")
    received = target.stat().st_size if target.exists() else 0
    if offset != received:
        raise HTTPException(409, "A posição do envio mudou. Consulte o progresso e retome.")
    if received + len(content) == item.tamanho:
        # Leave only a confirmed prefix on disk until the usual upload commits.
        original = (target.read_bytes() if received else b"") + content
        if hashlib.sha256(original).hexdigest() != expected_hash:
            target.unlink(missing_ok=True)
            raise HTTPException(422, "O áudio recebido não corresponde ao original. Retome o envio.")
        saved = upload_file(db, job, file_id, original)
        target.unlink(missing_ok=True)
        return saved

    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab", buffering=0) as stream:
        try:
            if stream.write(content) != len(content):
                raise OSError("short_write")
            os.fsync(stream.fileno())
        except OSError:
            stream.truncate(received)
            raise
    db.commit()
    return job


def upload_file(db, job, file_id, content):
    item = db.query(Arquivo).filter(Arquivo.lote_id == job.id, Arquivo.id == file_id).with_for_update().first()
    if not item:
        raise HTTPException(404, "Arquivo não encontrado neste conjunto.")
    digest = hashlib.sha256(content).hexdigest()
    if item.sha256:
        if item.sha256 != digest:
            raise HTTPException(409, "O conteúdo difere do arquivo recebido. Prepare um novo conjunto.")
        return job
    if job.status != "uploading":
        raise HTTPException(409, "O conjunto já foi iniciado.")
    if len(content) != item.tamanho:
        raise HTTPException(422, "O tamanho recebido difere do arquivo selecionado. Tente enviar este arquivo novamente.")
    try:
        if item.tipo == "audio":
            validar_audio(item.nome, item.mime, content, max_bytes=MAX_AUDIO_BYTES)
        else:
            validar_arquivo(item.nome, item.mime, content, item.ordem + 1)
    except AssistenteError as exc:
        item.erro = str(exc)
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc
    directory = storage_root() / job.id
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / f"{item.id}-{digest}"
    descriptor, temporary = tempfile.mkstemp(prefix="upload-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        item.caminho, item.sha256, item.status, item.erro = str(target), digest, "uploaded", None
        db.commit()
    finally:
        Path(temporary).unlink(missing_ok=True)
    return job


def start_job(db, job, *, retry=False):
    require_enabled()
    if job.status == "deleting":
        raise HTTPException(409, "A exclusão deste conjunto está pendente. Tente apagar novamente.")
    files = _files(db, job.id)
    context = _validate_patient(db, job)
    saved, mode = _stored_context(job)
    context_changed = mode == "analise" and _clinical_snapshot(context) != _clinical_snapshot(saved)
    refresh_synthesis = retry and _sintese_pendente(job, files, context_changed=context_changed)
    if job.status in ("queued", "processing") or (job.status == "completed" and not refresh_synthesis):
        return job
    if not retry and job.status != "uploading":
        raise HTTPException(409, "Use Retomar para continuar o conjunto que falhou.")
    if retry and job.status != "failed" and not refresh_synthesis:
        raise HTTPException(409, "Envie os arquivos pendentes antes de iniciar.")
    if any(not item.sha256 for item in files):
        raise HTTPException(409, "Envie todos os arquivos antes de iniciar a análise.")
    # A new synthesis can use the current saved visit with the same patient's
    # immutable readings and transcript. In-flight changes remain snapshot-checked.
    job.context_json = _job_context(context, mode)
    if refresh_synthesis:
        job.resultado_json = None
    for item in files:
        if item.status == "failed":
            item.status, item.erro = "uploaded", None
    job.status, job.erro, job.lease_token, job.lease_until = "queued", None, None, None
    db.commit()
    return job


def _remove_directory(directory):
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass


def delete_job(db, job):
    # The caller holds the job row lock. Keep a tombstone if filesystem removal
    # fails so cleanup retries it. Delete the DB references only after disk cleanup.
    directory = storage_root() / job.id
    job.status, job.lease_token, job.lease_until = "deleting", None, None
    job.erro = "A exclusão dos arquivos está pendente. Tente apagar novamente."
    db.flush()
    try:
        _remove_directory(directory)
    except OSError as exc:
        db.commit()
        raise HTTPException(503, "Não foi possível apagar todos os arquivos. A limpeza será tentada novamente.") from exc
    db.query(Arquivo).filter(Arquivo.lote_id == job.id).delete(synchronize_session=False)
    db.delete(job)
    db.commit()


def _claim():
    now = datetime.utcnow()
    with SessionLocal() as db:
        candidate = db.query(Lote.id).filter(
            Lote.expires_at > now,
            or_(Lote.status == "queued", (Lote.status == "processing") & (Lote.lease_until < now)),
        ).order_by(Lote.created_at).first()
        if not candidate:
            return None
        token = str(uuid4())
        changed = db.query(Lote).filter(Lote.id == candidate[0], Lote.expires_at > now,
            or_(Lote.status == "queued", (Lote.status == "processing") & (Lote.lease_until < now)),
        ).update({"status": "processing", "lease_token": token, "lease_until": now + timedelta(seconds=LEASE_SECONDS)}, synchronize_session=False)
        db.commit()
        return (candidate[0], token) if changed else None


def _lease_job(db, job_id, token):
    return db.query(Lote).filter(Lote.id == job_id, Lote.lease_token == token,
        Lote.status == "processing", Lote.expires_at > datetime.utcnow()).populate_existing().with_for_update().first()


def _heartbeat(job_id, token, finished):
    while not finished.wait(30):
        try:
            with SessionLocal() as db:
                db.query(Lote).filter(Lote.id == job_id, Lote.lease_token == token, Lote.status == "processing").update(
                    {"lease_until": datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)}, synchronize_session=False)
                db.commit()
        except Exception:
            logger.warning("Falha ao renovar concessão do lote do Atendimento.")


def _safe_error(exc):
    if isinstance(exc, FileNotFoundError):
        return "A cópia temporária deste arquivo está indisponível. Prepare um novo conjunto com os originais."
    if isinstance(exc, AssistenteError):
        return str(exc)
    if isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        return exc.detail
    return "Não foi possível processar esta etapa. Tente retomar o conjunto."


def process_job(job_id, token):
    from app.services.atendimento_assistente_lote_provider import processar_audio, processar_exame, sintetizar_lote
    finished = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat, args=(job_id, token, finished), daemon=True)
    heartbeat.start()
    try:
        with SessionLocal() as db:
            job = _lease_job(db, job_id, token)
            if not job:
                return
            _authorize_actor(db, job)
            _validate_snapshot(db, job)
            context, mode = _stored_context(job)
            user_id = job.usuario_id
            ids = [item.id for item in _files(db, job_id)]
            db.rollback()
        for file_id in ids:
            require_enabled()
            with SessionLocal() as db:
                job = _lease_job(db, job_id, token)
                if not job:
                    return
                _authorize_actor(db, job)
                _validate_snapshot(db, job)
                item = db.get(Arquivo, (job_id, file_id))
                if item.status == "completed":
                    continue
                item.status, item.erro = "processing", None
                source = {key: getattr(item, key) for key in ("nome", "mime", "caminho", "tipo", "ordem", "sha256")}
                db.commit()
            result, error = None, None
            try:
                content = Path(source["caminho"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != source["sha256"]:
                    raise AssistenteError("A cópia recebida precisa ser conferida. Prepare um novo conjunto.")
                if source["tipo"] == "audio":
                    result = processar_audio(nome=source["nome"], mime=source["mime"], content=content, paciente_nome=context["paciente"]["nome"])
                else:
                    result = processar_exame(nome=source["nome"], mime=source["mime"], content=content, indice=source["ordem"] + 1, context=context, user_id=user_id)
            except Exception as exc:
                error = _safe_error(exc)
            with SessionLocal() as db:
                if not _lease_job(db, job_id, token):
                    return
                item = db.get(Arquivo, (job_id, file_id))
                item.status, item.erro = ("failed", error) if error else ("completed", None)
                item.resultado_json = _json(result) if result else None
                db.commit()
        with SessionLocal() as db:
            job = _lease_job(db, job_id, token)
            if not job:
                return
            files = _files(db, job_id)
            if any(item.status != "completed" for item in files):
                job.status, job.erro = "failed", "Há arquivos pendentes. Retome os que falharam para analisar o conjunto completo."
                db.commit()
                return
            if mode == "transcricao":
                _authorize_actor(db, job)
                _validate_snapshot(db, job)
                job.status, job.erro = "completed", None
                db.commit()
                return
            if any(not _source_bytes_intact(item) for item in files):
                raise HTTPException(409, "As fontes do conjunto mudaram. Confira os arquivos antes de continuar.")
            source_version = _source_version(files)
            transcript = serialize(db, job)["transcricao"]
            exames = [json.loads(item.resultado_json) for item in files if item.tipo == "exame"]
            audio_notices = list(dict.fromkeys(notice for item in files if item.tipo == "audio"
                for notice in json.loads(item.resultado_json).get("avisos", [])))
            _authorize_actor(db, job)
            _validate_snapshot(db, job)
            db.rollback()
        if len(transcript) > 80000:
            raise AssistenteError("A transcrição conjunta excede 80.000 caracteres. Prepare um conjunto menor.")
        require_enabled()
        arguments = dict(transcript=transcript, context=context, exames=exames, user_id=user_id)
        result = sintetizar_lote(**arguments)
        result["avisos"] = list(dict.fromkeys([*result.get("avisos", []), *audio_notices]))
        with SessionLocal() as db:
            job = _lease_job(db, job_id, token)
            if job:
                _authorize_actor(db, job)
                _validate_snapshot(db, job)
                current_files = _files(db, job_id)
                if source_version != _source_version(current_files) or any(not _source_bytes_intact(item) for item in current_files):
                    raise HTTPException(409, "As fontes do conjunto mudaram durante a análise. Confira os arquivos.")
                result["fontes_versao"] = source_version
                job.status, job.resultado_json, job.erro = "completed", _json(result), None
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            job = _lease_job(db, job_id, token)
            if job:
                job.status, job.erro = "failed", _safe_error(exc)
                db.commit()
    finally:
        finished.set()
        heartbeat.join(timeout=2)


def cleanup_expired():
    with SessionLocal() as db:
        ids = db.query(Lote.id).filter(or_(Lote.expires_at <= datetime.utcnow(), Lote.status == "deleting")).limit(50).all()
        db.rollback()
        for (job_id,) in ids:
            job = db.query(Lote).filter(Lote.id == job_id).with_for_update(skip_locked=True).first()
            if not job:
                db.rollback()
                continue
            try:
                delete_job(db, job)
            except HTTPException:
                logger.warning("Limpeza de arquivos do Atendimento pendente; será tentada novamente.")
        # Recover directories orphaned by an interrupted old cleanup or an upload
        # transaction that could not persist. Never touch unrelated directories.
        cutoff = time.time() - RETENTION_HOURS * 3600
        for directory in storage_root().iterdir():
            try:
                if str(UUID(directory.name)) != directory.name or not directory.is_dir() or directory.stat().st_mtime > cutoff:
                    continue
            except (ValueError, FileNotFoundError):
                continue
            exists = db.query(Lote.id).filter(Lote.id == directory.name).first()
            db.rollback()
            if not exists:
                try:
                    _remove_directory(directory)
                except OSError:
                    logger.warning("Limpeza de diretório privado do Atendimento pendente.")


def run_once():
    cleanup_expired()
    if not settings.ATENDIMENTO_IA_ENABLED:
        return
    claimed = _claim()
    if claimed:
        process_job(*claimed)


def _worker():
    while not _stop.is_set():
        try:
            run_once()
        except Exception:
            # No payloads, credentials, transcripts or file names in logs.
            logger.warning("Fila de análise do Atendimento indisponível; nova verificação em cinco segundos.")
        _stop.wait(5)


def start_atendimento_assistente_worker():
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _stop.clear()
        _worker_thread = threading.Thread(target=_worker, daemon=True, name="atendimento-assistente-lotes")
        _worker_thread.start()


def shutdown_atendimento_assistente_worker():
    _stop.set()
    if _worker_thread:
        _worker_thread.join(timeout=2)
