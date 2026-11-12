"""Historico clinico restrito aos recursos do atendimento solicitado."""
import json
from datetime import timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, or_
from sqlalchemy.orm import Session

from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento, PrescricaoClinica
from app.models.auditoria_evento import AuditoriaEvento


ACOES_EDICAO = (
    "ATENDIMENTO_CONTEUDO_CLINICO_ATUALIZADO",
    "DOCUMENTO_ATENDIMENTO_ATUALIZADO",
    "EDITAR_RECEITA_EMITIDA",
    "PRESCRICAO_ATUALIZADA",
)


def listar_historico_edicoes(
    db: Session, atendimento_id: int, *, documento_id: Optional[int] = None,
    skip: int = 0, limit: int = 50,
) -> dict:
    if not db.query(AtendimentoClinico.id).filter(AtendimentoClinico.id == atendimento_id).first():
        raise HTTPException(status_code=404, detail="Atendimento nao encontrado.")
    documentos = db.query(cast(DocumentoAtendimento.id, String)).filter(
        DocumentoAtendimento.atendimento_id == atendimento_id,
    )
    if documento_id is not None:
        if not db.query(DocumentoAtendimento.id).filter(
            DocumentoAtendimento.atendimento_id == atendimento_id,
            DocumentoAtendimento.id == documento_id,
        ).first():
            raise HTTPException(status_code=404, detail="Documento do atendimento nao encontrado.")
        documentos = documentos.filter(DocumentoAtendimento.id == documento_id)
    escopo = [and_(AuditoriaEvento.entidade == "documento_atendimento",
                   AuditoriaEvento.entidade_id.in_(documentos))]
    if documento_id is None:
        prescricoes = db.query(cast(PrescricaoClinica.id, String)).filter(
            PrescricaoClinica.atendimento_id == atendimento_id,
        )
        escopo.extend([
            and_(AuditoriaEvento.entidade == "atendimento_clinico",
                 AuditoriaEvento.entidade_id == str(atendimento_id)),
            and_(AuditoriaEvento.entidade == "prescricao_clinica",
                 AuditoriaEvento.entidade_id.in_(prescricoes)),
        ])
    query = db.query(AuditoriaEvento).filter(
        AuditoriaEvento.modulo == "atendimento",
        AuditoriaEvento.acao.in_(ACOES_EDICAO), or_(*escopo),
    )
    total = query.count()
    eventos = query.order_by(AuditoriaEvento.id.desc()).offset(skip).limit(limit).all()
    items = []
    for evento in eventos:
        try:
            detalhes = json.loads(evento.detalhes_json or "{}")
        except (ValueError, TypeError):
            detalhes = {}
        alteracoes = detalhes.get("alteracoes", {}) if isinstance(detalhes, dict) else {}
        instante = evento.created_at
        if instante and instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        items.append({
            "id": evento.id, "created_at": instante.isoformat() if instante else None,
            "usuario_id": evento.usuario_id, "usuario_nome": evento.usuario_nome or "",
            "entidade": evento.entidade, "entidade_id": evento.entidade_id,
            "acao": evento.acao, "descricao": evento.descricao or "",
            "alteracoes": alteracoes if isinstance(alteracoes, dict) else {},
        })
    return {"items": items, "total": total, "skip": skip, "limit": limit}
