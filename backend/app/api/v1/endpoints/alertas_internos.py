from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.alerta_interno import AlertaInterno
from app.models.user import User
from app.schemas.alerta_interno import (
    AlertaInternoAckResponse,
    AlertaInternoListResponse,
    AlertaInternoResponse,
)

router = APIRouter()


def _serialize(alerta: AlertaInterno) -> AlertaInternoResponse:
    return AlertaInternoResponse(
        id=alerta.id,
        tipo=alerta.tipo,
        nivel=alerta.nivel,
        titulo=alerta.titulo,
        mensagem=alerta.mensagem,
        entidade_tipo=alerta.entidade_tipo,
        entidade_id=alerta.entidade_id,
        clinica_id=alerta.clinica_id,
        lido=bool(alerta.lido),
        lido_por_nome=alerta.lido_por_nome,
        lido_em=alerta.lido_em,
        criado_em=alerta.criado_em,
    )


@router.get("", response_model=AlertaInternoListResponse)
def listar_alertas_internos(
    incluir_lidos: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista alertas internos. Visivel para qualquer usuario interno autenticado,
    de proposito (o objetivo e minimizar a chance de ninguem ver um aviso, nao
    restringir por papel)."""
    total_nao_lidos = int(
        db.query(func.count(AlertaInterno.id)).filter(AlertaInterno.lido.is_(False)).scalar() or 0
    )

    query = db.query(AlertaInterno)
    if not incluir_lidos:
        query = query.filter(AlertaInterno.lido.is_(False))
    itens = query.order_by(AlertaInterno.criado_em.desc(), AlertaInterno.id.desc()).limit(limit).all()

    return AlertaInternoListResponse(
        total_nao_lidos=total_nao_lidos,
        items=[_serialize(alerta) for alerta in itens],
    )


@router.patch("/{alerta_id}/marcar-lido", response_model=AlertaInternoResponse)
def marcar_alerta_interno_lido(
    alerta_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alerta = db.query(AlertaInterno).filter(AlertaInterno.id == alerta_id).first()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta nao encontrado.")

    if not alerta.lido:
        alerta.lido = True
        alerta.lido_por_id = current_user.id
        alerta.lido_por_nome = current_user.nome
        alerta.lido_em = datetime.utcnow()
        db.commit()
        db.refresh(alerta)

    return _serialize(alerta)


@router.post("/marcar-todos-lidos", response_model=AlertaInternoAckResponse)
def marcar_todos_alertas_internos_lidos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agora = datetime.utcnow()
    db.query(AlertaInterno).filter(AlertaInterno.lido.is_(False)).update(
        {
            "lido": True,
            "lido_por_id": current_user.id,
            "lido_por_nome": current_user.nome,
            "lido_em": agora,
        },
        synchronize_session=False,
    )
    db.commit()
    return AlertaInternoAckResponse()
