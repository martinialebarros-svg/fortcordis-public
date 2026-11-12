from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import require_papel
from app.db.database import get_db
from app.models.user import User
from app.services.tutor_mesclagem_reversao_service import obter_previa_reversao, reverter_mesclagem

router = APIRouter()


class ReversaoPayload(BaseModel):
    token_previa: str = Field(min_length=64, max_length=64)
    motivo: str = Field(min_length=5, max_length=2000)
    confirmar: bool = False
    chave_operacao: str | None = Field(default=None, min_length=8, max_length=128)


@router.post("/mesclagens/{mesclagem_id}/reversao/previa")
def previa_reversao(mesclagem_id: int, db: Session = Depends(get_db),
                   current_user: User = Depends(require_papel("admin"))):
    return obter_previa_reversao(db, mesclagem_id)


@router.post("/mesclagens/{mesclagem_id}/reversao")
def confirmar_reversao(mesclagem_id: int, payload: ReversaoPayload, db: Session = Depends(get_db),
                      current_user: User = Depends(require_papel("admin"))):
    return reverter_mesclagem(db, mesclagem_id, payload, current_user)
