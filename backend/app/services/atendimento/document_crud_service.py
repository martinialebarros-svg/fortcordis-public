"""Documentos sao recursos independentes; salvar o atendimento nao os substitui."""
from datetime import datetime, timezone
import hashlib
import json
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.user import User
from app.schemas.atendimento import DocumentoAtendimentoUpdatePayload
from app.services.auditoria_service import _request_meta

_CAMPOS_DOCUMENTO_AUDITAVEIS = ("titulo", "corpo", "status")


def agora_documento() -> datetime:
    # As colunas legadas sao timestamp WITHOUT time zone. O servidor de
    # producao gravava UTC; conservar a representacao e explicitar UTC na API.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _snapshot_documento(documento: DocumentoAtendimento) -> dict:
    return {campo: getattr(documento, campo) or ("rascunho" if campo == "status" else "")
            for campo in _CAMPOS_DOCUMENTO_AUDITAVEIS}


def _to_iso(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def versao_documento(documento: DocumentoAtendimento) -> str:
    snapshot = {**_snapshot_documento(documento), "id": documento.id,
                "atendimento_id": documento.atendimento_id, "template_id": documento.template_id,
                "updated_at": _to_iso(documento.updated_at), "emitido_at": _to_iso(documento.emitido_at)}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def auditar_documento(db: Session, documento: DocumentoAtendimento, acao: str, *,
                      current_user: User, request: Optional[Request] = None,
                      detalhes: Optional[dict] = None) -> None:
    """Mesma transacao do documento: falha na auditoria impede a alteracao."""
    db.flush()
    ip, rota, metodo = _request_meta(request)
    db.add(AuditoriaEvento(
        usuario_id=getattr(current_user, "id", None),
        usuario_nome=getattr(current_user, "nome", None),
        usuario_email=getattr(current_user, "email", None),
        modulo="atendimento", entidade="documento_atendimento", entidade_id=str(documento.id),
        acao=acao, descricao=f"Documento clinico #{documento.id}: {acao}.",
        detalhes_json=json.dumps({"atendimento_id": documento.atendimento_id,
                                  "versao": versao_documento(documento),
                                  **(detalhes or {})}, ensure_ascii=False, default=str),
        ip_origem=ip, rota=rota, metodo=metodo, created_at=datetime.now(timezone.utc),
    ))


def serializar_documento_atendimento(documento: DocumentoAtendimento) -> dict:
    return {
        "id": documento.id, "atendimento_id": documento.atendimento_id,
        "template_id": documento.template_id, **_snapshot_documento(documento),
        "criado_por_id": documento.criado_por_id,
        "criado_por_nome": documento.criado_por_nome or "",
        "emitido_at": _to_iso(documento.emitido_at),
        "created_at": _to_iso(documento.created_at),
        "updated_at": _to_iso(documento.updated_at), "versao": versao_documento(documento),
    }


def obter_documento_atendimento_ou_404(db: Session, atendimento_id: int, documento_id: int,
                                      *, bloquear: bool = False) -> DocumentoAtendimento:
    query = db.query(DocumentoAtendimento).filter(
        DocumentoAtendimento.id == documento_id, DocumentoAtendimento.atendimento_id == atendimento_id)
    if bloquear:
        # PostgreSQL serializa update/archive/PDF. Releitura vence o identity map
        # de uma sessao que tenha carregado o documento antes do lock.
        query = query.populate_existing().with_for_update()
    documento = query.first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento do atendimento nao encontrado. Seu texto local foi preservado; recarregue a lista antes de continuar.")
    return documento


def validar_versao_documento(documento: DocumentoAtendimento, versao: Optional[str]) -> None:
    if not versao:
        raise HTTPException(status_code=428, detail="Recarregue o documento antes de alterar ou gerar o PDF. Esta sessao nao informou a versao.")
    if versao != versao_documento(documento):
        raise HTTPException(status_code=409, detail="Documento alterado em outra sessao. Seu texto local foi preservado; recarregue e compare antes de salvar.")


def validar_documento_ativo(documento: DocumentoAtendimento) -> None:
    if documento.status == "arquivado":
        raise HTTPException(status_code=409, detail="Documento arquivado. Restaure-o na lista antes de editar ou gerar PDF.")


def listar_documentos_atendimento(db: Session, atendimento_id: int) -> dict:
    documentos = (db.query(DocumentoAtendimento).filter(DocumentoAtendimento.atendimento_id == atendimento_id)
                  .order_by(DocumentoAtendimento.updated_at.desc(), DocumentoAtendimento.created_at.desc(), DocumentoAtendimento.id.desc()).all())
    return {"documentos": [serializar_documento_atendimento(d) for d in documentos]}


def atualizar_documento_atendimento(db: Session, atendimento: AtendimentoClinico, atendimento_id: int,
                                    documento_id: int, payload: DocumentoAtendimentoUpdatePayload, *,
                                    current_user: User, request: Optional[Request] = None) -> dict:
    documento = obter_documento_atendimento_ou_404(db, atendimento_id, documento_id, bloquear=True)
    validar_versao_documento(documento, payload.versao)
    validar_documento_ativo(documento)
    antes = _snapshot_documento(documento)
    data = payload.model_dump(exclude_unset=True)
    for campo in ("titulo", "corpo"):
        if campo in data:
            valor = (data[campo] or "").strip()
            if not valor:
                raise HTTPException(status_code=422, detail=f"{campo.title()} do documento e obrigatorio.")
            setattr(documento, campo, valor)
    # Status e derivado por emitir/arquivar/restaurar. Um PUT antigo nao pode
    # reviver um arquivo, nem fabricar uma emissao sem PDF.
    if data.get("status") is not None and data["status"] != documento.status:
        raise HTTPException(status_code=422, detail="Use as acoes de PDF, arquivar ou restaurar para alterar o status.")
    depois = _snapshot_documento(documento)
    alteracoes = {c: {"antes": antes[c], "depois": depois[c]} for c in _CAMPOS_DOCUMENTO_AUDITAVEIS if antes[c] != depois[c]}
    if alteracoes:
        documento.updated_at = agora_documento()
        atendimento.updated_at = agora_documento()
        auditar_documento(db, documento, "DOCUMENTO_ATENDIMENTO_ATUALIZADO", current_user=current_user,
                          request=request, detalhes={"alteracoes": alteracoes})
    db.commit()
    db.refresh(documento)
    return serializar_documento_atendimento(documento)


def excluir_documento_atendimento(db: Session, atendimento_id: int, documento_id: int, *,
                                  current_user: User, request: Optional[Request] = None,
                                  versao: Optional[str] = None) -> dict:
    documento = obter_documento_atendimento_ou_404(db, atendimento_id, documento_id, bloquear=True)
    validar_versao_documento(documento, versao)
    validar_documento_ativo(documento)
    antes = _snapshot_documento(documento)
    documento.status = "arquivado"
    documento.updated_at = agora_documento()
    auditar_documento(db, documento, "DOCUMENTO_ATENDIMENTO_ARQUIVADO", current_user=current_user,
                      request=request, detalhes={"conteudo_preservado": antes})
    db.commit()
    db.refresh(documento)
    return serializar_documento_atendimento(documento)


def restaurar_documento_atendimento(db: Session, atendimento_id: int, documento_id: int, *,
                                    current_user: User, versao: Optional[str],
                                    request: Optional[Request] = None) -> dict:
    documento = obter_documento_atendimento_ou_404(db, atendimento_id, documento_id, bloquear=True)
    validar_versao_documento(documento, versao)
    if documento.status != "arquivado":
        raise HTTPException(status_code=409, detail="Documento nao esta arquivado.")
    documento.status = "emitido" if documento.emitido_at else "rascunho"
    documento.updated_at = agora_documento()
    auditar_documento(db, documento, "DOCUMENTO_ATENDIMENTO_RESTAURADO", current_user=current_user, request=request)
    db.commit()
    db.refresh(documento)
    return serializar_documento_atendimento(documento)
