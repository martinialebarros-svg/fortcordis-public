from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import uuid
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.agendamento import Agendamento
from app.models.assistente_ia import (
    AssistenteIAAcaoPendente,
    AssistenteIAConhecimentoDocumento,
    AssistenteIAConhecimentoTrecho,
    AssistenteIAExecucao,
    AssistenteIAMemoria,
    AssistenteIAMissao,
    AssistenteIARegressaoCaso,
)
from app.models.financeiro import ContaReceber, Transacao
from app.models.user import User

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("America/Fortaleza")
MISSION_TYPES = {
    "radar",
    "executive_summary",
    "billing_trend",
    "overdue_debts",
    "clinic_360",
    "eval_lab",
}
MISSION_RECURRENCES = {"daily", "weekly"}

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()
_WORKER_STOP_EVENT = threading.Event()
_RUN_LOCK = threading.Lock()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _normalize_weekdays(values: list[int]) -> list[int]:
    normalized = sorted({int(item) for item in values if 0 <= int(item) <= 6})
    if len(normalized) != len(set(values)) or any(int(item) < 0 or int(item) > 6 for item in values):
        raise HTTPException(status_code=422, detail="Dias da semana devem usar numeros de 0 a 6.")
    return normalized


def _normalize_mission_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    raw = config if isinstance(config, dict) else {}
    if kind == "billing_trend":
        return {
            "months": max(2, min(24, int(raw.get("months") or 5))),
            "clinic": str(raw.get("clinic") or "").strip()[:220] or None,
        }
    if kind == "overdue_debts":
        clinic = str(raw.get("clinic") or "").strip()[:220]
        if not clinic:
            raise HTTPException(status_code=422, detail="Informe a clinica para a missao de debitos.")
        return {"clinic": clinic, "overdue_only": bool(raw.get("overdue_only", True))}
    if kind == "clinic_360":
        clinic = str(raw.get("clinic") or "").strip()[:220]
        if not clinic:
            raise HTTPException(status_code=422, detail="Informe a clinica para a missao Clinicas 360.")
        return {
            "clinic": clinic,
            "period_days": max(30, min(365, int(raw.get("period_days") or 90))),
        }
    return {}


def calculate_next_run(
    *,
    recurrence: str,
    local_time: str,
    weekdays: list[int],
    after: Optional[datetime] = None,
) -> datetime:
    if recurrence not in MISSION_RECURRENCES:
        raise HTTPException(status_code=422, detail="Recorrencia invalida.")
    try:
        hour, minute = [int(part) for part in local_time.split(":", 1)]
        scheduled_time = time(hour=hour, minute=minute)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Horario invalido. Use HH:MM.") from exc

    reference = _as_utc(after) or _utc_now()
    local_reference = reference.astimezone(LOCAL_TZ)
    allowed_days = set(_normalize_weekdays(weekdays)) if recurrence == "weekly" else set(range(7))
    if recurrence == "weekly" and not allowed_days:
        allowed_days = {0}
    for offset in range(8):
        candidate_date = local_reference.date() + timedelta(days=offset)
        if candidate_date.weekday() not in allowed_days:
            continue
        candidate = datetime.combine(candidate_date, scheduled_time, tzinfo=LOCAL_TZ)
        if candidate > local_reference:
            return candidate.astimezone(timezone.utc)
    raise HTTPException(status_code=422, detail="Nao foi possivel calcular a proxima execucao.")


def serialize_mission(row: AssistenteIAMissao) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.usuario_id,
        "title": row.titulo,
        "type": row.tipo,
        "config": _json_loads(row.configuracao_json, {}),
        "recurrence": row.recorrencia,
        "local_time": row.horario_local,
        "weekdays": _json_loads(row.dias_semana_json, []),
        "timezone": row.timezone,
        "enabled": bool(row.enabled),
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_execution(row: AssistenteIAExecucao) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.usuario_id,
        "mission_id": row.missao_id,
        "type": row.tipo,
        "source": row.origem,
        "status": row.status,
        "input": _json_loads(row.entrada_json, {}),
        "output": _json_loads(row.saida_json, None),
        "error": row.erro,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_missions(db: Session, current_user: User) -> list[dict[str, Any]]:
    rows = (
        db.query(AssistenteIAMissao)
        .filter(AssistenteIAMissao.usuario_id == int(current_user.id))
        .order_by(AssistenteIAMissao.enabled.desc(), AssistenteIAMissao.updated_at.desc())
        .limit(200)
        .all()
    )
    return [serialize_mission(row) for row in rows]


def create_mission(
    db: Session,
    current_user: User,
    *,
    title: str,
    kind: str,
    config: dict[str, Any],
    recurrence: str,
    local_time: str,
    weekdays: list[int],
    enabled: bool,
) -> dict[str, Any]:
    if kind not in MISSION_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de missao nao permitido.")
    normalized_days = _normalize_weekdays(weekdays)
    if recurrence == "weekly" and not normalized_days:
        normalized_days = [0]
    normalized_config = _normalize_mission_config(kind, config)
    next_candidate = calculate_next_run(
        recurrence=recurrence,
        local_time=local_time,
        weekdays=normalized_days,
    )
    row = AssistenteIAMissao(
        id=str(uuid.uuid4()),
        usuario_id=int(current_user.id),
        titulo=(str(title or "").strip() or "Missao da Mente")[:180],
        tipo=kind,
        configuracao_json=_json_dumps(normalized_config),
        recorrencia=recurrence,
        horario_local=local_time,
        dias_semana_json=_json_dumps(normalized_days),
        timezone=str(LOCAL_TZ),
        enabled=bool(enabled),
        next_run_at=next_candidate if enabled else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_mission(row)


def update_mission(
    db: Session,
    current_user: User,
    *,
    mission_id: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    row = (
        db.query(AssistenteIAMissao)
        .filter(
            AssistenteIAMissao.id == mission_id,
            AssistenteIAMissao.usuario_id == int(current_user.id),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Missao nao encontrada.")
    if changes.get("title") is not None:
        row.titulo = str(changes["title"]).strip()[:180]
    if changes.get("config") is not None:
        row.configuracao_json = _json_dumps(_normalize_mission_config(row.tipo, changes["config"]))
    if changes.get("recurrence") is not None:
        row.recorrencia = str(changes["recurrence"])
    if changes.get("local_time") is not None:
        row.horario_local = str(changes["local_time"])
    if changes.get("weekdays") is not None:
        days = _normalize_weekdays(changes["weekdays"])
        row.dias_semana_json = _json_dumps(days or ([0] if row.recorrencia == "weekly" else []))
    if changes.get("enabled") is not None:
        row.enabled = bool(changes["enabled"])
    row.next_run_at = (
        calculate_next_run(
            recurrence=row.recorrencia,
            local_time=row.horario_local,
            weekdays=_json_loads(row.dias_semana_json, []),
        )
        if row.enabled
        else None
    )
    row.updated_at = _utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_mission(row)


def enqueue_execution(
    db: Session,
    current_user: User,
    *,
    kind: str,
    input_data: dict[str, Any],
    source: str = "manual",
    mission_id: Optional[str] = None,
) -> AssistenteIAExecucao:
    row = AssistenteIAExecucao(
        id=str(uuid.uuid4()),
        usuario_id=int(current_user.id),
        missao_id=mission_id,
        tipo=kind,
        origem=source,
        status="queued",
        entrada_json=_json_dumps(input_data),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def enqueue_mission_now(db: Session, current_user: User, *, mission_id: str) -> dict[str, Any]:
    mission = (
        db.query(AssistenteIAMissao)
        .filter(
            AssistenteIAMissao.id == mission_id,
            AssistenteIAMissao.usuario_id == int(current_user.id),
        )
        .first()
    )
    if mission is None:
        raise HTTPException(status_code=404, detail="Missao nao encontrada.")
    execution = enqueue_execution(
        db,
        current_user,
        kind=mission.tipo,
        input_data=_json_loads(mission.configuracao_json, {}),
        source="manual",
        mission_id=mission.id,
    )
    return serialize_execution(execution)


def list_executions(
    db: Session,
    current_user: User,
    *,
    kind: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(AssistenteIAExecucao).filter(
        AssistenteIAExecucao.usuario_id == int(current_user.id)
    )
    if kind:
        query = query.filter(AssistenteIAExecucao.tipo == kind)
    rows = query.order_by(AssistenteIAExecucao.created_at.desc()).limit(max(1, min(200, limit))).all()
    return [serialize_execution(row) for row in rows]


def _month_bounds(reference: date) -> tuple[datetime, datetime]:
    start = datetime(reference.year, reference.month, 1)
    if reference.month == 12:
        return start, datetime(reference.year + 1, 1, 1)
    return start, datetime(reference.year, reference.month + 1, 1)


def _sum_revenue(db: Session, start: datetime, end: datetime) -> float:
    value = db.query(func.coalesce(func.sum(Transacao.valor_final), 0.0)).filter(
        Transacao.tipo == "entrada",
        Transacao.status.in_(["Pago", "Recebido"]),
        Transacao.data_transacao >= start,
        Transacao.data_transacao < end,
    ).scalar()
    return round(float(value or 0), 2)


def build_proactive_radar(
    db: Session,
    current_user: User,
    *,
    reference: Optional[date] = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(LOCAL_TZ).date()
    today_end = datetime.combine(reference + timedelta(days=1), time.min)
    current_month_start, _ = _month_bounds(reference)
    previous_month_last = current_month_start.date() - timedelta(days=1)
    previous_month_start = datetime(previous_month_last.year, previous_month_last.month, 1)
    comparable_day = min(reference.day, monthrange(previous_month_last.year, previous_month_last.month)[1])
    previous_period_end = datetime(
        previous_month_last.year,
        previous_month_last.month,
        comparable_day,
    ) + timedelta(days=1)

    current_revenue = _sum_revenue(db, current_month_start, today_end)
    previous_revenue = _sum_revenue(db, previous_month_start, previous_period_end)
    revenue_change = (
        round(((current_revenue - previous_revenue) / previous_revenue) * 100, 1)
        if previous_revenue > 0
        else None
    )

    recent_start = today_end - timedelta(days=7)
    prior_start = recent_start - timedelta(days=7)
    active_status_filter = Agendamento.status.notin_(["Cancelado", "Expirado"])
    recent_appointments = db.query(Agendamento).filter(
        Agendamento.inicio >= recent_start,
        Agendamento.inicio < today_end,
        active_status_filter,
    ).count()
    prior_appointments = db.query(Agendamento).filter(
        Agendamento.inicio >= prior_start,
        Agendamento.inicio < recent_start,
        Agendamento.status.notin_(["Cancelado", "Expirado"]),
    ).count()
    recent_cancelled = db.query(Agendamento).filter(
        Agendamento.inicio >= recent_start,
        Agendamento.inicio < today_end,
        Agendamento.status == "Cancelado",
    ).count()
    prior_cancelled = db.query(Agendamento).filter(
        Agendamento.inicio >= prior_start,
        Agendamento.inicio < recent_start,
        Agendamento.status == "Cancelado",
    ).count()

    now_naive = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    overdue_rows = db.query(ContaReceber).filter(
        ContaReceber.status.in_(["Pendente", "Atrasado"]),
        ContaReceber.data_vencimento < now_naive,
    ).all()
    overdue_total = round(sum(float(row.valor or 0) for row in overdue_rows), 2)
    expiring_reservations = db.query(Agendamento).filter(
        Agendamento.status == "Reservado",
        Agendamento.reserva_expira_em.isnot(None),
        Agendamento.reserva_expira_em > now_naive,
        Agendamento.reserva_expira_em <= now_naive + timedelta(hours=6),
    ).count()
    pending_actions = db.query(AssistenteIAAcaoPendente).filter(
        AssistenteIAAcaoPendente.usuario_id == int(current_user.id),
        AssistenteIAAcaoPendente.status == "pending",
    ).count()

    alerts: list[dict[str, Any]] = []
    if revenue_change is not None and revenue_change <= -10:
        alerts.append({
            "key": "revenue-decline",
            "level": "critical" if revenue_change <= -20 else "attention",
            "title": "Faturamento abaixo do periodo comparavel",
            "evidence": f"Variacao de {revenue_change:.1f}% contra os mesmos {comparable_day} dias do mes anterior.",
            "recommendation": "Revisar volume por clinica, servico e valores ainda pendentes.",
        })
    if recent_cancelled >= max(2, prior_cancelled + 2):
        alerts.append({
            "key": "cancellations-up",
            "level": "attention",
            "title": "Cancelamentos cresceram na ultima semana",
            "evidence": f"Foram {recent_cancelled} cancelamentos, contra {prior_cancelled} na semana anterior.",
            "recommendation": "Identificar clinicas, horarios e motivos mais recorrentes.",
        })
    if overdue_rows:
        alerts.append({
            "key": "overdue-receivables",
            "level": "attention",
            "title": "Debitos vencidos exigem acompanhamento",
            "evidence": f"{len(overdue_rows)} conta(s) vencida(s), total de R$ {overdue_total:,.2f}.",
            "recommendation": "Priorizar cobranca pelos maiores valores e maior atraso.",
        })
    if expiring_reservations:
        alerts.append({
            "key": "reservations-expiring",
            "level": "attention",
            "title": "Reservas proximas do vencimento",
            "evidence": f"{expiring_reservations} reserva(s) expiram nas proximas 6 horas.",
            "recommendation": "Confirmar ou liberar os slots para evitar ociosidade.",
        })
    if pending_actions:
        alerts.append({
            "key": "pending-approvals",
            "level": "info",
            "title": "Acoes aguardando sua decisao",
            "evidence": f"{pending_actions} acao(oes) continuam pendentes na caixa de aprovacao.",
            "recommendation": "Revisar os snapshots antes que as confirmacoes expirem.",
        })
    if not alerts:
        alerts.append({
            "key": "healthy",
            "level": "ok",
            "title": "Operacao sem bloqueio prioritario",
            "evidence": "Nenhuma variacao relevante ultrapassou os limites do radar.",
            "recommendation": "Manter acompanhamento recorrente.",
        })

    return {
        "ok": True,
        "date": reference.isoformat(),
        "generated_at": _utc_now().isoformat(),
        "alerts": alerts,
        "indicators": {
            "revenue": {
                "current_period": current_revenue,
                "previous_comparable_period": previous_revenue,
                "change_percent": revenue_change,
                "comparable_days": comparable_day,
            },
            "appointments": {
                "last_7_days": recent_appointments,
                "previous_7_days": prior_appointments,
                "cancelled_last_7_days": recent_cancelled,
                "cancelled_previous_7_days": prior_cancelled,
            },
            "overdue": {"count": len(overdue_rows), "total": overdue_total},
            "reservations_expiring_6h": expiring_reservations,
            "pending_approvals": pending_actions,
        },
        "safety": "Radar somente de leitura; nenhuma acao operacional foi executada.",
    }


def run_radar_now(db: Session, current_user: User, *, reference: Optional[date] = None) -> dict[str, Any]:
    execution = AssistenteIAExecucao(
        id=str(uuid.uuid4()),
        usuario_id=int(current_user.id),
        tipo="radar",
        origem="manual",
        status="running",
        entrada_json=_json_dumps({"date": reference.isoformat() if reference else None}),
        started_at=_utc_now(),
    )
    db.add(execution)
    db.commit()
    try:
        result = build_proactive_radar(db, current_user, reference=reference)
        execution.status = "completed"
        execution.saida_json = _json_dumps(result)
    except Exception as exc:
        db.rollback()
        execution = db.query(AssistenteIAExecucao).filter(
            AssistenteIAExecucao.id == execution.id
        ).one()
        execution.status = "error"
        execution.erro = str(exc)[:2000]
        raise
    finally:
        execution.finished_at = _utc_now()
        db.add(execution)
        db.commit()
    db.refresh(execution)
    return serialize_execution(execution)


def latest_radar(db: Session, current_user: User) -> Optional[dict[str, Any]]:
    row = (
        db.query(AssistenteIAExecucao)
        .filter(
            AssistenteIAExecucao.usuario_id == int(current_user.id),
            AssistenteIAExecucao.tipo == "radar",
            AssistenteIAExecucao.status == "completed",
        )
        .order_by(AssistenteIAExecucao.created_at.desc())
        .first()
    )
    return serialize_execution(row) if row else None


def enqueue_knowledge_index(
    db: Session,
    current_user: User,
    *,
    document_id: str,
) -> dict[str, Any]:
    document = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.id == document_id,
        AssistenteIAConhecimentoDocumento.status == "active",
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Documento nao encontrado.")
    if not bool(settings.ASSISTENTE_IA_SEMANTIC_SEARCH_ENABLED):
        raise HTTPException(status_code=503, detail="A busca semantica esta desabilitada neste ambiente.")
    existing = db.query(AssistenteIAExecucao).filter(
        AssistenteIAExecucao.tipo == "knowledge_index",
        AssistenteIAExecucao.status.in_(["queued", "running"]),
        AssistenteIAExecucao.entrada_json.like(f'%"document_id": "{document_id}"%'),
    ).first()
    if existing:
        return serialize_execution(existing)
    document.semantic_enabled = True
    document.semantic_status = "queued"
    document.semantic_error = None
    document.embedding_model = str(settings.ASSISTENTE_IA_EMBEDDING_MODEL)
    execution = AssistenteIAExecucao(
        id=str(uuid.uuid4()),
        usuario_id=int(current_user.id),
        tipo="knowledge_index",
        origem="manual",
        status="queued",
        entrada_json=_json_dumps({"document_id": document_id}),
    )
    db.add_all([document, execution])
    db.commit()
    db.refresh(execution)
    return serialize_execution(execution)


def _chunk_text(content: str, *, max_chars: int = 5000) -> list[str]:
    normalized = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for start in range(0, len(paragraph), max_chars):
            pieces.append(paragraph[start : start + max_chars].strip())
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip() if current else piece
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks[:100]


def _embedding_client() -> OpenAI:
    api_key = str(settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("Credencial da OpenAI nao configurada para indexacao semantica.")
    return OpenAI(api_key=api_key, timeout=90.0, max_retries=1)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    client = _embedding_client()
    vectors: list[list[float]] = []
    model = str(settings.ASSISTENTE_IA_EMBEDDING_MODEL or "text-embedding-3-small")
    for start in range(0, len(texts), 32):
        response = client.embeddings.create(
            model=model,
            input=texts[start : start + 32],
            encoding_format="float",
        )
        vectors.extend([[float(value) for value in item.embedding] for item in response.data])
    if len(vectors) != len(texts):
        raise RuntimeError("A indexacao semantica retornou uma quantidade inesperada de vetores.")
    return vectors


def _index_document(db: Session, execution: AssistenteIAExecucao) -> dict[str, Any]:
    document_id = str(_json_loads(execution.entrada_json, {}).get("document_id") or "")
    document = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.id == document_id,
        AssistenteIAConhecimentoDocumento.status == "active",
    ).first()
    if document is None:
        raise RuntimeError("Documento ativo nao encontrado para indexacao.")
    document.semantic_status = "indexing"
    document.semantic_error = None
    db.add(document)
    db.commit()

    chunks = _chunk_text(document.conteudo)
    if not chunks:
        raise RuntimeError("Documento sem conteudo indexavel.")
    vectors = _embed_texts([f"{document.titulo}\n\n{chunk}" for chunk in chunks])
    db.query(AssistenteIAConhecimentoTrecho).filter(
        AssistenteIAConhecimentoTrecho.documento_id == document.id
    ).delete(synchronize_session=False)
    model = str(settings.ASSISTENTE_IA_EMBEDDING_MODEL or "text-embedding-3-small")
    for order, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(AssistenteIAConhecimentoTrecho(
            documento_id=document.id,
            ordem=order,
            conteudo=chunk,
            conteudo_sha256=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
            embedding_json=_json_dumps(vector),
            embedding_model=model,
        ))
    document.semantic_enabled = True
    document.semantic_status = "ready"
    document.embedding_model = model
    document.semantic_error = None
    document.indexed_at = _utc_now()
    db.add(document)
    db.commit()
    return {"document_id": document.id, "chunks": len(chunks), "model": model}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return -1.0
    return dot / (left_norm * right_norm)


def semantic_search_documents(db: Session, *, query: str, limit: int = 10) -> list[dict[str, Any]]:
    if not bool(settings.ASSISTENTE_IA_SEMANTIC_SEARCH_ENABLED):
        return []
    ready_document_ids = [
        row[0]
        for row in db.query(AssistenteIAConhecimentoDocumento.id).filter(
            AssistenteIAConhecimentoDocumento.status == "active",
            AssistenteIAConhecimentoDocumento.semantic_status == "ready",
        ).all()
    ]
    if not ready_document_ids:
        return []
    try:
        query_vector = _embed_texts([str(query or "").strip()])[0]
    except Exception:
        logger.exception("Falha controlada na consulta semantica; busca lexical sera preservada.")
        return []
    rows = (
        db.query(AssistenteIAConhecimentoTrecho, AssistenteIAConhecimentoDocumento)
        .join(
            AssistenteIAConhecimentoDocumento,
            AssistenteIAConhecimentoDocumento.id == AssistenteIAConhecimentoTrecho.documento_id,
        )
        .filter(AssistenteIAConhecimentoTrecho.documento_id.in_(ready_document_ids))
        .limit(1500)
        .all()
    )
    ranked: list[tuple[float, AssistenteIAConhecimentoTrecho, AssistenteIAConhecimentoDocumento]] = []
    for chunk, document in rows:
        vector = _json_loads(chunk.embedding_json, [])
        similarity = _cosine_similarity(query_vector, vector if isinstance(vector, list) else [])
        if similarity >= 0.20:
            ranked.append((similarity, chunk, document))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    for similarity, chunk, document in ranked[: max(1, min(30, limit))]:
        results.append({
            "document_id": document.id,
            "chunk_id": chunk.id,
            "title": document.titulo,
            "category": document.categoria,
            "source": document.fonte,
            "semantic_score": round(similarity, 5),
            "excerpt": chunk.conteudo[:1800],
            "retrieval": "semantic",
        })
    return results


def _eval_dataset() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "evals" / "assistente_ia_admin_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


EVAL_ROUTING_INSTRUCTIONS = """
Voce esta em um laboratorio seguro da Mente FortCordis.
Escolha exatamente uma ferramenta adequada para a solicitacao.
Nenhuma ferramenta sera executada e nenhum dado real foi fornecido.
Responda obrigatoriamente com uma chamada de ferramenta, nunca com texto ou recusa.
Ferramentas `solicitar_*` apenas preparam uma acao pendente para confirmacao humana.

Regras de roteamento que devem ser observadas:
- servicos realizados ou todas as ordens de servico do periodo usa analisar_servicos_realizados;
- faturamento previsto, valor da agenda ou soma dos servicos agendados em uma data futura usa projetar_faturamento_agenda;
- tempo ou distancia entre clinicas usa consultar_deslocamento_clinicas;
- funcionamento geral ou horario de encerramento da agenda usa consultar_funcionamento_agenda;
- visao 360, saude operacional, motivo de queda ou plano de acao de uma clinica usa consultar_clinica_360;
- comparacao de desempenho ou prioridade entre clinicas usa comparar_clinicas_360;
- remarcacao de agendamento identificado, com data e horario de destino, usa solicitar_remarcacao_agendamento;
- bloqueio com data, inicio, fim e motivo definidos usa solicitar_bloqueio_agenda;
- incluir paciente e tutor em reserva existente usa solicitar_vinculo_paciente_reserva sem cancelar o horario;
- pedido de preparar rascunho sem conteudo clinico suficiente usa obter_contexto_laudo primeiro;
- pedido de salvar rascunho com titulo e conteudo explicitos usa salvar_rascunho_clinico;
- obter contexto ou salvar rascunho nunca modifica nem finaliza o laudo oficial.
""".strip()


def _memory_contract_results(db: Session) -> list[dict[str, Any]]:
    bind = db.get_bind()
    if bind is None:
        return []
    available_tables = set(inspect(bind).get_table_names())
    if not {"assistente_ia_memorias", "assistente_ia_regressao_casos"}.issubset(available_tables):
        return []
    now_utc = _utc_now()
    results: list[dict[str, Any]] = []
    rows = db.query(AssistenteIARegressaoCaso).filter(
        AssistenteIARegressaoCaso.status == "active",
        AssistenteIARegressaoCaso.tipo == "memory_contract",
    ).order_by(AssistenteIARegressaoCaso.created_at.asc()).limit(500).all()
    for row in rows:
        expected = _json_loads(row.expectativa_json, {})
        memory = db.query(AssistenteIAMemoria).filter(
            AssistenteIAMemoria.id == row.memoria_id,
            AssistenteIAMemoria.status == "approved",
        ).first()
        expected_version = int(expected.get("version") or 0)
        expected_digest = str(expected.get("content_sha256") or "")
        actual_version = int(getattr(memory, "versao_atual", 0) or 0) if memory else 0
        actual_digest = hashlib.sha256(memory.conteudo.encode("utf-8")).hexdigest() if memory else ""
        passed = bool(
            memory
            and expected_version > 0
            and actual_version == expected_version
            and expected_digest
            and actual_digest == expected_digest
        )
        expected_label = f"memoria_aprovada_v{expected_version}"
        error = None
        if not passed:
            error = (
                "Contrato de memoria divergente: "
                f"versao esperada={expected_version}, atual={actual_version}."
            )
        row.ultimo_status = "passed" if passed else "failed"
        row.verificado_em = now_utc
        db.add(row)
        results.append({
            "id": f"memory-contract-{row.id}",
            "case_type": "memory_contract",
            "memory_id": row.memoria_id,
            "expected_tool": expected_label,
            "selected_tools": [expected_label] if passed else [],
            "passed": passed,
            "error": error,
        })
    if rows:
        db.flush()
    return results


def _run_eval_lab(db: Session, execution: AssistenteIAExecucao) -> dict[str, Any]:
    from app.services.assistente_ia_tools import TOOL_DEFINITIONS

    api_key = str(settings.OPENAI_API_KEY or "").strip()
    if not settings.ASSISTENTE_IA_ENABLED or not api_key:
        raise RuntimeError("Assistente IA indisponivel para executar o laboratorio.")
    dataset = _eval_dataset()
    client = OpenAI(api_key=api_key, timeout=90.0, max_retries=1)
    results: list[dict[str, Any]] = []
    last_response_id: Optional[str] = None
    for case in dataset.get("cases", []):
        selected_tools: list[str] = []
        error: Optional[str] = None
        try:
            response = client.responses.create(
                model=str(settings.ASSISTENTE_IA_MODEL or "gpt-5.6-sol"),
                instructions=EVAL_ROUTING_INSTRUCTIONS,
                input=str(case.get("prompt") or ""),
                tools=TOOL_DEFINITIONS,
                tool_choice="required",
                parallel_tool_calls=False,
                reasoning={"effort": "low"},
                text={"verbosity": "low"},
                max_output_tokens=800,
                store=False,
                safety_identifier=hashlib.sha256(
                    f"fortcordis-eval-admin:{execution.usuario_id}".encode("utf-8")
                ).hexdigest(),
            )
            last_response_id = str(response.id)
            selected_tools = [
                str(getattr(item, "name", ""))
                for item in list(response.output or [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not selected_tools:
                response_status = str(getattr(response, "status", "unknown") or "unknown")
                incomplete = getattr(response, "incomplete_details", None)
                incomplete_reason = str(getattr(incomplete, "reason", "") or "")
                error = f"Nenhuma ferramenta selecionada (status={response_status}"
                if incomplete_reason:
                    error += f", motivo={incomplete_reason}"
                error += ")."
        except Exception as exc:
            logger.exception("Falha em caso do laboratorio da Mente: %s", case.get("id"))
            error = str(exc)[:500]
        expected = str(case.get("expected_tool") or "")
        results.append({
            "id": case.get("id"),
            "case_type": "tool_routing",
            "expected_tool": expected,
            "selected_tools": selected_tools,
            "passed": bool(selected_tools and selected_tools[0] == expected and error is None),
            "error": error,
        })
    results.extend(_memory_contract_results(db))
    passed = sum(1 for item in results if item["passed"])
    execution.provider_response_id = last_response_id
    return {
        "dataset_version": dataset.get("version"),
        "model": str(settings.ASSISTENTE_IA_MODEL),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "score_percent": round((passed / len(results)) * 100, 1) if results else 0.0,
        "cases": results,
        "safety": "Somente roteamento e contratos determinísticos de memória foram verificados; nenhuma ferramenta ou escrita operacional foi executada.",
    }


def _run_readonly_kind(
    db: Session,
    user: User,
    *,
    kind: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if kind == "radar":
        return build_proactive_radar(db, user)
    if kind == "executive_summary":
        from app.services.assistente_ia_management import executive_summary

        return executive_summary(db, user)
    if kind in {"billing_trend", "overdue_debts"}:
        from app.services.assistente_ia_tools import (
            AssistenteIAToolContext,
            analisar_faturamento,
            relatorio_debitos_pendentes,
        )

        ctx = AssistenteIAToolContext(
            db=db,
            current_user=user,
            conversa=SimpleNamespace(id="readonly-mission"),
            request=None,
        )
        if kind == "billing_trend":
            return analisar_faturamento(
                ctx,
                meses=int(config.get("months") or 5),
                clinica=config.get("clinic"),
            )
        return relatorio_debitos_pendentes(
            ctx,
            clinica=str(config.get("clinic") or ""),
            somente_vencidos=bool(config.get("overdue_only", True)),
        )
    if kind == "clinic_360":
        from app.services.assistente_ia_tools import AssistenteIAToolContext, consultar_clinica_360

        return consultar_clinica_360(
            AssistenteIAToolContext(
                db=db,
                current_user=user,
                conversa=SimpleNamespace(id="readonly-mission"),
                request=None,
            ),
            clinica=str(config.get("clinic") or ""),
            periodo_dias=int(config.get("period_days") or 90),
        )
    raise RuntimeError("Tipo de execucao autonoma nao permitido.")


def _mark_semantic_error(db: Session, execution: AssistenteIAExecucao, error: str) -> None:
    if execution.tipo != "knowledge_index":
        return
    document_id = str(_json_loads(execution.entrada_json, {}).get("document_id") or "")
    document = db.query(AssistenteIAConhecimentoDocumento).filter(
        AssistenteIAConhecimentoDocumento.id == document_id
    ).first()
    if document:
        document.semantic_status = "error"
        document.semantic_error = error[:2000]
        db.add(document)


def process_execution(db: Session, execution: AssistenteIAExecucao) -> None:
    execution.status = "running"
    execution.started_at = _utc_now()
    execution.erro = None
    db.add(execution)
    db.commit()
    try:
        user = db.query(User).filter(User.id == execution.usuario_id).first()
        if user is None or not user.tem_papel("admin"):
            raise RuntimeError("Execucao interrompida: o proprietario nao possui mais papel admin.")
        if execution.tipo == "knowledge_index":
            result = _index_document(db, execution)
        elif execution.tipo == "eval_lab":
            result = _run_eval_lab(db, execution)
        else:
            result = _run_readonly_kind(
                db,
                user,
                kind=execution.tipo,
                config=_json_loads(execution.entrada_json, {}),
            )
        execution.status = "completed"
        execution.saida_json = _json_dumps(result)
    except Exception as exc:
        logger.exception("Falha em execucao autonoma da Mente id=%s", execution.id)
        db.rollback()
        execution = db.query(AssistenteIAExecucao).filter(AssistenteIAExecucao.id == execution.id).first()
        if execution is None:
            return
        execution.status = "error"
        execution.erro = str(exc)[:2000]
        _mark_semantic_error(db, execution, execution.erro)
        if execution.missao_id:
            mission = db.query(AssistenteIAMissao).filter(
                AssistenteIAMissao.id == execution.missao_id
            ).first()
            if mission and "papel admin" in execution.erro:
                mission.enabled = False
                mission.next_run_at = None
                db.add(mission)
    execution.finished_at = _utc_now()
    db.add(execution)
    db.commit()


def _try_pg_lock(db: Session, lock_key: int) -> bool:
    row = db.execute(text("SELECT pg_try_advisory_lock(:key) AS locked"), {"key": lock_key}).fetchone()
    return bool(row and (row._mapping.get("locked") if hasattr(row, "_mapping") else row[0]))


def _release_pg_lock(db: Session, lock_key: int) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})


def run_assistant_scheduler_due_once(*, limit: int = 20) -> dict[str, int]:
    if not _RUN_LOCK.acquire(blocking=False):
        return {"scheduled": 0, "processed": 0, "errors": 0}
    db = SessionLocal()
    lock_key = max(1, int(settings.ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_KEY or 80433002))
    pg_locked = False
    scheduled = 0
    processed = 0
    errors = 0
    try:
        bind = db.get_bind()
        if bind is None:
            return {"scheduled": 0, "processed": 0, "errors": 0}
        available_tables = set(inspect(bind).get_table_names())
        if not {"assistente_ia_missoes", "assistente_ia_execucoes"}.issubset(available_tables):
            logger.info("Scheduler da Mente aguardando a migration de autonomia segura.")
            return {"scheduled": 0, "processed": 0, "errors": 0}
        if bool(settings.ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_ENABLED) and _is_postgres(db):
            pg_locked = _try_pg_lock(db, lock_key)
            if not pg_locked:
                return {"scheduled": 0, "processed": 0, "errors": 0}
        now = _utc_now()
        stale_before = now - timedelta(minutes=30)
        stale_rows = db.query(AssistenteIAExecucao).filter(
            AssistenteIAExecucao.status == "running",
            AssistenteIAExecucao.started_at.isnot(None),
            AssistenteIAExecucao.started_at < stale_before,
        ).limit(50).all()
        for stale in stale_rows:
            stale.status = "queued"
            stale.started_at = None
            stale.erro = "Execucao retomada apos interrupcao do worker."
            if stale.tipo == "knowledge_index":
                document_id = str(_json_loads(stale.entrada_json, {}).get("document_id") or "")
                document = db.query(AssistenteIAConhecimentoDocumento).filter(
                    AssistenteIAConhecimentoDocumento.id == document_id
                ).first()
                if document:
                    document.semantic_status = "queued"
                    db.add(document)
            db.add(stale)
        if stale_rows:
            db.commit()
        queued_documents = db.query(AssistenteIAConhecimentoDocumento).filter(
            AssistenteIAConhecimentoDocumento.status == "active",
            AssistenteIAConhecimentoDocumento.semantic_enabled.is_(True),
            AssistenteIAConhecimentoDocumento.semantic_status == "queued",
        ).limit(50).all()
        for document in queued_documents:
            existing_index = db.query(AssistenteIAExecucao).filter(
                AssistenteIAExecucao.tipo == "knowledge_index",
                AssistenteIAExecucao.status.in_(["queued", "running"]),
                AssistenteIAExecucao.entrada_json.like(f'%"document_id": "{document.id}"%'),
            ).first()
            if existing_index is None:
                db.add(AssistenteIAExecucao(
                    id=str(uuid.uuid4()),
                    usuario_id=document.criado_por_id,
                    tipo="knowledge_index",
                    origem="recovery",
                    status="queued",
                    entrada_json=_json_dumps({"document_id": document.id}),
                ))
        if queued_documents:
            db.commit()
        due_query = db.query(AssistenteIAMissao).filter(
            AssistenteIAMissao.enabled.is_(True),
            AssistenteIAMissao.next_run_at.isnot(None),
            AssistenteIAMissao.next_run_at <= now,
        ).order_by(AssistenteIAMissao.next_run_at.asc())
        if _is_postgres(db):
            due_query = due_query.with_for_update(skip_locked=True)
        for mission in due_query.limit(max(1, min(50, limit))).all():
            db.add(AssistenteIAExecucao(
                id=str(uuid.uuid4()),
                usuario_id=mission.usuario_id,
                missao_id=mission.id,
                tipo=mission.tipo,
                origem="scheduled",
                status="queued",
                entrada_json=mission.configuracao_json or "{}",
            ))
            mission.last_run_at = now
            mission.next_run_at = calculate_next_run(
                recurrence=mission.recorrencia,
                local_time=mission.horario_local,
                weekdays=_json_loads(mission.dias_semana_json, []),
                after=now,
            )
            db.add(mission)
            scheduled += 1
        db.commit()

        while processed < max(1, limit):
            query = db.query(AssistenteIAExecucao).filter(
                AssistenteIAExecucao.status == "queued"
            ).order_by(AssistenteIAExecucao.created_at.asc())
            if _is_postgres(db):
                query = query.with_for_update(skip_locked=True)
            execution = query.first()
            if execution is None:
                break
            process_execution(db, execution)
            processed += 1
            db.refresh(execution)
            if execution.status == "error":
                errors += 1
        return {"scheduled": scheduled, "processed": processed, "errors": errors}
    finally:
        if pg_locked:
            try:
                _release_pg_lock(db, lock_key)
            except Exception:
                logger.exception("Falha ao liberar lock do scheduler da Mente.")
        db.close()
        _RUN_LOCK.release()


def _worker_poll_seconds() -> int:
    return max(10, min(300, int(settings.ASSISTENTE_IA_SCHEDULER_POLL_SECONDS or 30)))


def _worker_main() -> None:
    if not bool(settings.ASSISTENTE_IA_SCHEDULER_ENABLED):
        logger.info("Scheduler da Mente FortCordis desativado por configuracao.")
        return
    while not _WORKER_STOP_EVENT.is_set():
        try:
            run_assistant_scheduler_due_once(limit=20)
        except Exception:
            logger.exception("Falha no scheduler da Mente FortCordis.")
        if _WORKER_STOP_EVENT.wait(_worker_poll_seconds()):
            break


def get_assistant_scheduler_worker_runtime_state() -> dict[str, Any]:
    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        thread_alive = bool(thread and thread.is_alive())
        worker_started = thread is not None
    enabled = bool(settings.ASSISTENTE_IA_SCHEDULER_ENABLED)
    return {
        "enabled": enabled,
        "status": "disabled" if not enabled else "running" if thread_alive else "stopped",
        "thread_alive": thread_alive,
        "worker_started": worker_started,
        "poll_seconds": _worker_poll_seconds(),
        "distributed_lock": {
            "enabled": bool(settings.ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_ENABLED),
            "mode": "postgres_advisory_lock",
            "lock_key": int(settings.ASSISTENTE_IA_SCHEDULER_DISTRIBUTED_LOCK_KEY or 80433002),
        },
    }


def start_assistant_scheduler_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_STOP_EVENT.clear()
        _WORKER_THREAD = threading.Thread(
            target=_worker_main,
            name="assistente-ia-scheduler-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()


def shutdown_assistant_scheduler_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        if not thread:
            return
        _WORKER_STOP_EVENT.set()
    thread.join(timeout=5)
    with _WORKER_LOCK:
        _WORKER_THREAD = None
