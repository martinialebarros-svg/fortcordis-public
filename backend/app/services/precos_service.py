"""Pricing helpers for clinic and service combinations."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.clinica import Clinica
from app.models.servico import Servico
from app.models.tabela_preco import PrecoServico, PrecoServicoClinica


def to_decimal(value, default: Decimal = Decimal("0.00")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _normalize_tipo_horario(tipo_horario: str) -> str:
    return "plantao" if str(tipo_horario or "").lower() == "plantao" else "comercial"


def _is_missing_pricing_schema_error(exc: Exception) -> bool:
    text = str(getattr(exc, "orig", exc)).lower()
    return (
        "no such table" in text
        or "does not exist" in text
        or "undefined table" in text
        or "no such column" in text
        or "undefined column" in text
        or "unknown column" in text
    )


def _preco_tabela_padrao(
    db: Session,
    clinica: Clinica,
    servico: Servico,
    tipo_horario: str,
) -> Decimal:
    tabela_id = clinica.tabela_preco_id or 1
    if tabela_id == 1:
        return to_decimal(
            servico.preco_fortaleza_plantao if tipo_horario == "plantao" else servico.preco_fortaleza_comercial
        )
    if tabela_id == 2:
        return to_decimal(servico.preco_rm_plantao if tipo_horario == "plantao" else servico.preco_rm_comercial)
    if tabela_id == 3:
        return to_decimal(
            servico.preco_domiciliar_plantao if tipo_horario == "plantao" else servico.preco_domiciliar_comercial
        )

    preco_custom_tabela = db.query(PrecoServico).filter(
        PrecoServico.tabela_preco_id == tabela_id,
        PrecoServico.servico_id == servico.id,
    )
    try:
        preco_custom_tabela = preco_custom_tabela.first()
    except (OperationalError, ProgrammingError) as exc:
        if not _is_missing_pricing_schema_error(exc):
            raise
        preco_custom_tabela = None
    if preco_custom_tabela:
        field = preco_custom_tabela.preco_plantao if tipo_horario == "plantao" else preco_custom_tabela.preco_comercial
        if field is not None:
            return to_decimal(field)

    return to_decimal(servico.preco)


def calcular_preco_servico(
    db: Session,
    clinica_id: int | None,
    servico_id: int,
    tipo_horario: str = "comercial",
    *,
    usar_preco_clinica: bool = True,
    origem_atendimento: str | None = None,
) -> Decimal:
    """Calcula preco final para OS/agendamento.

    Prioridade:
    1) Preco negociado da clinica para o servico (quando existir)
    2) Preco da tabela da clinica
    """
    servico = db.query(Servico).filter(Servico.id == servico_id).first()
    if not servico:
        raise HTTPException(status_code=404, detail="Servico nao encontrado")

    horario = _normalize_tipo_horario(tipo_horario)
    origem_normalizada = str(origem_atendimento or "").strip().lower()

    if not clinica_id:
        if origem_normalizada == "domiciliar":
            preco_domiciliar = to_decimal(
                servico.preco_domiciliar_plantao
                if horario == "plantao"
                else servico.preco_domiciliar_comercial
            )
            if preco_domiciliar > Decimal("0.00"):
                return preco_domiciliar
            return to_decimal(servico.preco)
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if not clinica:
        raise HTTPException(status_code=404, detail="Clinica nao encontrada")

    if usar_preco_clinica:
        try:
            preco_clinica = db.query(PrecoServicoClinica).filter(
                PrecoServicoClinica.clinica_id == clinica_id,
                PrecoServicoClinica.servico_id == servico_id,
                PrecoServicoClinica.ativo == 1,
            ).first()
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_pricing_schema_error(exc):
                raise
            preco_clinica = None
        if preco_clinica:
            field = preco_clinica.preco_plantao if horario == "plantao" else preco_clinica.preco_comercial
            if field is not None:
                return to_decimal(field)

    return _preco_tabela_padrao(db, clinica, servico, horario)


def calcular_precos_servicos_em_lote(
    db: Session,
    solicitacoes: Iterable[tuple[int | None, int, str | None]],
    tipo_horario: str = "comercial",
    *,
    usar_preco_clinica: bool = True,
) -> dict[tuple[int | None, int, str], Decimal]:
    """Calcula precos para combinacoes de clinica, servico e origem em consultas limitadas.

    A regra de prioridade e a mesma de :func:`calcular_preco_servico`, mas as
    entidades e tabelas de precificacao sao carregadas uma vez por lote. Isso
    evita que resumos com varios agendamentos repitam as mesmas consultas.
    """
    horario = _normalize_tipo_horario(tipo_horario)
    chaves: list[tuple[int | None, int, str]] = []
    vistos: set[tuple[int | None, int, str]] = set()

    for clinica_id, servico_id, origem_atendimento in solicitacoes:
        try:
            servico_id_normalizado = int(servico_id)
        except (TypeError, ValueError):
            continue
        if servico_id_normalizado <= 0:
            continue

        try:
            clinica_id_normalizado = int(clinica_id) if clinica_id is not None else None
        except (TypeError, ValueError):
            clinica_id_normalizado = None
        if clinica_id_normalizado is not None and clinica_id_normalizado <= 0:
            clinica_id_normalizado = None

        origem_normalizada = str(origem_atendimento or "").strip().lower()
        chave = (clinica_id_normalizado, servico_id_normalizado, origem_normalizada)
        if chave in vistos:
            continue
        vistos.add(chave)
        chaves.append(chave)

    if not chaves:
        return {}

    servico_ids = sorted({servico_id for _, servico_id, _ in chaves})
    clinica_ids = sorted({clinica_id for clinica_id, _, _ in chaves if clinica_id is not None})
    servicos = {
        int(servico.id): servico
        for servico in db.query(Servico).filter(Servico.id.in_(servico_ids)).all()
    }
    clinicas = {
        int(clinica.id): clinica
        for clinica in db.query(Clinica).filter(Clinica.id.in_(clinica_ids)).all()
    } if clinica_ids else {}

    precos_clinica: dict[tuple[int, int], PrecoServicoClinica] = {}
    if usar_preco_clinica and clinica_ids:
        try:
            precos_clinica_rows = (
                db.query(PrecoServicoClinica)
                .filter(
                    PrecoServicoClinica.clinica_id.in_(clinica_ids),
                    PrecoServicoClinica.servico_id.in_(servico_ids),
                    PrecoServicoClinica.ativo == 1,
                )
                .all()
            )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_pricing_schema_error(exc):
                raise
            precos_clinica_rows = []
        for preco_clinica in precos_clinica_rows:
            precos_clinica.setdefault(
                (int(preco_clinica.clinica_id), int(preco_clinica.servico_id)),
                preco_clinica,
            )

    tabela_ids_customizadas = sorted(
        {
            int(getattr(clinica, "tabela_preco_id", None) or 1)
            for clinica in clinicas.values()
            if int(getattr(clinica, "tabela_preco_id", None) or 1) not in (1, 2, 3)
        }
    )
    precos_tabela: dict[tuple[int, int], PrecoServico] = {}
    if tabela_ids_customizadas:
        try:
            precos_tabela_rows = (
                db.query(PrecoServico)
                .filter(
                    PrecoServico.tabela_preco_id.in_(tabela_ids_customizadas),
                    PrecoServico.servico_id.in_(servico_ids),
                )
                .all()
            )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_missing_pricing_schema_error(exc):
                raise
            precos_tabela_rows = []
        for preco_tabela in precos_tabela_rows:
            precos_tabela.setdefault(
                (int(preco_tabela.tabela_preco_id), int(preco_tabela.servico_id)),
                preco_tabela,
            )

    precos: dict[tuple[int | None, int, str], Decimal] = {}
    for clinica_id, servico_id, origem in chaves:
        servico = servicos.get(servico_id)
        if not servico:
            continue

        if clinica_id is None:
            if origem == "domiciliar":
                preco_domiciliar = to_decimal(
                    servico.preco_domiciliar_plantao
                    if horario == "plantao"
                    else servico.preco_domiciliar_comercial
                )
                precos[(clinica_id, servico_id, origem)] = (
                    preco_domiciliar if preco_domiciliar > Decimal("0.00") else to_decimal(servico.preco)
                )
            continue

        clinica = clinicas.get(clinica_id)
        if not clinica:
            continue

        preco_clinica = precos_clinica.get((clinica_id, servico_id))
        if preco_clinica:
            campo_preco_clinica = (
                preco_clinica.preco_plantao if horario == "plantao" else preco_clinica.preco_comercial
            )
            if campo_preco_clinica is not None:
                precos[(clinica_id, servico_id, origem)] = to_decimal(campo_preco_clinica)
                continue

        tabela_id = int(getattr(clinica, "tabela_preco_id", None) or 1)
        if tabela_id == 1:
            precos[(clinica_id, servico_id, origem)] = to_decimal(
                servico.preco_fortaleza_plantao if horario == "plantao" else servico.preco_fortaleza_comercial
            )
            continue
        if tabela_id == 2:
            precos[(clinica_id, servico_id, origem)] = to_decimal(
                servico.preco_rm_plantao if horario == "plantao" else servico.preco_rm_comercial
            )
            continue
        if tabela_id == 3:
            precos[(clinica_id, servico_id, origem)] = to_decimal(
                servico.preco_domiciliar_plantao if horario == "plantao" else servico.preco_domiciliar_comercial
            )
            continue

        preco_tabela = precos_tabela.get((tabela_id, servico_id))
        if preco_tabela:
            campo_preco_tabela = preco_tabela.preco_plantao if horario == "plantao" else preco_tabela.preco_comercial
            if campo_preco_tabela is not None:
                precos[(clinica_id, servico_id, origem)] = to_decimal(campo_preco_tabela)
                continue

        precos[(clinica_id, servico_id, origem)] = to_decimal(servico.preco)

    return precos
