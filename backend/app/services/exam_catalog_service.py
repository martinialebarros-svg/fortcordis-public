from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, or_
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.services.atendimento.catalogo_exame_custom_service import catalogo_exame_e_customizado

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CATALOGO_EXAMES_FILE = DATA_DIR / "catalogo_exames.json"


def _load_json(filepath: Path, default: Any = None) -> Any:
    if not filepath.exists():
        return default
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _table_exists(db: Session, table_name: str) -> bool:
    inspector = inspect(db.bind)
    return table_name in inspector.get_table_names()


def _catalog_tables_ready(db: Session) -> bool:
    return all(
        _table_exists(db, table_name)
        for table_name in ("catalogo_exames", "painel_exames", "painel_exames_itens")
    )


def _parse_sinonimos(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def catalogo_exame_to_dict(item: CatalogoExame) -> Dict[str, Any]:
    return {
        "id": item.id,
        "codigo": item.codigo,
        "nome": item.nome,
        "categoria": item.categoria,
        "subcategoria": item.subcategoria or "",
        "especie_alvo": item.especie_alvo or "",
        "prioridade_padrao": item.prioridade_padrao or "Rotina",
        "valor_padrao": item.valor_padrao or 0,
        "preparo": item.preparo or "",
        "observacoes_padrao": item.observacoes_padrao or "",
        "sinonimos": _parse_sinonimos(item.sinonimos_json),
        "clinic_id": item.clinic_id,
        "ativo": item.ativo,
        "customizado": catalogo_exame_e_customizado(item),
    }


def painel_exame_to_dict(item: PainelExame, itens: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "id": item.id,
        "codigo": item.codigo,
        "nome": item.nome,
        "categoria": item.categoria or "",
        "especie_alvo": item.especie_alvo or "",
        "observacoes": item.observacoes or "",
        "clinic_id": item.clinic_id,
        "ativo": item.ativo,
        "itens": itens or [],
    }


def ensure_exam_catalog_seeded(db: Session) -> Dict[str, Any]:
    report = {
        "tables_ready": _catalog_tables_ready(db),
        "seeded": False,
        "seeded_exames": 0,
        "seeded_paineis": 0,
        "seeded_itens": 0,
        "db_exames": 0,
        "db_paineis": 0,
        "json_exames": 0,
        "json_paineis": 0,
        "error": None,
    }
    if not report["tables_ready"]:
        return report

    try:
        report["db_exames"] = db.query(CatalogoExame).count()
        report["db_paineis"] = db.query(PainelExame).count()
    except (ProgrammingError, OperationalError):
        db.rollback()
        report["tables_ready"] = False
        return report

    data = _load_json(CATALOGO_EXAMES_FILE, {"version": "1.0", "exames": [], "paineis": []})
    exames_seed = data.get("exames", []) if isinstance(data, dict) else []
    paineis_seed = data.get("paineis", []) if isinstance(data, dict) else []
    if not isinstance(exames_seed, list):
        exames_seed = []
    if not isinstance(paineis_seed, list):
        paineis_seed = []

    report["json_exames"] = len(exames_seed)
    report["json_paineis"] = len(paineis_seed)
    if not exames_seed and not paineis_seed:
        return report

    existing_exames = {
        (item.codigo or "").strip(): item
        for item in db.query(CatalogoExame).all()
        if (item.codigo or "").strip()
    }
    existing_paineis = {
        (item.codigo or "").strip(): item
        for item in db.query(PainelExame).all()
        if (item.codigo or "").strip()
    }

    for item in exames_seed:
        codigo = str(item.get("codigo") or "").strip()
        nome = str(item.get("nome") or "").strip()
        categoria = str(item.get("categoria") or "").strip()
        if not codigo or not nome or not categoria or codigo in existing_exames:
            continue

        registro = CatalogoExame(
            codigo=codigo,
            nome=nome,
            categoria=categoria,
            subcategoria=str(item.get("subcategoria") or "").strip() or None,
            especie_alvo=str(item.get("especie_alvo") or "").strip() or None,
            prioridade_padrao=str(item.get("prioridade_padrao") or "Rotina").strip() or "Rotina",
            valor_padrao=float(item.get("valor_padrao") or 0),
            preparo=str(item.get("preparo") or "").strip() or None,
            observacoes_padrao=str(item.get("observacoes_padrao") or "").strip() or None,
            sinonimos_json=json.dumps(_parse_sinonimos(item.get("sinonimos")), ensure_ascii=False),
            ativo=int(item.get("ativo", 1) or 0),
        )
        db.add(registro)
        db.flush()
        existing_exames[codigo] = registro
        report["seeded_exames"] += 1

    for item in paineis_seed:
        codigo = str(item.get("codigo") or "").strip()
        nome = str(item.get("nome") or "").strip()
        if not codigo or not nome or codigo in existing_paineis:
            continue

        registro = PainelExame(
            codigo=codigo,
            nome=nome,
            categoria=str(item.get("categoria") or "").strip() or None,
            especie_alvo=str(item.get("especie_alvo") or "").strip() or None,
            observacoes=str(item.get("observacoes") or "").strip() or None,
            ativo=int(item.get("ativo", 1) or 0),
        )
        db.add(registro)
        db.flush()
        existing_paineis[codigo] = registro
        report["seeded_paineis"] += 1

    existing_links = {
        (row.painel_id, row.catalogo_exame_id)
        for row in db.query(PainelExameItem).all()
    }

    for painel_seed in paineis_seed:
        painel_codigo = str(painel_seed.get("codigo") or "").strip()
        painel = existing_paineis.get(painel_codigo)
        if painel is None:
            continue

        for ordem, exame_codigo in enumerate(painel_seed.get("itens") or []):
            exame = existing_exames.get(str(exame_codigo or "").strip())
            if exame is None or (painel.id, exame.id) in existing_links:
                continue

            db.add(
                PainelExameItem(
                    painel_id=painel.id,
                    catalogo_exame_id=exame.id,
                    ordem=ordem,
                )
            )
            existing_links.add((painel.id, exame.id))
            report["seeded_itens"] += 1

    if not any((report["seeded_exames"], report["seeded_paineis"], report["seeded_itens"])):
        report["db_exames"] = db.query(CatalogoExame).count()
        report["db_paineis"] = db.query(PainelExame).count()
        return report

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        report["error"] = str(exc)
        return report

    report["seeded"] = True
    report["db_exames"] = db.query(CatalogoExame).count()
    report["db_paineis"] = db.query(PainelExame).count()
    return report


def listar_catalogo_exames(
    db: Session,
    *,
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    ativos: Optional[int] = 1,
    limit: int = 500,
) -> List[CatalogoExame]:
    ensure_exam_catalog_seeded(db)
    query = db.query(CatalogoExame)
    if ativos is not None:
        query = query.filter(CatalogoExame.ativo == ativos)
    if categoria:
        query = query.filter(CatalogoExame.categoria == categoria)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                CatalogoExame.nome.ilike(term),
                CatalogoExame.codigo.ilike(term),
                CatalogoExame.categoria.ilike(term),
                CatalogoExame.subcategoria.ilike(term),
                CatalogoExame.sinonimos_json.ilike(term),
            )
        )
    return query.order_by(CatalogoExame.categoria.asc(), CatalogoExame.nome.asc()).limit(limit).all()


def listar_paineis_exames(
    db: Session,
    *,
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    ativos: Optional[int] = 1,
    limit: int = 200,
) -> List[PainelExame]:
    ensure_exam_catalog_seeded(db)
    query = db.query(PainelExame)
    if ativos is not None:
        query = query.filter(PainelExame.ativo == ativos)
    if categoria:
        query = query.filter(PainelExame.categoria == categoria)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                PainelExame.nome.ilike(term),
                PainelExame.codigo.ilike(term),
                PainelExame.categoria.ilike(term),
            )
        )
    return query.order_by(PainelExame.categoria.asc(), PainelExame.nome.asc()).limit(limit).all()


def montar_contexto_catalogo_exames(
    db: Session,
    *,
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    ativos: Optional[int] = 1,
) -> Dict[str, Any]:
    exames = listar_catalogo_exames(db, search=search, categoria=categoria, ativos=ativos)
    paineis = listar_paineis_exames(db, search=search, categoria=categoria, ativos=ativos)

    painel_ids = [item.id for item in paineis]
    itens_por_painel: Dict[int, List[Dict[str, Any]]] = {painel_id: [] for painel_id in painel_ids}
    if painel_ids:
        rows = (
            db.query(PainelExameItem, CatalogoExame)
            .join(CatalogoExame, CatalogoExame.id == PainelExameItem.catalogo_exame_id)
            .filter(PainelExameItem.painel_id.in_(painel_ids))
            .order_by(PainelExameItem.painel_id.asc(), PainelExameItem.ordem.asc(), CatalogoExame.nome.asc())
            .all()
        )
        for item, exame in rows:
            itens_por_painel.setdefault(item.painel_id, []).append(
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
            )

    categorias = sorted({item.categoria for item in exames if (item.categoria or "").strip()})
    return {
        "seed": ensure_exam_catalog_seeded(db),
        "categorias": categorias,
        "exames": [catalogo_exame_to_dict(item) for item in exames],
        "paineis": [painel_exame_to_dict(item, itens_por_painel.get(item.id, [])) for item in paineis],
    }
