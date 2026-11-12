from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.atendimento_clinico import DocumentoAtendimentoTemplate
from app.schemas.atendimento import DocumentoTemplatePayload


def _to_iso(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.isoformat()


def serializar_template_documento(template: DocumentoAtendimentoTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "nome": template.nome,
        "tipo": template.tipo or "documento",
        "titulo_padrao": template.titulo_padrao or "",
        "corpo_template": template.corpo_template or "",
        "ativo": template.ativo,
        "ordem": template.ordem or 0,
        "criado_por_id": template.criado_por_id,
        "criado_por_nome": template.criado_por_nome or "",
        "created_at": _to_iso(template.created_at),
        "updated_at": _to_iso(template.updated_at),
    }


def obter_template_documento_ou_404(db: Session, template_id: int) -> DocumentoAtendimentoTemplate:
    template = db.query(DocumentoAtendimentoTemplate).filter(DocumentoAtendimentoTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template de documento nao encontrado.")
    return template


def listar_templates_documento(
    db: Session,
    *,
    include_inactive: int = 0,
    search: Optional[str] = None,
) -> dict[str, list[dict[str, Any]]]:
    query = db.query(DocumentoAtendimentoTemplate)
    if not include_inactive:
        query = query.filter(DocumentoAtendimentoTemplate.ativo == 1)
    if search:
        termo = f"%{search.strip()}%"
        query = query.filter(
            or_(
                DocumentoAtendimentoTemplate.nome.ilike(termo),
                DocumentoAtendimentoTemplate.tipo.ilike(termo),
                DocumentoAtendimentoTemplate.titulo_padrao.ilike(termo),
            )
        )

    templates = (
        query.order_by(
            DocumentoAtendimentoTemplate.ordem.asc(),
            DocumentoAtendimentoTemplate.nome.asc(),
        )
        .all()
    )
    return {"templates": [serializar_template_documento(template) for template in templates]}


def criar_template_documento(
    db: Session,
    payload: DocumentoTemplatePayload,
    *,
    criado_por_id: int,
    criado_por_nome: str,
) -> dict[str, Any]:
    nome = (payload.nome or "").strip()
    titulo = (payload.titulo_padrao or "").strip()
    corpo = (payload.corpo_template or "").strip()
    if not nome or not titulo or not corpo:
        raise HTTPException(status_code=422, detail="Preencha nome, titulo e corpo do template.")

    existente = (
        db.query(DocumentoAtendimentoTemplate)
        .filter(DocumentoAtendimentoTemplate.nome == nome)
        .first()
    )
    if existente:
        raise HTTPException(status_code=409, detail="Ja existe um template com esse nome.")

    template = DocumentoAtendimentoTemplate(
        nome=nome,
        tipo=(payload.tipo or "documento").strip() or "documento",
        titulo_padrao=titulo,
        corpo_template=corpo,
        ativo=1 if payload.ativo is None else int(payload.ativo),
        ordem=payload.ordem or 0,
        criado_por_id=criado_por_id,
        criado_por_nome=criado_por_nome,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return serializar_template_documento(template)


def atualizar_template_documento(
    db: Session,
    template_id: int,
    payload: DocumentoTemplatePayload,
) -> dict[str, Any]:
    template = obter_template_documento_ou_404(db, template_id)
    nome = (payload.nome or "").strip()
    titulo = (payload.titulo_padrao or "").strip()
    corpo = (payload.corpo_template or "").strip()
    if not nome or not titulo or not corpo:
        raise HTTPException(status_code=422, detail="Preencha nome, titulo e corpo do template.")

    duplicado = (
        db.query(DocumentoAtendimentoTemplate)
        .filter(
            DocumentoAtendimentoTemplate.id != template_id,
            DocumentoAtendimentoTemplate.nome == nome,
        )
        .first()
    )
    if duplicado:
        raise HTTPException(status_code=409, detail="Ja existe um template com esse nome.")

    template.nome = nome
    template.tipo = (payload.tipo or "documento").strip() or "documento"
    template.titulo_padrao = titulo
    template.corpo_template = corpo
    template.ativo = 1 if payload.ativo is None else int(payload.ativo)
    template.ordem = payload.ordem or 0
    template.updated_at = datetime.now()

    db.commit()
    db.refresh(template)
    return serializar_template_documento(template)


def desativar_template_documento(db: Session, template_id: int) -> dict[str, Any]:
    template = obter_template_documento_ou_404(db, template_id)
    template.ativo = 0
    template.updated_at = datetime.now()
    db.commit()
    return {"message": "Template de documento desativado com sucesso.", "id": template_id}


def restaurar_template_documento(db: Session, template_id: int) -> dict[str, Any]:
    template = obter_template_documento_ou_404(db, template_id)
    template.ativo = 1
    template.updated_at = datetime.now()
    db.commit()
    db.refresh(template)
    return serializar_template_documento(template)
