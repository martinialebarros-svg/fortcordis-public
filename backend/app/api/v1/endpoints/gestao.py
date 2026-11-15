"""Painel administrativo. POST calcula sem gravar; só PUT salva premissas."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.clinica import Clinica
from app.models.gestao import GestaoPremissas
from app.models.user import User
from app.schemas.gestao import ConsultaGestao, PremissasGestao, SalvarPremissasGestao
from app.services.auditoria_service import registrar_auditoria
from app.services.gestao_agenda import build_agenda_metrics
from app.services.gestao_financeira import build_financial_metrics

router = APIRouter()
LOCAL_ZONE = ZoneInfo("America/Fortaleza")


def _admin(user: User) -> None:
    if not user.tem_papel("admin"):
        raise HTTPException(status_code=403, detail="O painel de gestão é exclusivo de administradores.")


def _serialize(row: GestaoPremissas | None) -> dict:
    if row is None:
        return {"revision": 0, "contexto": None, "values": PremissasGestao().model_dump(mode="json"),
                "updated_at": None, "updated_by_id": None}
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return {"revision": row.revision, "contexto": json.loads(row.contexto_json),
            "values": json.loads(row.values_json), "updated_at": updated.isoformat(),
            "updated_by_id": row.updated_by_id}


@router.get("/premissas")
def obter_premissas(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _admin(current_user)
    try:
        return _serialize(db.get(GestaoPremissas, 1))
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Premissas indisponíveis. Verifique a instalação e tente novamente.") from None


@router.put("/premissas")
def salvar_premissas(payload: SalvarPremissasGestao, request: Request,
                     db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _admin(current_user)
    now = datetime.now(timezone.utc)
    fields = {"revision": payload.expected_revision + 1,
              "contexto_json": payload.contexto.model_dump_json(),
              "values_json": payload.values.model_dump_json(),
              "updated_at": now, "updated_by_id": current_user.id}
    try:
        if payload.expected_revision == 0:
            db.add(GestaoPremissas(id=1, **fields))
            db.flush()
        else:
            updated = db.query(GestaoPremissas).filter(
                GestaoPremissas.id == 1, GestaoPremissas.revision == payload.expected_revision,
            ).update(fields, synchronize_session=False)
            if updated != 1:
                db.rollback()
                raise HTTPException(status_code=409, detail="As premissas foram alteradas por outro administrador. Recarregue antes de salvar.")
        registrar_auditoria(current_user=current_user, modulo="gestao", entidade="premissas",
                            entidade_id=1, acao="ATUALIZAR_PREMISSAS",
                            descricao="Administrador salvou premissas do painel de gestão.",
                            detalhes={"revision": fields["revision"],
                                      "contexto": payload.contexto.model_dump(mode="json"),
                                      "values": payload.values.model_dump(mode="json")},
                            request=request, db=db)
        db.commit()
        db.expire_all()
        return _serialize(db.get(GestaoPremissas, 1))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existem premissas salvas. Recarregue antes de salvar.") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Não foi possível salvar as premissas. Nenhum registro operacional foi alterado.") from None


@router.post("/painel")
def consultar_painel(payload: ConsultaGestao, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    _admin(current_user)
    now = datetime.now(LOCAL_ZONE)
    days = (payload.data_fim - payload.data_inicio).days + 1
    previous_end = payload.data_inicio - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)

    def calculate(start, end, assumptions):
        return {**build_financial_metrics(db, start, end, payload.clinica_id, payload.regiao, assumptions, now.date()),
                **build_agenda_metrics(db, start, end, payload.clinica_id, payload.regiao, now.date())}

    try:
        with db.no_autoflush:
            clinics = db.query(Clinica.id, Clinica.nome, Clinica.ativo, Clinica.regiao_operacional, Clinica.cidade).order_by(Clinica.nome, Clinica.id).all()
            current = calculate(payload.data_inicio, payload.data_fim, payload.premissas.model_dump(mode="json"))
            previous = calculate(previous_start, previous_end, {})
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Os dados de gestão estão indisponíveis. Tente atualizar o painel novamente.") from None
    return {
        "atualizado_em": now.isoformat(),
        "periodo": {"inicio": payload.data_inicio, "fim": payload.data_fim,
                    "anterior_inicio": previous_start, "anterior_fim": previous_end},
        "filtros": {"clinicas": [{"id": c.id, "nome": c.nome, "ativo": c.ativo} for c in clinics],
                    "regioes": sorted({str(c.regiao_operacional or "").strip() or str(c.cidade or "").strip() or "Não informada" for c in clinics} | {"Não informada"})},
        "atual": current, "anterior": previous,
        "comparacao": "Mesmo número de dias imediatamente anterior. Premissas de totais, horas e saldo não são extrapoladas ao período anterior.",
        "premissas_aplicadas": payload.premissas.model_dump(mode="json"),
    }
