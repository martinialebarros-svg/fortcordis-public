import re
import unicodedata
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalogo_exame import CatalogoExame

CUSTOM_CATALOGO_EXAME_PREFIX = "custom_exam_"


def slugify_catalogo_exame(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized or "exame"


def catalogo_exame_e_customizado(item: CatalogoExame) -> bool:
    return str(getattr(item, "codigo", "") or "").startswith(CUSTOM_CATALOGO_EXAME_PREFIX)


def gerar_codigo_unico_catalogo_exame(
    db: Session,
    nome: str,
    *,
    ignore_id: Optional[int] = None,
) -> str:
    base_code = f"{CUSTOM_CATALOGO_EXAME_PREFIX}{slugify_catalogo_exame(nome)}"
    candidate = base_code
    suffix = 2

    while True:
        query = db.query(CatalogoExame).filter(CatalogoExame.codigo == candidate)
        if ignore_id is not None:
            query = query.filter(CatalogoExame.id != ignore_id)
        if query.first() is None:
            return candidate
        candidate = f"{base_code}-{suffix}"
        suffix += 1


def obter_catalogo_exame_customizado(db: Session, exame_id: int) -> CatalogoExame:
    exame = db.query(CatalogoExame).filter(CatalogoExame.id == exame_id).first()
    if not exame:
        raise HTTPException(status_code=404, detail="Exame nao encontrado no catalogo.")
    if not catalogo_exame_e_customizado(exame):
        raise HTTPException(status_code=403, detail="Apenas exames customizados podem ser alterados.")
    return exame
