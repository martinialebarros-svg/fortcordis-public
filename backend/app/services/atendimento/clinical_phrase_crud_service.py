from datetime import datetime
from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.frase_atendimento_clinico import FraseAtendimentoClinico
from app.schemas.atendimento import ClinicalPhrasePayload
from app.services.clinical_phrase_service import VALID_SECOES, clinical_phrase_to_dict


def criar_frase_clinica(
    db: Session,
    payload: ClinicalPhrasePayload,
    *,
    created_by: int,
) -> Dict[str, Any]:
    secao = (payload.secao or "").strip()
    titulo = (payload.titulo or "").strip()
    texto = (payload.texto or "").strip()
    if secao not in VALID_SECOES:
        raise HTTPException(status_code=422, detail="Secao clinica invalida.")

    existente = (
        db.query(FraseAtendimentoClinico)
        .filter(
            FraseAtendimentoClinico.secao == secao,
            FraseAtendimentoClinico.titulo == titulo,
        )
        .first()
    )
    if existente:
        raise HTTPException(status_code=409, detail="Ja existe uma frase com esse titulo nessa secao.")

    frase = FraseAtendimentoClinico(
        secao=secao,
        titulo=titulo,
        texto=texto,
        ordem=payload.ordem or 0,
        ativo=1 if payload.ativo is None else int(payload.ativo),
        parametrizacao_origem="manual",
        created_by=created_by,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(frase)
    db.commit()
    db.refresh(frase)
    return clinical_phrase_to_dict(frase)


def atualizar_frase_clinica(db: Session, phrase_id: int, payload: ClinicalPhrasePayload) -> Dict[str, Any]:
    frase = db.query(FraseAtendimentoClinico).filter(FraseAtendimentoClinico.id == phrase_id).first()
    if not frase:
        raise HTTPException(status_code=404, detail="Frase clinica nao encontrada.")

    secao = (payload.secao or "").strip()
    titulo = (payload.titulo or "").strip()
    texto = (payload.texto or "").strip()
    if secao not in VALID_SECOES:
        raise HTTPException(status_code=422, detail="Secao clinica invalida.")

    duplicada = (
        db.query(FraseAtendimentoClinico)
        .filter(
            FraseAtendimentoClinico.id != phrase_id,
            FraseAtendimentoClinico.secao == secao,
            FraseAtendimentoClinico.titulo == titulo,
        )
        .first()
    )
    if duplicada:
        raise HTTPException(status_code=409, detail="Ja existe uma frase com esse titulo nessa secao.")

    frase.secao = secao
    frase.titulo = titulo
    frase.texto = texto
    frase.ordem = payload.ordem or 0
    if payload.ativo is not None:
        frase.ativo = int(payload.ativo)
    frase.updated_at = datetime.now()

    db.commit()
    db.refresh(frase)
    return clinical_phrase_to_dict(frase)


def desativar_frase_clinica(db: Session, phrase_id: int) -> Dict[str, Any]:
    frase = db.query(FraseAtendimentoClinico).filter(FraseAtendimentoClinico.id == phrase_id).first()
    if not frase:
        raise HTTPException(status_code=404, detail="Frase clinica nao encontrada.")

    frase.ativo = 0
    frase.updated_at = datetime.now()
    db.commit()
    return {"message": "Frase clinica desativada com sucesso."}


def restaurar_frase_clinica(db: Session, phrase_id: int) -> Dict[str, Any]:
    frase = db.query(FraseAtendimentoClinico).filter(FraseAtendimentoClinico.id == phrase_id).first()
    if not frase:
        raise HTTPException(status_code=404, detail="Frase clinica nao encontrada.")

    frase.ativo = 1
    frase.updated_at = datetime.now()
    db.commit()
    db.refresh(frase)
    return clinical_phrase_to_dict(frase)
