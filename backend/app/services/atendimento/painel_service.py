import re
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.schemas.atendimento import PainelExamePayload
from app.services.exam_catalog_service import painel_exame_to_dict

CUSTOM_PAINEL_EXAME_PREFIX = "custom_"


def slugify_painel_exame(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized or "painel"


def painel_exame_e_customizado(item: PainelExame) -> bool:
    return str(getattr(item, "codigo", "") or "").startswith(CUSTOM_PAINEL_EXAME_PREFIX)


def gerar_codigo_unico_painel_exame(db: Session, nome: str, *, ignore_id: Optional[int] = None) -> str:
    base_code = f"{CUSTOM_PAINEL_EXAME_PREFIX}{slugify_painel_exame(nome)}"
    candidate = base_code
    suffix = 2

    while True:
        query = db.query(PainelExame).filter(PainelExame.codigo == candidate)
        if ignore_id is not None:
            query = query.filter(PainelExame.id != ignore_id)
        if query.first() is None:
            return candidate
        candidate = f"{base_code}-{suffix}"
        suffix += 1


def carregar_itens_painel_exame(db: Session, painel_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(PainelExameItem, CatalogoExame)
        .join(CatalogoExame, CatalogoExame.id == PainelExameItem.catalogo_exame_id)
        .filter(PainelExameItem.painel_id == painel_id)
        .order_by(PainelExameItem.ordem.asc(), CatalogoExame.nome.asc())
        .all()
    )
    return [
        {
            "catalogo_exame_id": exame.id,
            "codigo": exame.codigo,
            "nome": exame.nome,
            "categoria": exame.categoria,
            "subcategoria": exame.subcategoria or "",
            "prioridade_padrao": exame.prioridade_padrao or "Rotina",
            "valor_padrao": exame.valor_padrao or 0,
            "preparo": exame.preparo or "",
            "observacoes_padrao": exame.observacoes_padrao or "",
            "ordem": item.ordem or 0,
        }
        for item, exame in rows
    ]


def serializar_painel_exame_com_itens(db: Session, painel: PainelExame) -> Dict[str, Any]:
    return painel_exame_to_dict(painel, carregar_itens_painel_exame(db, painel.id))


def resolver_ids_catalogo_exames(db: Session, payload: PainelExamePayload) -> List[int]:
    if not payload.itens:
        raise HTTPException(status_code=422, detail="Selecione pelo menos um exame para o painel.")

    ordered_ids: List[int] = []
    seen_ids = set()
    for item in payload.itens:
        exame_id = int(item.catalogo_exame_id)
        if exame_id in seen_ids:
            continue
        seen_ids.add(exame_id)
        ordered_ids.append(exame_id)

    exames_existentes = (
        db.query(CatalogoExame.id)
        .filter(CatalogoExame.id.in_(ordered_ids), CatalogoExame.ativo == 1)
        .all()
    )
    existing_ids = {row[0] for row in exames_existentes}
    missing_ids = [exame_id for exame_id in ordered_ids if exame_id not in existing_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Exame(s) nao encontrado(s) no catalogo: {', '.join(map(str, missing_ids))}.",
        )
    return ordered_ids


def obter_painel_exame_customizado(db: Session, painel_id: int) -> PainelExame:
    painel = db.query(PainelExame).filter(PainelExame.id == painel_id).first()
    if not painel:
        raise HTTPException(status_code=404, detail="Painel de exames nao encontrado.")
    if not painel_exame_e_customizado(painel):
        raise HTTPException(status_code=403, detail="Apenas paineis customizados podem ser alterados.")
    return painel


def substituir_itens_painel_exame(db: Session, painel_id: int, ordered_exam_ids: List[int]) -> None:
    db.query(PainelExameItem).filter(PainelExameItem.painel_id == painel_id).delete(synchronize_session=False)
    for ordem, exame_id in enumerate(ordered_exam_ids):
        db.add(
            PainelExameItem(
                painel_id=painel_id,
                catalogo_exame_id=exame_id,
                ordem=ordem,
            )
        )
