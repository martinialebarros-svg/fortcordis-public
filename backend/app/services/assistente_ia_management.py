from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, Request
from sqlalchemy import func, inspect
from sqlalchemy.orm import Session

from app.api.v1.endpoints import laudos
from app.models.agendamento import Agendamento
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAAprendizado,
    AssistenteIAConhecimentoDocumento,
    AssistenteIAFeedback,
    AssistenteIAMemoria,
    AssistenteIAMemoriaVersao,
    AssistenteIAMensagem,
    AssistenteIARegressaoCaso,
    AssistenteIARascunhoClinico,
)
from app.models.financeiro import ContaReceber, Transacao
from app.models.laudo import Laudo
from app.models.user import User
from app.services.auditoria_service import registrar_auditoria

LOCAL_TZ = timezone(timedelta(hours=-3))


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _local_day_bounds(reference: date) -> tuple[datetime, datetime]:
    start = datetime.combine(reference, time.min, tzinfo=LOCAL_TZ)
    return start, start + timedelta(days=1)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _tables_available(db: Session, *names: str) -> bool:
    bind = db.get_bind()
    return bool(bind and set(names).issubset(set(inspect(bind).get_table_names())))


def serialize_memory(row: AssistenteIAMemoria) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.titulo,
        "content": row.conteudo,
        "category": row.categoria,
        "source": row.origem,
        "status": row.status,
        "current_version": int(getattr(row, "versao_atual", 1) or 1),
        "created_by_id": row.criado_por_id,
        "approved_by_id": row.aprovado_por_id,
        "approved_at": row.aprovado_em.isoformat() if row.aprovado_em else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_memories(db: Session, *, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    query = db.query(AssistenteIAMemoria)
    if status:
        query = query.filter(AssistenteIAMemoria.status == status)
    rows = query.order_by(AssistenteIAMemoria.created_at.desc()).limit(max(1, min(200, limit))).all()
    return [serialize_memory(row) for row in rows]


def create_memory(
    db: Session,
    current_user: User,
    *,
    title: str,
    content: str,
    category: str,
    source: str = "admin",
    approve_immediately: bool = False,
) -> dict[str, Any]:
    clean_title = str(title or "").strip()[:180]
    clean_content = str(content or "").strip()[:8000]
    if not clean_title or not clean_content:
        raise HTTPException(status_code=422, detail="Informe titulo e conteudo da memoria.")
    now_utc = datetime.now(timezone.utc)
    row = AssistenteIAMemoria(
        id=str(uuid.uuid4()),
        titulo=clean_title,
        conteudo=clean_content,
        categoria=(str(category or "operacao").strip() or "operacao")[:60],
        origem=(str(source or "admin").strip() or "admin")[:40],
        status="approved" if approve_immediately else "pending",
        criado_por_id=int(current_user.id),
        aprovado_por_id=int(current_user.id) if approve_immediately else None,
        aprovado_em=now_utc if approve_immediately else None,
    )
    db.add(row)
    if approve_immediately and _tables_available(
        db,
        "assistente_ia_memoria_versoes",
        "assistente_ia_regressao_casos",
    ):
        db.flush()
        _record_memory_version(
            db,
            row,
            user_id=int(current_user.id),
            change_type="create",
        )
        _replace_regression_contract(db, row, user_id=int(current_user.id))
    db.commit()
    db.refresh(row)
    return serialize_memory(row)


def decide_memory(
    db: Session,
    current_user: User,
    request: Optional[Request],
    *,
    memory_id: str,
    decision: str,
) -> dict[str, Any]:
    row = db.query(AssistenteIAMemoria).filter(AssistenteIAMemoria.id == memory_id).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Memoria nao encontrada.")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Esta memoria ja foi decidida.")
    now_utc = datetime.now(timezone.utc)
    if decision == "approve":
        row.status = "approved"
        row.aprovado_por_id = int(current_user.id)
        row.aprovado_em = now_utc
        if _tables_available(
            db,
            "assistente_ia_memoria_versoes",
            "assistente_ia_regressao_casos",
        ):
            _record_memory_version(
                db,
                row,
                user_id=int(current_user.id),
                change_type="create",
            )
            _replace_regression_contract(db, row, user_id=int(current_user.id))
    elif decision == "reject":
        row.status = "rejected"
        row.rejeitado_em = now_utc
    else:
        raise HTTPException(status_code=422, detail="Decisao invalida.")
    db.add(row)
    db.commit()
    db.refresh(row)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="memoria",
        entidade_id=row.id,
        acao="ASSISTENTE_IA_MEMORIA_APROVADA" if decision == "approve" else "ASSISTENTE_IA_MEMORIA_REJEITADA",
        descricao="Administrador decidiu uma memoria supervisionada da Mente FortCordis.",
        detalhes={"titulo": row.titulo, "categoria": row.categoria, "decisao": decision},
        request=request,
    )
    return serialize_memory(row)


def _serialize_memory_version(row: AssistenteIAMemoriaVersao) -> dict[str, Any]:
    return {
        "id": row.id,
        "memory_id": row.memoria_id,
        "version": row.versao,
        "title": row.titulo,
        "content": row.conteudo,
        "category": row.categoria,
        "source": row.origem,
        "change_type": row.tipo_alteracao,
        "learning_id": row.aprendizado_id,
        "created_by_id": row.criado_por_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _record_memory_version(
    db: Session,
    memory: AssistenteIAMemoria,
    *,
    user_id: int,
    change_type: str,
    learning_id: Optional[str] = None,
    version: Optional[int] = None,
) -> AssistenteIAMemoriaVersao:
    existing_max = db.query(func.max(AssistenteIAMemoriaVersao.versao)).filter(
        AssistenteIAMemoriaVersao.memoria_id == memory.id
    ).scalar()
    next_version = int(version or ((existing_max or 0) + 1))
    memory.versao_atual = next_version
    version_row = AssistenteIAMemoriaVersao(
        memoria_id=memory.id,
        versao=next_version,
        titulo=memory.titulo,
        conteudo=memory.conteudo,
        categoria=memory.categoria,
        origem=memory.origem,
        tipo_alteracao=change_type,
        aprendizado_id=learning_id,
        criado_por_id=user_id,
    )
    db.add(memory)
    db.add(version_row)
    db.flush()
    return version_row


def _ensure_memory_baseline(db: Session, memory: AssistenteIAMemoria, *, user_id: int) -> None:
    existing = db.query(AssistenteIAMemoriaVersao.id).filter(
        AssistenteIAMemoriaVersao.memoria_id == memory.id
    ).first()
    if existing is None:
        _record_memory_version(
            db,
            memory,
            user_id=user_id,
            change_type="create",
            version=max(1, int(getattr(memory, "versao_atual", 1) or 1)),
        )


def _replace_regression_contract(
    db: Session,
    memory: AssistenteIAMemoria,
    *,
    user_id: int,
    learning_id: Optional[str] = None,
) -> AssistenteIARegressaoCaso:
    db.query(AssistenteIARegressaoCaso).filter(
        AssistenteIARegressaoCaso.memoria_id == memory.id,
        AssistenteIARegressaoCaso.status == "active",
    ).update({"status": "archived"}, synchronize_session=False)
    digest = hashlib.sha256(memory.conteudo.encode("utf-8")).hexdigest()
    row = AssistenteIARegressaoCaso(
        id=str(uuid.uuid4()),
        aprendizado_id=learning_id,
        memoria_id=memory.id,
        tipo="memory_contract",
        prompt=f"Preservar a memoria aprovada: {memory.titulo}",
        expectativa_json=_json_dumps({
            "version": int(memory.versao_atual or 1),
            "content_sha256": digest,
        }),
        status="active",
        criado_por_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


def _serialize_learning(row: AssistenteIAAprendizado) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.usuario_id,
        "feedback_id": row.feedback_id,
        "target_memory_id": row.memoria_alvo_id,
        "title": row.titulo,
        "content": row.conteudo,
        "category": row.categoria,
        "source": row.origem,
        "source_context": _json_loads(row.fonte_json, {}),
        "impact": _json_loads(row.impacto_json, {}),
        "status": row.status,
        "reviewed_by_id": row.revisado_por_id,
        "reviewed_at": row.revisado_em.isoformat() if row.revisado_em else None,
        "memory_id": row.memoria_id,
        "regression_case_id": row.caso_regressao_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _new_learning(
    *,
    user_id: int,
    title: str,
    content: str,
    category: str,
    source: str,
    feedback_id: Optional[int] = None,
    target_memory_id: Optional[str] = None,
    source_context: Optional[dict[str, Any]] = None,
) -> AssistenteIAAprendizado:
    clean_title = str(title or "").strip()[:180]
    clean_content = str(content or "").strip()[:8000]
    if len(clean_title) < 3 or len(clean_content) < 3:
        raise HTTPException(status_code=422, detail="Informe titulo e conteudo do aprendizado.")
    return AssistenteIAAprendizado(
        id=str(uuid.uuid4()),
        usuario_id=user_id,
        feedback_id=feedback_id,
        memoria_alvo_id=target_memory_id,
        titulo=clean_title,
        conteudo=clean_content,
        categoria=(str(category or "operacao").strip() or "operacao")[:60],
        origem=(str(source or "manual").strip() or "manual")[:40],
        fonte_json=_json_dumps(source_context or {}),
        impacto_json=_json_dumps({
            "scope": "global_admin_memory",
            "applies_after_approval": True,
            "operational_writes": False,
        }),
        status="pending",
    )


def create_learning(
    db: Session,
    current_user: User,
    request: Optional[Request],
    *,
    title: str,
    content: str,
    category: str,
    target_memory_id: Optional[str] = None,
) -> dict[str, Any]:
    if target_memory_id:
        target = db.query(AssistenteIAMemoria).filter(
            AssistenteIAMemoria.id == target_memory_id,
            AssistenteIAMemoria.status == "approved",
        ).first()
        if target is None:
            raise HTTPException(status_code=404, detail="Memoria alvo aprovada nao encontrada.")
    row = _new_learning(
        user_id=int(current_user.id),
        title=title,
        content=content,
        category=category,
        source="manual",
        target_memory_id=target_memory_id,
        source_context={"created_by_admin": True},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="aprendizado",
        entidade_id=row.id,
        acao="ASSISTENTE_IA_APRENDIZADO_PROPOSTO",
        descricao="Administrador criou uma sugestao de aprendizado para revisao.",
        detalhes={"titulo": row.titulo, "memoria_alvo_id": target_memory_id},
        request=request,
    )
    return _serialize_learning(row)


def list_learnings(
    db: Session,
    current_user: User,
    *,
    status: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    query = db.query(AssistenteIAAprendizado).filter(
        AssistenteIAAprendizado.usuario_id == current_user.id
    )
    if status:
        query = query.filter(AssistenteIAAprendizado.status == status)
    rows = query.order_by(AssistenteIAAprendizado.created_at.desc()).limit(max(1, min(200, limit))).all()
    counts = dict(
        db.query(AssistenteIAAprendizado.status, func.count(AssistenteIAAprendizado.id))
        .filter(AssistenteIAAprendizado.usuario_id == current_user.id)
        .group_by(AssistenteIAAprendizado.status)
        .all()
    )
    return {
        "items": [_serialize_learning(row) for row in rows],
        "counts": {
            "pending": int(counts.get("pending", 0)),
            "approved": int(counts.get("approved", 0)),
            "rejected": int(counts.get("rejected", 0)),
        },
    }


def decide_learning(
    db: Session,
    current_user: User,
    request: Optional[Request],
    *,
    learning_id: str,
    decision: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    row = db.query(AssistenteIAAprendizado).filter(
        AssistenteIAAprendizado.id == learning_id,
        AssistenteIAAprendizado.usuario_id == current_user.id,
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sugestao de aprendizado nao encontrada.")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Esta sugestao ja foi decidida.")
    if title is not None:
        row.titulo = str(title).strip()[:180]
    if content is not None:
        row.conteudo = str(content).strip()[:8000]
    if category is not None:
        row.categoria = str(category).strip()[:60]
    if len(row.titulo) < 3 or len(row.conteudo) < 3 or len(row.categoria) < 2:
        raise HTTPException(status_code=422, detail="Revise titulo, conteudo e categoria antes de aprovar.")
    now_utc = datetime.now(timezone.utc)
    row.revisado_por_id = int(current_user.id)
    row.revisado_em = now_utc
    if decision == "reject":
        row.status = "rejected"
        db.add(row)
        db.commit()
        db.refresh(row)
    elif decision == "approve":
        if row.memoria_alvo_id:
            memory = db.query(AssistenteIAMemoria).filter(
                AssistenteIAMemoria.id == row.memoria_alvo_id,
                AssistenteIAMemoria.status == "approved",
            ).with_for_update().first()
            if memory is None:
                raise HTTPException(status_code=409, detail="A memoria alvo deixou de estar disponivel.")
            _ensure_memory_baseline(db, memory, user_id=int(current_user.id))
            memory.titulo = row.titulo
            memory.conteudo = row.conteudo
            memory.categoria = row.categoria
            memory.origem = "aprendizado_supervisionado"
            memory.aprovado_por_id = int(current_user.id)
            memory.aprovado_em = now_utc
            change_type = "update"
        else:
            memory = AssistenteIAMemoria(
                id=str(uuid.uuid4()),
                titulo=row.titulo,
                conteudo=row.conteudo,
                categoria=row.categoria,
                origem="aprendizado_supervisionado",
                status="approved",
                versao_atual=1,
                criado_por_id=int(current_user.id),
                aprovado_por_id=int(current_user.id),
                aprovado_em=now_utc,
            )
            db.add(memory)
            db.flush()
            change_type = "create"
        _record_memory_version(
            db,
            memory,
            user_id=int(current_user.id),
            change_type=change_type,
            learning_id=row.id,
        )
        regression = _replace_regression_contract(
            db,
            memory,
            user_id=int(current_user.id),
            learning_id=row.id,
        )
        row.status = "approved"
        row.memoria_id = memory.id
        row.caso_regressao_id = regression.id
        db.add(row)
        db.commit()
        db.refresh(row)
    else:
        raise HTTPException(status_code=422, detail="Decisao invalida.")
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="aprendizado",
        entidade_id=row.id,
        acao=(
            "ASSISTENTE_IA_APRENDIZADO_APROVADO"
            if decision == "approve"
            else "ASSISTENTE_IA_APRENDIZADO_REJEITADO"
        ),
        descricao="Administrador decidiu uma sugestao de aprendizado supervisionado.",
        detalhes={"decisao": decision, "memoria_id": row.memoria_id},
        request=request,
    )
    return _serialize_learning(row)


def list_memory_versions(db: Session, *, memory_id: str) -> list[dict[str, Any]]:
    memory = db.query(AssistenteIAMemoria.id).filter(AssistenteIAMemoria.id == memory_id).first()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memoria nao encontrada.")
    rows = db.query(AssistenteIAMemoriaVersao).filter(
        AssistenteIAMemoriaVersao.memoria_id == memory_id
    ).order_by(AssistenteIAMemoriaVersao.versao.desc()).all()
    return [_serialize_memory_version(row) for row in rows]


def rollback_memory(
    db: Session,
    current_user: User,
    request: Optional[Request],
    *,
    memory_id: str,
    target_version: int,
) -> dict[str, Any]:
    memory = db.query(AssistenteIAMemoria).filter(
        AssistenteIAMemoria.id == memory_id,
        AssistenteIAMemoria.status == "approved",
    ).with_for_update().first()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memoria aprovada nao encontrada.")
    _ensure_memory_baseline(db, memory, user_id=int(current_user.id))
    source = db.query(AssistenteIAMemoriaVersao).filter(
        AssistenteIAMemoriaVersao.memoria_id == memory_id,
        AssistenteIAMemoriaVersao.versao == target_version,
    ).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Versao de destino nao encontrada.")
    if int(memory.versao_atual or 1) == int(target_version):
        raise HTTPException(status_code=409, detail="A memoria ja esta nesta versao.")
    previous_version = int(memory.versao_atual or 1)
    memory.titulo = source.titulo
    memory.conteudo = source.conteudo
    memory.categoria = source.categoria
    memory.origem = "rollback_supervisionado"
    memory.aprovado_por_id = int(current_user.id)
    memory.aprovado_em = datetime.now(timezone.utc)
    version_row = _record_memory_version(
        db,
        memory,
        user_id=int(current_user.id),
        change_type="rollback",
    )
    regression = _replace_regression_contract(db, memory, user_id=int(current_user.id))
    db.commit()
    db.refresh(memory)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="memoria",
        entidade_id=memory.id,
        acao="ASSISTENTE_IA_MEMORIA_REVERTIDA",
        descricao="Administrador restaurou uma versao anterior como nova versao da memoria.",
        detalhes={
            "versao_anterior": previous_version,
            "versao_restaurada": target_version,
            "nova_versao": version_row.versao,
            "caso_regressao_id": regression.id,
        },
        request=request,
    )
    return serialize_memory(memory)


def _serialize_regression_case(row: AssistenteIARegressaoCaso) -> dict[str, Any]:
    return {
        "id": row.id,
        "learning_id": row.aprendizado_id,
        "memory_id": row.memoria_id,
        "type": row.tipo,
        "prompt": row.prompt,
        "expectation": _json_loads(row.expectativa_json, {}),
        "status": row.status,
        "last_status": row.ultimo_status,
        "verified_at": row.verificado_em.isoformat() if row.verificado_em else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_regression_cases(db: Session, *, include_archived: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    query = db.query(AssistenteIARegressaoCaso)
    if not include_archived:
        query = query.filter(AssistenteIARegressaoCaso.status == "active")
    rows = query.order_by(AssistenteIARegressaoCaso.created_at.desc()).limit(max(1, min(200, limit))).all()
    return [_serialize_regression_case(row) for row in rows]


def approved_memory_context(db: Session, *, limit: int = 30) -> str:
    rows = (
        db.query(AssistenteIAMemoria)
        .filter(AssistenteIAMemoria.status == "approved")
        .order_by(AssistenteIAMemoria.updated_at.desc(), AssistenteIAMemoria.created_at.desc())
        .limit(max(1, min(50, limit)))
        .all()
    )
    if not rows:
        return "Nenhuma memoria operacional aprovada pelo administrador."
    return "\n".join(f"- [{row.categoria}] {row.titulo}: {row.conteudo}" for row in rows)[:14000]


def serialize_document(row: AssistenteIAConhecimentoDocumento, *, include_content: bool = False) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "title": row.titulo,
        "category": row.categoria,
        "source": row.fonte,
        "status": row.status,
        "semantic_enabled": bool(getattr(row, "semantic_enabled", False)),
        "semantic_status": str(getattr(row, "semantic_status", "disabled") or "disabled"),
        "embedding_model": getattr(row, "embedding_model", None),
        "semantic_error": getattr(row, "semantic_error", None),
        "indexed_at": row.indexed_at.isoformat() if getattr(row, "indexed_at", None) else None,
        "content_sha256": row.conteudo_sha256,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        payload["content"] = row.conteudo
    return payload


def create_document(
    db: Session,
    current_user: User,
    *,
    title: str,
    content: str,
    category: str,
    source: Optional[str],
    semantic_index: bool = False,
) -> dict[str, Any]:
    clean_title = str(title or "").strip()[:220]
    clean_content = str(content or "").strip()
    if not clean_title or len(clean_content) < 20:
        raise HTTPException(status_code=422, detail="Informe titulo e conteudo com ao menos 20 caracteres.")
    if len(clean_content) > 250_000:
        raise HTTPException(status_code=413, detail="O documento deve ter no maximo 250 mil caracteres.")
    clean_source = str(source or "").strip()[:500] or None
    if semantic_index and not clean_source:
        raise HTTPException(
            status_code=422,
            detail="Informe a fonte antes de ativar a memoria semantica.",
        )
    digest = hashlib.sha256(clean_content.encode("utf-8")).hexdigest()
    duplicate = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.conteudo_sha256 == digest,
        AssistenteIAConhecimentoDocumento.status == "active",
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Este conteudo ja esta ativo na base de conhecimento.")
    row = AssistenteIAConhecimentoDocumento(
        id=str(uuid.uuid4()),
        titulo=clean_title,
        categoria=(str(category or "manual").strip() or "manual")[:60],
        conteudo=clean_content,
        fonte=clean_source,
        conteudo_sha256=digest,
        status="active",
        semantic_enabled=bool(semantic_index),
        semantic_status="queued" if semantic_index else "disabled",
        criado_por_id=int(current_user.id),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_document(row, include_content=True)


def list_documents(db: Session, *, include_archived: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    query = db.query(AssistenteIAConhecimentoDocumento)
    if not include_archived:
        query = query.filter(AssistenteIAConhecimentoDocumento.status == "active")
    rows = query.order_by(AssistenteIAConhecimentoDocumento.updated_at.desc()).limit(max(1, min(200, limit))).all()
    return [serialize_document(row) for row in rows]


def archive_document(db: Session, *, document_id: str) -> dict[str, Any]:
    row = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.id == document_id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Documento nao encontrado.")
    row.status = "archived"
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_document(row)


def search_knowledge(db: Session, *, query: str, limit: int = 5) -> dict[str, Any]:
    terms = {term for term in _normalize(query).split() if len(term) >= 3}
    if not terms:
        return {"ok": False, "error": "Informe termos mais especificos para consultar a base interna."}
    rows = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.status == "active"
    ).order_by(AssistenteIAConhecimentoDocumento.updated_at.desc()).limit(300).all()
    ranked: list[tuple[int, AssistenteIAConhecimentoDocumento, list[str]]] = []
    for row in rows:
        title = _normalize(row.titulo)
        content = _normalize(row.conteudo)
        matches = sorted(term for term in terms if term in title or term in content)
        score = sum(5 if term in title else 1 for term in matches)
        if score:
            ranked.append((score, row, matches))
    ranked.sort(key=lambda item: (item[0], item[1].updated_at or item[1].created_at), reverse=True)
    lexical_items = []
    for score, row, matches in ranked[: max(1, min(10, limit))]:
        normalized_content = _normalize(row.conteudo)
        first_position = min((normalized_content.find(term) for term in matches if term in normalized_content), default=0)
        start = max(0, first_position - 250)
        excerpt = row.conteudo[start : start + 1600].strip()
        lexical_items.append({
            "document_id": row.id,
            "title": row.titulo,
            "category": row.categoria,
            "source": row.fonte,
            "keyword_score": score,
            "matched_terms": matches,
            "excerpt": excerpt,
            "retrieval": "keyword",
        })

    semantic_items: list[dict[str, Any]] = []
    try:
        from app.services.assistente_ia_autonomy import semantic_search_documents

        semantic_items = semantic_search_documents(
            db,
            query=query,
            limit=max(3, min(30, limit * 3)),
        )
    except Exception:
        semantic_items = []

    max_keyword = max((float(item["keyword_score"]) for item in lexical_items), default=1.0)
    combined: dict[str, dict[str, Any]] = {}
    for item in lexical_items:
        keyword_normalized = float(item["keyword_score"]) / max_keyword
        combined[str(item["document_id"])] = {
            **item,
            "semantic_score": None,
            "score": round(0.35 * keyword_normalized, 5),
        }
    for item in semantic_items:
        document_id = str(item["document_id"])
        semantic_score = float(item.get("semantic_score") or 0.0)
        existing = combined.get(document_id)
        if existing is None:
            combined[document_id] = {
                **item,
                "keyword_score": 0,
                "matched_terms": [],
                "score": round(0.65 * max(0.0, semantic_score), 5),
            }
            continue
        if semantic_score > float(existing.get("semantic_score") or 0.0):
            existing["semantic_score"] = semantic_score
            existing["score"] = round(float(existing["score"]) + 0.65 * max(0.0, semantic_score), 5)
            existing["retrieval"] = "hybrid"
            if len(str(existing.get("excerpt") or "")) < 80:
                existing["excerpt"] = item.get("excerpt")

    items = sorted(combined.values(), key=lambda item: float(item.get("score") or 0), reverse=True)
    items = items[: max(1, min(10, limit))]
    for item in items:
        item["excerpt"] = str(item.get("excerpt") or "")[:1600]
    return {
        "ok": True,
        "query": query,
        "total": len(items),
        "items": items,
        "retrieval": "hybrid" if semantic_items else "keyword",
    }


def create_feedback(
    db: Session,
    current_user: User,
    *,
    message_id: int,
    rating: str,
    category: Optional[str],
    comment: Optional[str],
    expected_correction: Optional[str],
    request: Optional[Request] = None,
) -> dict[str, Any]:
    message = db.query(AssistenteIAMensagem).filter(
        AssistenteIAMensagem.id == message_id,
        AssistenteIAMensagem.usuario_id == current_user.id,
        AssistenteIAMensagem.papel == "assistant",
    ).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Resposta da Mente nao encontrada.")
    normalized_rating = str(rating or "").strip().lower()
    if normalized_rating not in {"positive", "negative"}:
        raise HTTPException(status_code=422, detail="Avaliacao invalida.")
    row = AssistenteIAFeedback(
        mensagem_id=int(message.id),
        conversa_id=str(message.conversa_id),
        usuario_id=int(current_user.id),
        avaliacao=normalized_rating,
        categoria=str(category or "").strip()[:60] or None,
        comentario=str(comment or "").strip()[:2000] or None,
        correcao_esperada=str(expected_correction or "").strip()[:6000] or None,
    )
    db.add(row)
    db.flush()
    learning: Optional[AssistenteIAAprendizado] = None
    if (
        normalized_rating == "negative"
        and row.correcao_esperada
        and _tables_available(db, "assistente_ia_aprendizados")
    ):
        user_message = db.query(AssistenteIAMensagem).filter(
            AssistenteIAMensagem.conversa_id == message.conversa_id,
            AssistenteIAMensagem.usuario_id == current_user.id,
            AssistenteIAMensagem.papel == "user",
            AssistenteIAMensagem.id < message.id,
        ).order_by(AssistenteIAMensagem.id.desc()).first()
        prompt = str(user_message.conteudo if user_message else "").strip()
        title_seed = prompt[:140] if prompt else (row.categoria or "Resposta da Mente")
        learning = _new_learning(
            user_id=int(current_user.id),
            title=f"Correcao: {title_seed}"[:180],
            content=row.correcao_esperada,
            category=row.categoria or "correcao",
            source="feedback",
            feedback_id=int(row.id),
            source_context={
                "conversation_id": str(message.conversa_id),
                "user_request": prompt[:6000] or None,
                "assistant_response": str(message.conteudo or "")[:6000],
                "feedback_comment": row.comentario,
            },
        )
        db.add(learning)
    db.commit()
    db.refresh(row)
    if learning is not None:
        db.refresh(learning)
        registrar_auditoria(
            current_user=current_user,
            modulo="assistente_ia",
            entidade="aprendizado",
            entidade_id=learning.id,
            acao="ASSISTENTE_IA_APRENDIZADO_SUGERIDO_POR_FEEDBACK",
            descricao="Feedback negativo gerou sugestao pendente, sem alterar a memoria ativa.",
            detalhes={"feedback_id": row.id, "categoria": learning.categoria},
            request=request,
        )
    payload = {
        "id": row.id,
        "message_id": row.mensagem_id,
        "conversation_id": row.conversa_id,
        "rating": row.avaliacao,
        "category": row.categoria,
        "comment": row.comentario,
        "expected_correction": row.correcao_esperada,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    payload["learning_suggestion"] = _serialize_learning(learning) if learning is not None else None
    return payload


def list_pending_actions(db: Session, current_user: User, *, limit: int = 100) -> list[dict[str, Any]]:
    from app.services.assistente_ia_tools import serialize_pending_action

    rows = (
        db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.usuario_id == current_user.id,
            AssistenteIAAcaoPendente.status == "pending",
        )
        .order_by(AssistenteIAAcaoPendente.created_at.desc())
        .limit(max(1, min(200, limit)))
        .all()
    )
    return [serialize_pending_action(row) for row in rows]


def executive_summary(db: Session, current_user: User, *, reference: Optional[date] = None) -> dict[str, Any]:
    reference = reference or datetime.now(LOCAL_TZ).date()
    start, end = _local_day_bounds(reference)
    start_naive = start.replace(tzinfo=None)
    end_naive = end.replace(tzinfo=None)
    appointments = db.query(Agendamento).filter(
        Agendamento.inicio >= start_naive,
        Agendamento.inicio < end_naive,
        Agendamento.status.notin_(["Cancelado", "Expirado"]),
    ).order_by(Agendamento.inicio.asc()).all()
    status_counts: dict[str, int] = {}
    for row in appointments:
        status = str(row.status or "Nao informado")
        status_counts[status] = status_counts.get(status, 0) + 1

    now_naive = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    expiring = db.query(Agendamento).filter(
        Agendamento.status == "Reservado",
        Agendamento.reserva_expira_em.isnot(None),
        Agendamento.reserva_expira_em > now_naive,
        Agendamento.reserva_expira_em <= now_naive + timedelta(hours=6),
    ).count()
    overdue_rows = db.query(ContaReceber).filter(
        ContaReceber.status.in_(["Pendente", "Atrasado"]),
        ContaReceber.data_vencimento < now_naive,
    ).all()
    month_start = datetime(reference.year, reference.month, 1)
    next_month = datetime(reference.year + (1 if reference.month == 12 else 0), 1 if reference.month == 12 else reference.month + 1, 1)
    revenue_month = db.query(func.coalesce(func.sum(Transacao.valor_final), 0.0)).filter(
        Transacao.tipo == "entrada",
        Transacao.status.in_(["Pago", "Recebido"]),
        Transacao.data_transacao >= month_start,
        Transacao.data_transacao < next_month,
    ).scalar()
    pending_approvals = db.query(AssistenteIAAcaoPendente).filter(
        AssistenteIAAcaoPendente.usuario_id == current_user.id,
        AssistenteIAAcaoPendente.status == "pending",
    ).count()
    alerts: list[dict[str, Any]] = []
    if expiring:
        alerts.append({"level": "attention", "message": f"{expiring} reserva(s) expiram nas proximas 6 horas."})
    if overdue_rows:
        alerts.append({"level": "attention", "message": f"{len(overdue_rows)} conta(s) vencida(s) somam R$ {sum(float(row.valor or 0) for row in overdue_rows):,.2f}."})
    if pending_approvals:
        alerts.append({"level": "info", "message": f"{pending_approvals} acao(oes) aguardam sua aprovacao na Mente."})
    if not alerts:
        alerts.append({"level": "ok", "message": "Sem alertas operacionais prioritarios para esta leitura."})
    return {
        "ok": True,
        "date": reference.isoformat(),
        "agenda": {
            "total": len(appointments),
            "by_status": status_counts,
            "first_at": appointments[0].inicio.isoformat() if appointments else None,
            "last_at": appointments[-1].fim.isoformat() if appointments and appointments[-1].fim else None,
            "reservations_expiring_6h": expiring,
        },
        "finance": {
            "month_revenue": round(float(revenue_month or 0), 2),
            "overdue_count": len(overdue_rows),
            "overdue_total": round(sum(float(row.valor or 0) for row in overdue_rows), 2),
        },
        "pending_approvals": pending_approvals,
        "alerts": alerts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def clinical_report_context(db: Session, current_user: User, *, report_id: int) -> dict[str, Any]:
    report = db.query(Laudo).filter(Laudo.id == int(report_id)).first()
    if report is None:
        return {"ok": False, "error": "Laudo nao encontrado."}
    try:
        payload = laudos.obter_laudo(laudo_id=int(report_id), db=db, current_user=current_user)
    except Exception:
        db.rollback()
        payload = {
            "id": report.id,
            "paciente_id": report.paciente_id,
            "tipo": report.tipo,
            "titulo": report.titulo,
            "descricao": report.descricao,
            "diagnostico": report.diagnostico,
            "observacoes": report.observacoes,
            "status": report.status,
            "clinic_id": report.clinic_id,
            "data_exame": report.data_exame,
        }
    previous = db.query(Laudo).filter(
        Laudo.paciente_id == report.paciente_id,
        Laudo.id != report.id,
    ).order_by(Laudo.data_exame.desc(), Laudo.created_at.desc()).limit(5).all()
    return {
        "ok": True,
        "report": payload,
        "previous_reports": [
            {
                "id": row.id,
                "type": row.tipo,
                "title": row.titulo,
                "exam_date": row.data_exame.isoformat() if row.data_exame else None,
                "description": str(row.descricao or "")[:3000],
                "diagnosis": str(row.diagnostico or "")[:2000],
            }
            for row in previous
        ],
        "safety": "Contexto somente para apoio. O rascunho nao substitui revisao veterinaria e nunca finaliza o laudo.",
    }


def save_clinical_draft(
    db: Session,
    current_user: User,
    *,
    conversation_id: str,
    report_id: int,
    title: str,
    content: str,
    alerts: list[str],
    source_report_ids: list[int],
) -> dict[str, Any]:
    report = db.query(Laudo).filter(Laudo.id == int(report_id)).first()
    if report is None:
        return {"ok": False, "error": "Laudo nao encontrado."}
    clean_content = str(content or "").strip()
    if len(clean_content) < 20:
        return {"ok": False, "error": "O rascunho clinico ficou incompleto."}
    row = AssistenteIARascunhoClinico(
        id=str(uuid.uuid4()),
        laudo_id=int(report.id),
        conversa_id=str(conversation_id),
        usuario_id=int(current_user.id),
        titulo=(str(title or "Rascunho clinico assistido").strip() or "Rascunho clinico assistido")[:220],
        conteudo=clean_content[:60_000],
        alertas_json=_json_dumps([str(item)[:500] for item in alerts[:20]]),
        fontes_json=_json_dumps(sorted({int(report.id), *[int(item) for item in source_report_ids[:20]]})),
        status="draft",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_clinical_draft(row)


def serialize_clinical_draft(row: AssistenteIARascunhoClinico) -> dict[str, Any]:
    return {
        "ok": True,
        "id": row.id,
        "report_id": row.laudo_id,
        "conversation_id": row.conversa_id,
        "title": row.titulo,
        "content": row.conteudo,
        "alerts": _json_loads(row.alertas_json, []),
        "source_report_ids": _json_loads(row.fontes_json, []),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "official_report_modified": False,
    }


def list_clinical_drafts(db: Session, current_user: User, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.query(AssistenteIARascunhoClinico).filter(
        AssistenteIARascunhoClinico.usuario_id == current_user.id,
        AssistenteIARascunhoClinico.status != "archived",
    ).order_by(AssistenteIARascunhoClinico.updated_at.desc()).limit(max(1, min(200, limit))).all()
    return [serialize_clinical_draft(row) for row in rows]


def assistant_metrics(db: Session, current_user: User, *, days: int = 30) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days)))
    messages = db.query(AssistenteIAMensagem).filter(
        AssistenteIAMensagem.usuario_id == current_user.id,
        AssistenteIAMensagem.papel == "assistant",
        AssistenteIAMensagem.created_at >= since,
    ).all()
    feedbacks = db.query(AssistenteIAFeedback).filter(
        AssistenteIAFeedback.usuario_id == current_user.id,
        AssistenteIAFeedback.created_at >= since,
    ).all()
    actions = db.query(AssistenteIAAcaoPendente).filter(
        AssistenteIAAcaoPendente.usuario_id == current_user.id,
        AssistenteIAAcaoPendente.created_at >= since,
    ).all()
    latencies = [int(row.latency_ms) for row in messages if row.latency_ms is not None]
    action_counts: dict[str, int] = {}
    for row in actions:
        action_counts[row.status] = action_counts.get(row.status, 0) + 1
    return {
        "period_days": max(1, min(365, days)),
        "assistant_responses": len(messages),
        "tokens": sum(int(row.total_tokens or 0) for row in messages),
        "average_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "feedback": {
            "positive": sum(1 for row in feedbacks if row.avaliacao == "positive"),
            "negative": sum(1 for row in feedbacks if row.avaliacao == "negative"),
        },
        "actions": action_counts,
    }
