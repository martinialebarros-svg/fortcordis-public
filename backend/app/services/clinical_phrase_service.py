from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, or_
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.frase_atendimento_clinico import FraseAtendimentoClinico

DATA_DIR = Path(__file__).parent.parent.parent / "data"
CLINICAL_PHRASES_FILE = DATA_DIR / "atendimento_clinical_phrases.json"

VALID_SECOES = {
    "queixa_principal",
    "anamnese",
    "exame_fisico",
    "dados_clinicos",
    "diagnostico_principal",
    "diagnostico_secundario",
    "diagnostico_diferencial",
    "plano_terapeutico",
    "retorno_recomendado",
    "motivo_retorno",
    "observacoes",
}


def _load_json(filepath: Path, default: Any = None) -> Any:
    if not filepath.exists():
        return default
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _table_exists(db: Session, table_name: str) -> bool:
    # Authentication may already hold a pool slot in this request's session.
    inspector = inspect(db.connection())
    return table_name in inspector.get_table_names()


def clinical_phrase_to_dict(item: FraseAtendimentoClinico) -> Dict[str, Any]:
    return {
        "id": item.id,
        "secao": item.secao,
        "titulo": item.titulo,
        "texto": item.texto or "",
        "ordem": item.ordem or 0,
        "ativo": item.ativo,
        "parametrizacao_origem": item.parametrizacao_origem or "manual",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "created_by": item.created_by,
    }


def ensure_clinical_phrases_seeded(db: Session) -> Dict[str, Any]:
    report = {
        "tables_ready": _table_exists(db, "frases_atendimento_clinico"),
        "seeded": False,
        "seeded_items": 0,
        "db_items": 0,
        "json_items": 0,
        "error": None,
    }
    if not report["tables_ready"]:
        return report

    try:
        report["db_items"] = db.query(FraseAtendimentoClinico).count()
    except (ProgrammingError, OperationalError):
        db.rollback()
        report["tables_ready"] = False
        return report

    payload = _load_json(CLINICAL_PHRASES_FILE, {"version": "1.0", "frases": []})
    frases_seed = payload.get("frases", []) if isinstance(payload, dict) else []
    if not isinstance(frases_seed, list):
        frases_seed = []
    report["json_items"] = len(frases_seed)
    if not frases_seed:
        return report

    existing = {
        ((item.secao or "").strip(), (item.titulo or "").strip()): item
        for item in db.query(FraseAtendimentoClinico).all()
        if (item.secao or "").strip() and (item.titulo or "").strip()
    }

    for seed in frases_seed:
        secao = str(seed.get("secao") or "").strip()
        titulo = str(seed.get("titulo") or "").strip()
        texto = str(seed.get("texto") or "").strip()
        if not secao or not titulo or not texto or secao not in VALID_SECOES:
            continue
        if (secao, titulo) in existing:
            continue

        registro = FraseAtendimentoClinico(
            secao=secao,
            titulo=titulo,
            texto=texto,
            ordem=int(seed.get("ordem") or 0),
            ativo=int(seed.get("ativo", 1) or 0),
            parametrizacao_origem="seed",
        )
        db.add(registro)
        db.flush()
        existing[(secao, titulo)] = registro
        report["seeded_items"] += 1

    if report["seeded_items"] == 0:
        report["db_items"] = db.query(FraseAtendimentoClinico).count()
        return report

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        report["error"] = str(exc)
        return report

    report["seeded"] = True
    report["db_items"] = db.query(FraseAtendimentoClinico).count()
    return report


def listar_frases_clinicas(
    db: Session,
    *,
    secao: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    skip: int = 0,
    limit: int = 500,
) -> List[FraseAtendimentoClinico]:
    ensure_clinical_phrases_seeded(db)

    query = db.query(FraseAtendimentoClinico)
    if secao:
        query = query.filter(FraseAtendimentoClinico.secao == secao)
    if not include_inactive:
        query = query.filter(FraseAtendimentoClinico.ativo == 1)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                FraseAtendimentoClinico.secao.ilike(term),
                FraseAtendimentoClinico.titulo.ilike(term),
                FraseAtendimentoClinico.texto.ilike(term),
            )
        )

    return (
        query.order_by(
            FraseAtendimentoClinico.secao.asc(),
            FraseAtendimentoClinico.ordem.asc(),
            FraseAtendimentoClinico.titulo.asc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def montar_contexto_frases_clinicas(
    db: Session,
    *,
    secao: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    skip: int = 0,
    limit: int = 500,
) -> Dict[str, Any]:
    ensure_clinical_phrases_seeded(db)
    query = db.query(FraseAtendimentoClinico)
    if secao:
        query = query.filter(FraseAtendimentoClinico.secao == secao)
    if not include_inactive:
        query = query.filter(FraseAtendimentoClinico.ativo == 1)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                FraseAtendimentoClinico.secao.ilike(term),
                FraseAtendimentoClinico.titulo.ilike(term),
                FraseAtendimentoClinico.texto.ilike(term),
            )
        )

    frases = listar_frases_clinicas(
        db,
        secao=secao,
        search=search,
        include_inactive=include_inactive,
        skip=skip,
        limit=limit,
    )
    secoes = sorted(set(VALID_SECOES) | {frase.secao for frase in frases if (frase.secao or "").strip()})
    return {
        "seed": ensure_clinical_phrases_seeded(db),
        "secoes": secoes,
        "total": query.count(),
        "frases": [clinical_phrase_to_dict(item) for item in frases],
    }
