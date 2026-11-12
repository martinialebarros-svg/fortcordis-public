from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import require_papel
from app.db.database import get_db
from app.models.paciente import Paciente
from app.models.paciente_mesclagem import PacienteMesclagem
from app.models.user import User
from app.services import paciente_mesclagem_service as service

router = APIRouter(prefix="/mesclagens")
admin = require_papel("admin")


class Dupla(BaseModel):
    principal_id: int = Field(gt=0)
    secundario_id: int = Field(gt=0)


class Confirmacao(Dupla):
    token_previa: str = Field(pattern=r"^[a-f0-9]{64}$")
    motivo: str = Field(min_length=5, max_length=2000)
    confirmar: StrictBool


@router.get("")
def listar(estado: Literal["pendente", "historico"] = "pendente",
           paciente_id: int | None = Query(default=None, gt=0),
           offset: int = Query(default=0, ge=0),
           db: Session = Depends(get_db), _user: User = Depends(admin)):
    q = db.query(PacienteMesclagem)
    if estado == "pendente":
        q = q.filter(PacienteMesclagem.estado == "pendente")
    else:
        q = q.filter(PacienteMesclagem.estado != "pendente")
    if paciente_id:
        q = q.filter(or_(PacienteMesclagem.principal_id == paciente_id, PacienteMesclagem.secundario_id == paciente_id))
    items = q.order_by(PacienteMesclagem.id.desc()).offset(offset).limit(51).all()
    ids = {id_ for r in items[:50] for id_ in (r.principal_id, r.secundario_id)}
    nomes = {id_: nome for id_, nome in db.query(Paciente.id, Paciente.nome).filter(Paciente.id.in_(ids))} if ids else {}
    return {"items": [service.serializar(r, nomes) for r in items[:50]], "tem_mais": len(items) > 50}


@router.post("/previa")
def gerar_previa(payload: Dupla, db: Session = Depends(get_db), _user: User = Depends(admin)):
    return service.previa(db, payload.principal_id, payload.secundario_id)


@router.post("/adiar")
def revisar_depois(payload: Dupla, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.adiar(db, payload.principal_id, payload.secundario_id, user)


@router.post("/confirmar")
def confirmar(payload: Confirmacao, db: Session = Depends(get_db), user: User = Depends(admin)):
    return service.concluir(db, payload.principal_id, payload.secundario_id, payload.token_previa,
                            payload.motivo, payload.confirmar, user)
