from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.user import User
from app.services.logistica_service import (
    normalizar_perfil,
    recalcular_matriz_completa,
    recalcular_matriz_para_clinica,
    resumir_cobertura_matriz_deslocamentos,
    resumir_google_maps_metricas,
    serialize_deslocamento,
    obter_ou_criar_deslocamento,
    upsert_deslocamento,
)

router = APIRouter()


class RecalcularMatrizPayload(BaseModel):
    clinica_id: Optional[int] = None
    perfis: Optional[List[str]] = None
    force_override: bool = False
    incluir_inativas: bool = False


class AjusteManualDeslocamentoPayload(BaseModel):
    origem_clinica_id: int = Field(..., ge=1)
    destino_clinica_id: int = Field(..., ge=1)
    perfil: str = "comercial"
    distancia_km: float = Field(default=0, ge=0)
    duracao_min: int = Field(..., ge=0)
    observacoes: Optional[str] = None


@router.get("/matriz")
def obter_matriz_deslocamento(
    perfil: str = "comercial",
    clinica_ids: Optional[List[int]] = Query(default=None),
    incluir_inativas: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perfil_norm = normalizar_perfil(perfil)

    query_clinicas = db.query(Clinica)
    if not incluir_inativas:
        query_clinicas = query_clinicas.filter(Clinica.ativo == True)
    if clinica_ids:
        ids_validos = [int(cid) for cid in clinica_ids if int(cid) > 0]
        if ids_validos:
            query_clinicas = query_clinicas.filter(Clinica.id.in_(ids_validos))

    clinicas = query_clinicas.order_by(Clinica.nome.asc()).all()
    ids = [int(c.id) for c in clinicas]

    if not ids:
        return {
            "perfil": perfil_norm,
            "total_clinicas": 0,
            "total_itens": 0,
            "clinicas": [],
            "items": [],
        }

    deslocamentos = (
        db.query(ClinicaDeslocamento)
        .filter(
            ClinicaDeslocamento.perfil == perfil_norm,
            ClinicaDeslocamento.origem_clinica_id.in_(ids),
            ClinicaDeslocamento.destino_clinica_id.in_(ids),
        )
        .all()
    )

    return {
        "perfil": perfil_norm,
        "total_clinicas": len(clinicas),
        "total_itens": len(deslocamentos),
        "clinicas": [{"id": c.id, "nome": c.nome} for c in clinicas],
        "items": [serialize_deslocamento(item) for item in deslocamentos],
    }


@router.get("/deslocamento")
def obter_deslocamento_entre_clinicas(
    origem_clinica_id: int = Query(..., ge=1),
    destino_clinica_id: int = Query(..., ge=1),
    perfil: str = "comercial",
    recalcular: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perfil_norm = normalizar_perfil(perfil)

    row = obter_ou_criar_deslocamento(
        db,
        origem_clinica_id=origem_clinica_id,
        destino_clinica_id=destino_clinica_id,
        perfil=perfil_norm,
        force_recalculate=recalcular,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Clinica de origem ou destino nao encontrada.")

    origem = db.query(Clinica).filter(Clinica.id == origem_clinica_id).first()
    destino = db.query(Clinica).filter(Clinica.id == destino_clinica_id).first()

    return {
        "origem": {"id": origem.id if origem else origem_clinica_id, "nome": origem.nome if origem else None},
        "destino": {"id": destino.id if destino else destino_clinica_id, "nome": destino.nome if destino else None},
        "item": serialize_deslocamento(row),
    }


@router.post("/recalcular")
def recalcular_matriz(
    payload: RecalcularMatrizPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.clinica_id:
        resultado = recalcular_matriz_para_clinica(
            db,
            clinica_id=payload.clinica_id,
            perfis=payload.perfis,
            force_override=payload.force_override,
            incluir_inativas=payload.incluir_inativas,
        )
    else:
        resultado = recalcular_matriz_completa(
            db,
            perfis=payload.perfis,
            force_override=payload.force_override,
            incluir_inativas=payload.incluir_inativas,
        )

    if not resultado.get("ok", False):
        raise HTTPException(status_code=404, detail="Clinica nao encontrada para recalculo.")
    return resultado


@router.get("/cobertura-matriz")
def obter_cobertura_matriz_deslocamentos(
    incluir_inativas: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumo somente leitura: linhas da matriz por fonte (Google vs heuristica) e geolocalizacao das clinicas."""
    return resumir_cobertura_matriz_deslocamentos(
        db,
        incluir_inativas=incluir_inativas,
    )


@router.get("/google-maps/resumo")
def obter_resumo_google_maps(
    dias: int = Query(default=30, ge=1, le=365),
    incluir_inativas: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return resumir_google_maps_metricas(
        db,
        dias=dias,
        incluir_inativas=incluir_inativas,
    )


@router.get("/google-maps/custos-quotas")
def obter_custos_quotas_google_maps(
    dias: int = Query(default=30, ge=1, le=365),
    incluir_inativas: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resumo = resumir_google_maps_metricas(
        db,
        dias=dias,
        incluir_inativas=incluir_inativas,
    )
    return {
        "window_days": resumo.get("window_days"),
        "total_api_calls": resumo.get("total_api_calls"),
        "cost_and_quotas": resumo.get("cost_and_quotas"),
    }


@router.put("/deslocamento/manual", status_code=status.HTTP_200_OK)
def ajustar_deslocamento_manual(
    payload: AjusteManualDeslocamentoPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    origem = db.query(Clinica).filter(Clinica.id == payload.origem_clinica_id).first()
    destino = db.query(Clinica).filter(Clinica.id == payload.destino_clinica_id).first()
    if not origem or not destino:
        raise HTTPException(status_code=404, detail="Clinica de origem ou destino nao encontrada.")

    row, _changed, _skipped = upsert_deslocamento(
        db,
        origem_clinica_id=payload.origem_clinica_id,
        destino_clinica_id=payload.destino_clinica_id,
        perfil=payload.perfil,
        distancia_km=payload.distancia_km,
        duracao_min=payload.duracao_min,
        fonte="manual",
        force_override=True,
    )
    row.manual_override = True
    row.observacoes = payload.observacoes
    db.commit()
    db.refresh(row)
    return {"item": serialize_deslocamento(row)}
