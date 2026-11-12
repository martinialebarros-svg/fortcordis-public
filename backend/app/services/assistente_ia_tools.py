from __future__ import annotations

import json
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.endpoints import agenda, clinicas, configuracoes, tutores
from app.core.agenda_config import (
    DEFAULT_AGENDA_SEMANAL,
    DEFAULT_EXCECAO_FIM,
    DEFAULT_EXCECAO_INICIO,
    carregar_agenda_excecoes,
    carregar_agenda_feriados,
    carregar_agenda_semanal,
    obter_excecao_data,
    obter_feriado,
)
from app.core.config import settings
from app.models.agendamento import Agendamento
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.assistente_ia import AssistenteIAAcaoPendente, AssistenteIAConversa
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.financeiro import ContaReceber, Transacao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tabela_preco import TabelaPreco
from app.models.tutor import Tutor
from app.models.user import User
from app.schemas.agendamento import AgendamentoCreate, AgendamentoUpdate
from app.schemas.agenda_preferencia import AgendaPreferencia
from app.services.assistente_ia_management import (
    clinical_report_context,
    create_memory,
    executive_summary,
    save_clinical_draft,
    search_knowledge,
)
from app.services.assistente_ia_clinics360 import (
    clinic_360_profile,
    compare_clinics_360,
)
from app.services.auditoria_service import registrar_auditoria
from app.services.google_maps_cost_control import GoogleMapsCostBlocked
from app.services.logistica_service import obter_ou_criar_deslocamento, serialize_deslocamento
from app.services.precos_service import calcular_preco_servico

LOCAL_TZ = ZoneInfo("America/Fortaleza")
ACTIVE_APPOINTMENT_STATUSES = {
    "Agendado",
    "Reservado",
    "Confirmado",
    "Em atendimento",
    "Realizado",
    "Faltou",
}
FORECAST_APPOINTMENT_STATUSES = {
    "Agendado",
    "Reservado",
    "Confirmado",
    "Em atendimento",
}


@dataclass(slots=True)
class AssistenteIAToolContext:
    db: Session
    current_user: User
    conversa: AssistenteIAConversa
    request: Optional[Request] = None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    alphanumeric = "".join(
        char if char.isalnum() else " "
        for char in without_accents
    )
    return " ".join(alphanumeric.split())


def _fuzzy_name_score(requested: str, candidate: str) -> float:
    direct = SequenceMatcher(None, requested, candidate).ratio()
    compact = SequenceMatcher(
        None,
        requested.replace(" ", ""),
        candidate.replace(" ", ""),
    ).ratio()
    requested_tokens = requested.split()
    candidate_tokens = candidate.split()
    token_score = 0.0
    if requested_tokens and candidate_tokens:
        token_score = sum(
            max(SequenceMatcher(None, token, candidate_token).ratio() for candidate_token in candidate_tokens)
            for token in requested_tokens
        ) / len(requested_tokens)
    return max(direct, compact, (direct * 0.55) + (token_score * 0.45))


def _confident_fuzzy_match(
    normalized_request: str,
    ranked: list[tuple[float, Any]],
) -> Any | None:
    if not ranked or len(normalized_request.replace(" ", "")) < 5:
        return None
    top_score, top_record = ranked[0]
    runner_up_score = ranked[1][0] if len(ranked) > 1 else 0.0
    request_length = len(normalized_request.replace(" ", ""))
    threshold = 0.86 if request_length <= 7 else 0.80 if request_length <= 14 else 0.77
    minimum_margin = 0.08 if top_score >= 0.92 else 0.12
    if top_score >= threshold and (top_score - runner_up_score) >= minimum_margin:
        return top_record
    return None


def _resolve_named_record(
    db: Session,
    model: Any,
    requested_name: str,
    *,
    entity_label: str,
    filters: Optional[list[Any]] = None,
    exigir_id: bool = False,
) -> tuple[Any | None, dict[str, Any] | None]:
    if exigir_id:
        raw_id = str(requested_name or "").strip().lstrip("#")
        if raw_id.isdigit():
            from app.services.tutor_identidade_service import exigir_tutor_utilizavel
            try:
                return exigir_tutor_utilizavel(db, int(raw_id)), None
            except HTTPException as exc:
                return None, {"ok": False, "error": str(exc.detail)}
        return None, {"ok": False, "error": "Selecione o tutor pelo ID (ex.: #184). O nome nao confirma a identidade; consulte os cadastros e revise os animais e contatos antes de selecionar."}
    normalized_request = _normalize_text(requested_name)
    if not normalized_request:
        return None, {
            "ok": False,
            "error": f"Informe o nome de {entity_label}.",
        }

    query = db.query(model)
    if hasattr(model, "ativo"):
        query = query.filter(model.ativo.in_([True, 1]))
    if filters:
        query = query.filter(*filters)
    records = query.order_by(model.nome.asc()).all()
    names = [(record, _normalize_text(getattr(record, "nome", ""))) for record in records]

    exact = [record for record, name in names if name == normalized_request]
    if len(exact) == 1:
        return exact[0], None

    contains = [
        record
        for record, name in names
        if normalized_request in name or name in normalized_request
    ]
    if len(contains) == 1:
        return contains[0], None

    request_tokens = set(normalized_request.split())
    token_matches = [
        record
        for record, name in names
        if request_tokens and request_tokens.issubset(set(name.split()))
    ]
    if len(token_matches) == 1:
        return token_matches[0], None

    ambiguous = exact or contains or token_matches
    if len(ambiguous) > 1:
        return None, {
            "ok": False,
            "error": f"Nome de {entity_label} ambiguo.",
            "matches": [
                {"id": int(record.id), "nome": str(record.nome)}
                for record in ambiguous[:8]
            ],
        }

    ranked = sorted(
        (
            (_fuzzy_name_score(normalized_request, name), record)
            for record, name in names
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if _normalize_text(entity_label) == "clinica":
        fuzzy_match = _confident_fuzzy_match(normalized_request, ranked)
        if fuzzy_match is not None:
            return fuzzy_match, None
    suggestions = [
        {"id": int(record.id), "nome": str(record.nome)}
        for score, record in ranked[:5]
        if score >= 0.35
    ]
    return None, {
        "ok": False,
        "error": f"{entity_label.capitalize()} nao encontrada.",
        "matches": suggestions,
    }


def _parse_iso_date(value: Optional[str], *, default: Optional[date] = None) -> date:
    raw = str(value or "").strip()
    if not raw and default is not None:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Data invalida. Use YYYY-MM-DD.") from exc


def _parse_hhmm(value: Optional[str]) -> Optional[time]:
    raw = str(value or "").strip()
    if not raw:
        return None
    for pattern in ("%H:%M", "%Hh%M", "%Hh"):
        try:
            return datetime.strptime(raw, pattern).time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    raise ValueError("Horario invalido. Use HH:MM.")


def _as_local_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _as_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_day_shifted(reference: date, month_delta: int) -> date:
    absolute_month = (reference.year * 12 + reference.month - 1) + month_delta
    year, month_zero = divmod(absolute_month, 12)
    return date(year, month_zero + 1, 1)


def analisar_faturamento(
    ctx: AssistenteIAToolContext,
    *,
    meses: int,
    clinica: Optional[str],
) -> dict[str, Any]:
    meses = max(2, min(24, int(meses or 5)))
    clinica_obj: Optional[Clinica] = None
    if str(clinica or "").strip():
        clinica_obj, error = _resolve_named_record(
            ctx.db,
            Clinica,
            str(clinica),
            entity_label="clinica",
        )
        if error:
            return error

    hoje = datetime.now(LOCAL_TZ).date()
    primeiro_mes = _first_day_shifted(hoje.replace(day=1), -(meses - 1))
    series: list[dict[str, Any]] = []

    for offset in range(meses):
        inicio = _first_day_shifted(primeiro_mes, offset)
        proximo = _first_day_shifted(inicio, 1)
        fim = min(hoje, proximo - timedelta(days=1))
        filtros = [
            Transacao.tipo == "entrada",
            Transacao.status.in_(["Recebido", "Pago"]),
            func.date(Transacao.data_transacao) >= inicio.isoformat(),
            func.date(Transacao.data_transacao) < proximo.isoformat(),
        ]
        if clinica_obj is not None:
            filtros.append(Transacao.clinica_id == clinica_obj.id)

        total, quantidade, taxas = (
            ctx.db.query(
                func.coalesce(func.sum(Transacao.valor_final), 0),
                func.count(Transacao.id),
                func.coalesce(func.sum(Transacao.valor_taxa), 0),
            )
            .filter(*filtros)
            .one()
        )
        total_float = round(float(total or 0), 2)
        taxas_float = round(float(taxas or 0), 2)
        item = {
            "competencia": inicio.strftime("%Y-%m"),
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "parcial": inicio.year == hoje.year and inicio.month == hoje.month,
            "faturamento_liquido": total_float,
            "taxas": taxas_float,
            "recebimentos": int(quantidade or 0),
            "ticket_medio": round(total_float / int(quantidade), 2) if quantidade else 0.0,
            "variacao_percentual": None,
        }
        if series and float(series[-1]["faturamento_liquido"]) != 0:
            previous = float(series[-1]["faturamento_liquido"])
            item["variacao_percentual"] = round(((total_float - previous) / previous) * 100, 2)
        series.append(item)

    total_periodo = round(sum(float(item["faturamento_liquido"]) for item in series), 2)
    values = [float(item["faturamento_liquido"]) for item in series]
    best = max(series, key=lambda item: float(item["faturamento_liquido"])) if series else None
    worst = min(series, key=lambda item: float(item["faturamento_liquido"])) if series else None
    crescimento = None
    if len(values) >= 2 and values[0] != 0:
        crescimento = round(((values[-1] - values[0]) / values[0]) * 100, 2)

    return {
        "ok": True,
        "fonte": "transacoes recebidas do modulo financeiro",
        "clinica": (
            {"id": int(clinica_obj.id), "nome": str(clinica_obj.nome)}
            if clinica_obj is not None
            else None
        ),
        "periodo": {
            "meses": meses,
            "inicio": primeiro_mes.isoformat(),
            "fim": hoje.isoformat(),
            "mes_atual_parcial": True,
        },
        "resumo": {
            "faturamento_total": total_periodo,
            "media_mensal": round(total_periodo / meses, 2),
            "crescimento_primeiro_ultimo_percentual": crescimento,
            "melhor_mes": best,
            "menor_mes": worst,
        },
        "serie_mensal": series,
    }


def analisar_servicos_realizados(
    ctx: AssistenteIAToolContext,
    *,
    data_inicio: str,
    data_fim: str,
    clinica: Optional[str],
) -> dict[str, Any]:
    try:
        inicio = _parse_iso_date(data_inicio)
        fim = _parse_iso_date(data_fim)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if fim < inicio:
        return {"ok": False, "error": "A data final nao pode ser anterior a data inicial."}
    if (fim - inicio).days > 366:
        return {"ok": False, "error": "O periodo deve ter no maximo 367 dias."}

    clinica_obj: Optional[Clinica] = None
    if str(clinica or "").strip():
        clinica_obj, error = _resolve_named_record(
            ctx.db,
            Clinica,
            str(clinica),
            entity_label="clinica",
        )
        if error:
            return error

    filters = [
        func.date(OrdemServico.data_atendimento) >= inicio.isoformat(),
        func.date(OrdemServico.data_atendimento) <= fim.isoformat(),
        func.lower(func.coalesce(OrdemServico.status, "")) != "cancelado",
    ]
    if clinica_obj is not None:
        filters.append(OrdemServico.clinica_id == clinica_obj.id)
    orders = (
        ctx.db.query(OrdemServico)
        .filter(*filters)
        .order_by(OrdemServico.data_atendimento.asc(), OrdemServico.id.asc())
        .limit(5000)
        .all()
    )

    clinic_ids = {int(item.clinica_id) for item in orders if item.clinica_id}
    service_ids = {int(item.servico_id) for item in orders if item.servico_id}
    clinic_map = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(Clinica).filter(Clinica.id.in_(clinic_ids)).all()
    } if clinic_ids else {}
    service_map = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(Servico).filter(Servico.id.in_(service_ids)).all()
    } if service_ids else {}

    def aggregate(key_for: Any) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for order in orders:
            key = str(key_for(order) or "Nao informado")
            item = grouped.setdefault(key, {"nome": key, "quantidade": 0, "valor": 0.0})
            item["quantidade"] += 1
            item["valor"] = round(float(item["valor"]) + float(order.valor_final or 0), 2)
        return sorted(grouped.values(), key=lambda item: (-float(item["valor"]), str(item["nome"])))

    total = round(sum(float(item.valor_final or 0) for item in orders), 2)
    by_status = aggregate(lambda item: str(item.status or "Nao informado"))
    by_clinic = aggregate(
        lambda item: clinic_map.get(int(item.clinica_id), "Sem clinica")
        if item.clinica_id
        else "Sem clinica"
    )
    by_service = aggregate(
        lambda item: service_map.get(int(item.servico_id), f"Servico #{item.servico_id}")
        if item.servico_id
        else "Servico nao informado"
    )
    return {
        "ok": True,
        "fonte": "ordens de servico por data de atendimento, excluindo status Cancelado",
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "clinica": (
            {"id": int(clinica_obj.id), "nome": str(clinica_obj.nome)}
            if clinica_obj is not None
            else None
        ),
        "resumo": {
            "ordens_servico": len(orders),
            "valor_servicos_realizados": total,
            "ticket_medio": round(total / len(orders), 2) if orders else 0.0,
        },
        "por_status": by_status,
        "por_clinica": by_clinic[:25],
        "por_servico": by_service[:25],
        "truncado": len(orders) >= 5000,
        "aviso": "Este valor mede servicos realizados pelas ordens de servico, independentemente do recebimento financeiro.",
    }


def projetar_faturamento_agenda(
    ctx: AssistenteIAToolContext,
    *,
    data: str,
    clinica: Optional[str],
) -> dict[str, Any]:
    try:
        data_ref = _parse_iso_date(data)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    clinica_obj: Optional[Clinica] = None
    if str(clinica or "").strip():
        clinica_obj, error = _resolve_named_record(
            ctx.db,
            Clinica,
            str(clinica),
            entity_label="clinica",
        )
        if error:
            return error

    query = ctx.db.query(Agendamento).filter(
        func.date(Agendamento.inicio) == data_ref.isoformat(),
        Agendamento.status.in_(sorted(FORECAST_APPOINTMENT_STATUSES)),
    )
    if clinica_obj is not None:
        query = query.filter(Agendamento.clinica_id == clinica_obj.id)
    appointments = (
        query
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .limit(1000)
        .all()
    )

    clinic_ids = {int(item.clinica_id) for item in appointments if item.clinica_id}
    service_ids = {int(item.servico_id) for item in appointments if item.servico_id}
    appointment_ids = [int(item.id) for item in appointments]
    clinic_map = {
        int(item.id): item
        for item in ctx.db.query(Clinica).filter(Clinica.id.in_(clinic_ids)).all()
    } if clinic_ids else {}
    service_map = {
        int(item.id): item
        for item in ctx.db.query(Servico).filter(Servico.id.in_(service_ids)).all()
    } if service_ids else {}
    table_names = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(TabelaPreco).all()
    }
    fallback_table_names = {
        1: "Clinicas Fortaleza",
        2: "Regiao Metropolitana",
        3: "Domiciliar",
        4: "Personalizado",
    }

    orders_by_appointment: dict[int, OrdemServico] = {}
    if appointment_ids:
        orders = (
            ctx.db.query(OrdemServico)
            .filter(
                OrdemServico.agendamento_id.in_(appointment_ids),
                func.lower(func.coalesce(OrdemServico.status, "")) != "cancelado",
            )
            .order_by(OrdemServico.id.desc())
            .all()
        )
        for order in orders:
            if order.agendamento_id:
                orders_by_appointment.setdefault(int(order.agendamento_id), order)

    items: list[dict[str, Any]] = []
    total_scheduled = 0.0
    total_reserved = 0.0
    without_price = 0
    by_clinic: dict[str, dict[str, Any]] = {}
    by_service: dict[str, dict[str, Any]] = {}
    by_status: dict[str, dict[str, Any]] = {}

    def add_group(
        groups: dict[str, dict[str, Any]],
        name: str,
        value: Optional[float],
    ) -> None:
        group = groups.setdefault(
            name,
            {"nome": name, "quantidade": 0, "valor_previsto": 0.0, "sem_valor": 0},
        )
        group["quantidade"] += 1
        if value is None:
            group["sem_valor"] += 1
        else:
            group["valor_previsto"] = round(float(group["valor_previsto"]) + value, 2)

    for appointment in appointments:
        clinic_record = (
            clinic_map.get(int(appointment.clinica_id))
            if appointment.clinica_id
            else None
        )
        service_record = (
            service_map.get(int(appointment.servico_id))
            if appointment.servico_id
            else None
        )
        clinic_name = (
            str(clinic_record.nome)
            if clinic_record is not None
            else str(appointment.clinica or "Atendimento domiciliar")
        )
        service_name = (
            str(service_record.nome)
            if service_record is not None
            else str(appointment.servico or "Servico nao informado")
        )
        table_id = int(clinic_record.tabela_preco_id or 1) if clinic_record is not None else 3
        table_name = table_names.get(table_id) or fallback_table_names.get(
            table_id,
            f"Tabela #{table_id}",
        )
        linked_order = orders_by_appointment.get(int(appointment.id))
        value: Optional[float] = None
        price_source: Optional[str] = None
        price_error: Optional[str] = None

        if linked_order is not None and linked_order.valor_final is not None:
            value = round(float(linked_order.valor_final), 2)
            price_source = "ordem_de_servico_vinculada"
        elif service_record is not None and (
            clinic_record is not None
            or _normalize_text(appointment.origem_atendimento) == "domiciliar"
        ):
            try:
                calculated = calcular_preco_servico(
                    db=ctx.db,
                    clinica_id=int(clinic_record.id) if clinic_record is not None else None,
                    servico_id=int(service_record.id),
                    tipo_horario="comercial",
                    usar_preco_clinica=True,
                    origem_atendimento=appointment.origem_atendimento,
                )
                value = round(float(calculated), 2)
                price_source = "regra_oficial_de_precos"
            except HTTPException as exc:
                price_error = str(exc.detail)
        else:
            price_error = "Clinica ou servico sem cadastro vinculado."

        if value is None:
            without_price += 1
        elif str(appointment.status) == "Reservado":
            total_reserved = round(total_reserved + value, 2)
        else:
            total_scheduled = round(total_scheduled + value, 2)

        local_start = _as_local_datetime(appointment.inicio)
        item = {
            "agendamento_id": int(appointment.id),
            "horario": local_start.strftime("%H:%M") if local_start else str(appointment.hora or ""),
            "status": str(appointment.status),
            "clinica": clinic_name,
            "tabela_preco": table_name,
            "servico": service_name,
            "valor_previsto": value,
            "fonte_valor": price_source,
        }
        if price_error:
            item["erro_preco"] = price_error
        items.append(item)
        add_group(by_clinic, clinic_name, value)
        add_group(by_service, service_name, value)
        add_group(by_status, str(appointment.status), value)

    total = round(total_scheduled + total_reserved, 2)

    def sorted_groups(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            groups.values(),
            key=lambda item: (-float(item["valor_previsto"]), str(item["nome"])),
        )

    return {
        "ok": True,
        "fonte": (
            "agenda ativa, ordens de servico vinculadas e regra oficial de precos; "
            "preco negociado da clinica tem prioridade sobre a tabela regional"
        ),
        "data": data_ref.isoformat(),
        "clinica": (
            {"id": int(clinica_obj.id), "nome": str(clinica_obj.nome)}
            if clinica_obj is not None
            else None
        ),
        "resumo": {
            "agendamentos_considerados": len(appointments),
            "agendados_confirmados_ou_em_atendimento": sum(
                1 for item in appointments if str(item.status) != "Reservado"
            ),
            "reservas": sum(1 for item in appointments if str(item.status) == "Reservado"),
            "valor_agendado": total_scheduled,
            "valor_reservado": total_reserved,
            "valor_total_previsto": total,
            "sem_valor_configurado": without_price,
            "ticket_medio_previsto": round(total / (len(appointments) - without_price), 2)
            if len(appointments) > without_price
            else 0.0,
        },
        "por_status": sorted_groups(by_status),
        "por_clinica": sorted_groups(by_clinic),
        "por_servico": sorted_groups(by_service),
        "itens": items,
        "truncado": len(appointments) >= 1000,
        "dados_pessoais_incluidos": False,
        "premissas": [
            "Agendado, Confirmado, Em atendimento e Reservado entram na projecao.",
            "Reservas ficam separadas porque ainda dependem de confirmacao.",
            "Na ausencia de OS vinculada, aplica-se o preco comercial oficial vigente.",
            "O total e previsao de producao da agenda, nao valor ja recebido.",
        ],
        "aviso": (
            "Cancelamentos, faltas, descontos e alteracoes posteriores podem mudar o valor realizado."
        ),
    }


def localizar_agendamentos(
    ctx: AssistenteIAToolContext,
    *,
    data: str,
    horario: Optional[str],
    clinica: Optional[str],
    servico: Optional[str],
) -> dict[str, Any]:
    try:
        data_ref = _parse_iso_date(data)
        horario_ref = _parse_hhmm(horario)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    clinica_obj: Optional[Clinica] = None
    servico_obj: Optional[Servico] = None
    if str(clinica or "").strip():
        clinica_obj, error = _resolve_named_record(
            ctx.db,
            Clinica,
            str(clinica),
            entity_label="clinica",
        )
        if error:
            return error
    if str(servico or "").strip():
        servico_obj, error = _resolve_named_record(
            ctx.db,
            Servico,
            str(servico),
            entity_label="servico",
        )
        if error:
            return error

    query = ctx.db.query(Agendamento).filter(
        func.date(Agendamento.inicio) == data_ref.isoformat(),
        Agendamento.status.in_(sorted(ACTIVE_APPOINTMENT_STATUSES)),
    )
    if clinica_obj is not None:
        query = query.filter(Agendamento.clinica_id == clinica_obj.id)
    if servico_obj is not None:
        query = query.filter(Agendamento.servico_id == servico_obj.id)
    appointments = query.order_by(Agendamento.inicio.asc(), Agendamento.id.asc()).limit(100).all()

    if horario_ref is not None:
        appointments = [
            item
            for item in appointments
            if (_as_local_datetime(item.inicio) or datetime.min.replace(tzinfo=LOCAL_TZ)).time().replace(
                second=0,
                microsecond=0,
            )
            == horario_ref
        ]

    clinic_ids = {int(item.clinica_id) for item in appointments if item.clinica_id}
    service_ids = {int(item.servico_id) for item in appointments if item.servico_id}
    patient_ids = {int(item.paciente_id) for item in appointments if item.paciente_id}
    clinic_map = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(Clinica).filter(Clinica.id.in_(clinic_ids)).all()
    } if clinic_ids else {}
    service_map = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(Servico).filter(Servico.id.in_(service_ids)).all()
    } if service_ids else {}
    patient_map = {
        int(item.id): str(item.nome or "").strip().split()[0]
        for item in ctx.db.query(Paciente).filter(Paciente.id.in_(patient_ids)).all()
    } if patient_ids else {}

    matches = []
    for item in appointments[:20]:
        inicio = _as_local_datetime(item.inicio)
        fim = _as_local_datetime(item.fim)
        matches.append(
            {
                "agendamento_id": int(item.id),
                "inicio": inicio.isoformat() if inicio else None,
                "fim": fim.isoformat() if fim else None,
                "horario": inicio.strftime("%H:%M") if inicio else str(item.hora or ""),
                "status": str(item.status or ""),
                "clinica": {
                    "id": int(item.clinica_id) if item.clinica_id else None,
                    "nome": clinic_map.get(int(item.clinica_id)) if item.clinica_id else str(item.clinica or ""),
                },
                "servico": {
                    "id": int(item.servico_id) if item.servico_id else None,
                    "nome": service_map.get(int(item.servico_id)) if item.servico_id else str(item.servico or ""),
                },
                "paciente_primeiro_nome": (
                    patient_map.get(int(item.paciente_id))
                    if item.paciente_id
                    else str(item.paciente or "").strip().split()[0] if str(item.paciente or "").strip() else None
                ),
            }
        )

    return {
        "ok": True,
        "data": data_ref.isoformat(),
        "horario": horario_ref.strftime("%H:%M") if horario_ref else None,
        "total": len(appointments),
        "matches": matches,
        "truncado": len(appointments) > len(matches),
        "orientacao": (
            "Ha mais de um candidato. Solicite desambiguacao antes de preparar qualquer exclusao."
            if len(appointments) > 1
            else "Use o agendamento_id retornado para preparar uma acao, se solicitado."
        ),
    }


def verificar_disponibilidade(
    ctx: AssistenteIAToolContext,
    *,
    clinica: str,
    servico: str,
    data_inicio: Optional[str],
    dias: int,
    preferencia: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    clinica_obj, error = _resolve_named_record(
        ctx.db,
        Clinica,
        clinica,
        entity_label="clinica",
    )
    if error:
        return error
    servico_obj, error = _resolve_named_record(
        ctx.db,
        Servico,
        servico,
        entity_label="servico",
    )
    if error:
        return error

    try:
        criterio = AgendaPreferencia.model_validate(preferencia) if preferencia is not None else None
        inicio = _parse_iso_date(
            (criterio.data_inicio if criterio else None) or data_inicio,
            default=datetime.now(LOCAL_TZ).date(),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    hoje = datetime.now(LOCAL_TZ).date()
    if inicio < hoje:
        inicio = hoje
    dias = max(1, min(14, int(dias or 7)))
    if criterio and criterio.data_fim:
        fim = date.fromisoformat(criterio.data_fim)
        if fim < hoje:
            return {"ok": False, "error": "O periodo da preferencia ja terminou. Informe um novo intervalo."}
        dias = (fim - inicio).days + 1
    else:
        fim = inicio + timedelta(days=dias - 1)

    slots: list[dict[str, Any]] = []
    dias_consultados: list[dict[str, Any]] = []
    for offset in range(dias):
        data_ref = inicio + timedelta(days=offset)
        if criterio and not criterio.permite_data(data_ref):
            continue
        payload = agenda.SugestaoHorarioPayload(
            data=data_ref.isoformat(),
            origem_atendimento="clinica_parceira",
            clinica_id=int(clinica_obj.id),
            servico_id=int(servico_obj.id),
            duracao_minutos=int(servico_obj.duracao_minutos or 30),
            intervalo_minutos=15,
            limite=6,
            perfil_deslocamento="comercial",
            preferencia=criterio,
        )
        try:
            result = agenda.sugerir_horarios_agenda(
                payload=payload,
                db=ctx.db,
                current_user=ctx.current_user,
            )
        except GoogleMapsCostBlocked:
            # A budget failure is not evidence that a day has no availability.
            # Stop this action before querying another day or asking the model
            # to infer a scheduling result from an incomplete search.
            ctx.db.rollback()
            raise
        except HTTPException as exc:
            dias_consultados.append(
                {
                    "data": data_ref.isoformat(),
                    "total": 0,
                    "motivo": str(exc.detail),
                }
            )
            continue

        day_items = result.get("items") if isinstance(result, dict) else []
        day_items = day_items if isinstance(day_items, list) else []
        if criterio:
            inicio_min, fim_min = criterio.limites_horarios()
            inicio_local = datetime.combine(data_ref, time.min, tzinfo=LOCAL_TZ)
            limite_inicio = inicio_local + timedelta(minutes=inicio_min)
            limite_fim = inicio_local + timedelta(minutes=fim_min)
            filtrados = []
            for item in day_items:
                try:
                    item_inicio = _as_local_datetime(datetime.fromisoformat(str(item['inicio']).replace('Z', '+00:00')))
                    item_fim = _as_local_datetime(datetime.fromisoformat(str(item['fim']).replace('Z', '+00:00')))
                    if limite_inicio <= item_inicio < item_fim <= limite_fim:
                        filtrados.append(item)
                except (ValueError, TypeError, KeyError):
                    continue
            day_items = filtrados
        dias_consultados.append(
            {
                "data": data_ref.isoformat(),
                "total": len(day_items),
                "motivo": str(result.get("motivo") or "") if isinstance(result, dict) else "",
            }
        )
        for item in day_items[:4]:
            if not isinstance(item, dict):
                continue
            slots.append(
                {
                    "inicio": item.get("inicio"),
                    "fim": item.get("fim"),
                    "risco": item.get("risco"),
                    "score_operacional": item.get("score"),
                    "deslocamento_total_min": item.get("tempo_deslocamento_total_min"),
                    "destino": item.get("destino_operacional"),
                }
            )
            if len(slots) >= 12:
                break
        if len(slots) >= 12:
            break

    return {
        "ok": True,
        "clinica": {"id": int(clinica_obj.id), "nome": str(clinica_obj.nome)},
        "servico": {
            "id": int(servico_obj.id),
            "nome": str(servico_obj.nome),
            "duracao_minutos": int(servico_obj.duracao_minutos or 30),
        },
        "periodo": {
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "dias_solicitados": dias,
        },
        "preferencia": criterio.model_dump(exclude_none=True) if criterio else None,
        "slots": slots,
        "dias_consultados": dias_consultados,
        "dados_pessoais_incluidos": False,
        "orientacao": (
            "Nenhuma opcao encontrada dentro da preferencia solicitada. Consulte o administrador antes de ampliar o periodo ou turno."
            if criterio and not slots else
            "Os slots sao candidatos operacionais e devem ser confirmados novamente antes de criar um agendamento."
        ),
    }


def consultar_deslocamento_clinicas(
    ctx: AssistenteIAToolContext,
    *,
    origem: str,
    destino: str,
    perfil: str,
) -> dict[str, Any]:
    origem_obj, error = _resolve_named_record(
        ctx.db,
        Clinica,
        origem,
        entity_label="clinica",
    )
    if error:
        return {**error, "campo": "origem"}
    destino_obj, error = _resolve_named_record(
        ctx.db,
        Clinica,
        destino,
        entity_label="clinica",
    )
    if error:
        return {**error, "campo": "destino"}
    perfil_normalizado = _normalize_text(perfil).replace(" ", "_") or "comercial"
    if perfil_normalizado not in {"comercial", "plantao"}:
        return {"ok": False, "error": "Perfil invalido. Use comercial ou plantao."}
    if int(origem_obj.id) == int(destino_obj.id):
        return {
            "ok": True,
            "origem": {"id": int(origem_obj.id), "nome": str(origem_obj.nome)},
            "destino": {"id": int(destino_obj.id), "nome": str(destino_obj.nome)},
            "perfil": perfil_normalizado,
            "distancia_km": 0.0,
            "duracao_min": 0,
            "fonte": "mesma_clinica",
        }
    route = obter_ou_criar_deslocamento(
        ctx.db,
        origem_clinica_id=int(origem_obj.id),
        destino_clinica_id=int(destino_obj.id),
        perfil=perfil_normalizado,
    )
    if route is None:
        return {"ok": False, "error": "Nao foi possivel estimar o deslocamento entre as clinicas."}
    serialized = serialize_deslocamento(route)
    return {
        "ok": True,
        "origem": {"id": int(origem_obj.id), "nome": str(origem_obj.nome)},
        "destino": {"id": int(destino_obj.id), "nome": str(destino_obj.nome)},
        "perfil": perfil_normalizado,
        "distancia_km": serialized.get("distancia_km"),
        "duracao_min": serialized.get("duracao_min"),
        "fonte": serialized.get("fonte"),
        "atualizado_em": serialized.get("updated_at"),
        "orientacao": "Informe que o tempo e uma estimativa operacional e pode variar com o transito.",
    }


def relatorio_debitos_pendentes(
    ctx: AssistenteIAToolContext,
    *,
    clinica: str,
    somente_vencidos: bool,
) -> dict[str, Any]:
    clinica_obj, error = _resolve_named_record(
        ctx.db,
        Clinica,
        clinica,
        entity_label="clinica",
    )
    if error:
        return error

    hoje = datetime.now(LOCAL_TZ).date()
    os_query = ctx.db.query(OrdemServico).filter(
        OrdemServico.clinica_id == clinica_obj.id,
        OrdemServico.status == "Pendente",
    )
    if somente_vencidos:
        os_query = os_query.filter(func.date(OrdemServico.data_atendimento) <= hoje.isoformat())
    orders = os_query.order_by(OrdemServico.data_atendimento.asc(), OrdemServico.id.asc()).limit(200).all()

    service_ids = {int(item.servico_id) for item in orders if item.servico_id}
    service_map = {
        int(item.id): str(item.nome)
        for item in ctx.db.query(Servico).filter(Servico.id.in_(service_ids)).all()
    } if service_ids else {}
    order_items: list[dict[str, Any]] = []
    for item in orders:
        atendimento = _as_local_datetime(item.data_atendimento)
        atendimento_data = atendimento.date() if atendimento else None
        order_items.append(
            {
                "ordem_servico_id": int(item.id),
                "numero_os": str(item.numero_os),
                "data_atendimento": atendimento_data.isoformat() if atendimento_data else None,
                "dias_pendente": max(0, (hoje - atendimento_data).days) if atendimento_data else None,
                "servico": service_map.get(int(item.servico_id), f"Servico #{item.servico_id}"),
                "valor": round(float(item.valor_final or 0), 2),
            }
        )

    account_query = ctx.db.query(ContaReceber).filter(
        ContaReceber.clinica_id == clinica_obj.id,
        ContaReceber.status.in_(["Pendente", "Atrasado"]),
    )
    if somente_vencidos:
        account_query = account_query.filter(func.date(ContaReceber.data_vencimento) < hoje.isoformat())
    accounts = account_query.order_by(ContaReceber.data_vencimento.asc(), ContaReceber.id.asc()).limit(200).all()
    account_items: list[dict[str, Any]] = []
    for item in accounts:
        due = _as_local_datetime(item.data_vencimento)
        due_date = due.date() if due else None
        account_items.append(
            {
                "conta_receber_id": int(item.id),
                "descricao": str(item.descricao or ""),
                "cliente": str(item.cliente or "") or None,
                "vencimento": due_date.isoformat() if due_date else None,
                "dias_em_atraso": max(0, (hoje - due_date).days) if due_date else None,
                "status": str(item.status or "Pendente"),
                "valor": round(float(item.valor or 0), 2),
            }
        )

    total_orders = round(sum(float(item["valor"]) for item in order_items), 2)
    total_accounts = round(sum(float(item["valor"]) for item in account_items), 2)
    return {
        "ok": True,
        "clinica": {"id": int(clinica_obj.id), "nome": str(clinica_obj.nome)},
        "data_referencia": hoje.isoformat(),
        "somente_vencidos": bool(somente_vencidos),
        "ordens_servico_pendentes": {
            "quantidade": len(order_items),
            "total": total_orders,
            "items": order_items[:100],
            "truncado": len(order_items) > 100,
        },
        "contas_receber_pendentes": {
            "quantidade": len(account_items),
            "total": total_accounts,
            "items": account_items[:100],
            "truncado": len(account_items) > 100,
        },
        "total_estimado_sem_deduplicacao": round(total_orders + total_accounts, 2),
        "aviso": "Ordens de servico e contas a receber sao fontes separadas e podem representar o mesmo debito; apresente os subtotais antes do total estimado.",
    }


def consultar_clinica_360(
    ctx: AssistenteIAToolContext,
    *,
    clinica: str,
    periodo_dias: int,
) -> dict[str, Any]:
    clinic, error = _resolve_named_record(
        ctx.db,
        Clinica,
        clinica,
        entity_label="clinica",
    )
    if error:
        return error
    return clinic_360_profile(
        ctx.db,
        int(clinic.id),
        period_days=max(30, min(365, int(periodo_dias or 90))),
    )


def comparar_clinicas_360(
    ctx: AssistenteIAToolContext,
    *,
    clinicas: list[str],
    periodo_dias: int,
) -> dict[str, Any]:
    resolved_ids: list[int] = []
    for requested_name in clinicas:
        clinic, error = _resolve_named_record(
            ctx.db,
            Clinica,
            requested_name,
            entity_label="clinica",
        )
        if error:
            return {**error, "clinica_solicitada": requested_name}
        if int(clinic.id) not in resolved_ids:
            resolved_ids.append(int(clinic.id))
    if len(resolved_ids) < 2:
        return {"ok": False, "error": "Informe ao menos duas clinicas diferentes."}
    return compare_clinics_360(
        ctx.db,
        resolved_ids,
        period_days=max(30, min(365, int(periodo_dias or 90))),
    )


def _agenda_configuration_rules(db: Session) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    config = db.query(Configuracao).order_by(Configuracao.id.asc()).first()
    exceptions = carregar_agenda_excecoes(getattr(config, "agenda_excecoes", None) if config else None)
    weekly = carregar_agenda_semanal(getattr(config, "agenda_semanal", None) if config else None)
    holidays = carregar_agenda_feriados(getattr(config, "agenda_feriados", None) if config else None)
    return exceptions, weekly, holidays


def _agenda_day_window(
    reference_date: date,
    *,
    exceptions: list[dict[str, Any]],
    weekly: dict[str, Any],
    holidays: list[dict[str, Any]],
) -> dict[str, Any]:
    exception = obter_excecao_data(reference_date, exceptions)
    if exception is not None:
        return {
            "data": reference_date.isoformat(),
            "ativo": bool(exception.get("ativo", False)),
            "inicio": str(exception.get("inicio") or DEFAULT_EXCECAO_INICIO),
            "fim": str(exception.get("fim") or DEFAULT_EXCECAO_FIM),
            "motivo": str(exception.get("motivo") or "").strip() or None,
            "fonte": "excecao",
        }

    day_key = str(reference_date.isoweekday())
    day_config = weekly.get(day_key) or DEFAULT_AGENDA_SEMANAL[day_key]
    holiday = obter_feriado(reference_date, holidays)
    return {
        "data": reference_date.isoformat(),
        "ativo": bool(day_config.get("ativo", False)) and holiday is None,
        "inicio": str(day_config.get("inicio") or DEFAULT_AGENDA_SEMANAL[day_key]["inicio"]),
        "fim": str(day_config.get("fim") or DEFAULT_AGENDA_SEMANAL[day_key]["fim"]),
        "motivo": (
            str(holiday.get("descricao") or "").strip() or "Feriado"
            if holiday is not None
            else None
        ),
        "fonte": "feriado" if holiday is not None else "agenda_semanal",
    }


def consultar_funcionamento_agenda(
    ctx: AssistenteIAToolContext,
    *,
    data: str,
) -> dict[str, Any]:
    try:
        reference_date = _parse_iso_date(data)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    exceptions, weekly, holidays = _agenda_configuration_rules(ctx.db)
    window = _agenda_day_window(
        reference_date,
        exceptions=exceptions,
        weekly=weekly,
        holidays=holidays,
    )
    return {
        "ok": True,
        "funcionamento": window,
        "escopo": "agenda geral da FortCordis",
        "orientacao": (
            "A agenda esta aberta no periodo informado."
            if window["ativo"]
            else "A agenda esta fechada na data informada."
        ),
    }


def _hhmm(value: Optional[str], *, field_label: str) -> Optional[str]:
    try:
        parsed = _parse_hhmm(value)
    except ValueError as exc:
        raise ValueError(f"{field_label} invalido. Use HH:MM.") from exc
    return parsed.strftime("%H:%M") if parsed is not None else None


def _hhmm_minutes(value: str) -> int:
    parsed = _parse_hhmm(value)
    if parsed is None:
        raise ValueError("Horario nao informado.")
    return parsed.hour * 60 + parsed.minute


def _agenda_exception_signature(arguments: dict[str, Any]) -> tuple[Any, ...]:
    desired = arguments.get("excecao") if isinstance(arguments.get("excecao"), dict) else {}
    return (
        desired.get("data"),
        bool(desired.get("ativo")),
        desired.get("inicio"),
        desired.get("fim"),
        desired.get("motivo"),
    )


def solicitar_excecao_funcionamento_agenda(
    ctx: AssistenteIAToolContext,
    *,
    data: str,
    ativo: bool,
    inicio: Optional[str],
    fim: Optional[str],
    motivo: Optional[str],
) -> dict[str, Any]:
    if not ctx.current_user.tem_papel("admin"):
        return {"ok": False, "error": "Apenas administradores podem alterar o funcionamento da agenda."}

    try:
        reference_date = _parse_iso_date(data)
        requested_start = _hhmm(inicio, field_label="Horario inicial")
        requested_end = _hhmm(fim, field_label="Horario final")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    today = datetime.now(LOCAL_TZ).date()
    if reference_date < today:
        return {"ok": False, "error": "A excecao de funcionamento nao pode ser criada para uma data passada."}
    if reference_date > today + timedelta(days=370):
        return {"ok": False, "error": "A data deve estar no maximo 370 dias no futuro."}

    current_exceptions, weekly, holidays = _agenda_configuration_rules(ctx.db)
    before = _agenda_day_window(
        reference_date,
        exceptions=current_exceptions,
        weekly=weekly,
        holidays=holidays,
    )
    desired_start = requested_start or str(before.get("inicio") or DEFAULT_EXCECAO_INICIO)
    desired_end = requested_end or str(before.get("fim") or DEFAULT_EXCECAO_FIM)
    try:
        if _hhmm_minutes(desired_start) >= _hhmm_minutes(desired_end):
            return {"ok": False, "error": "O horario final deve ser posterior ao horario inicial."}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    clean_reason = (
        str(motivo or "").strip()[:300]
        or "Ajuste solicitado pelo administrador via Mente FortCordis"
    )
    desired = {
        "data": reference_date.isoformat(),
        "ativo": bool(ativo),
        "inicio": desired_start,
        "fim": desired_end,
        "motivo": clean_reason,
    }
    if (
        bool(before.get("ativo")) == desired["ativo"]
        and str(before.get("inicio")) == desired["inicio"]
        and str(before.get("fim")) == desired["fim"]
    ):
        return {
            "ok": True,
            "changed": False,
            "message": "A agenda ja possui esse funcionamento na data informada.",
            "current": before,
        }

    arguments = {"excecao": desired}
    snapshot = {
        "data": reference_date.isoformat(),
        "antes": before,
        "depois": {**desired, "fonte": "excecao"},
        "agenda_excecoes_antes": current_exceptions,
        "motivo": clean_reason,
    }
    now_utc = datetime.now(timezone.utc)
    existing = (
        ctx.db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.usuario_id == ctx.current_user.id,
            AssistenteIAAcaoPendente.conversa_id == ctx.conversa.id,
            AssistenteIAAcaoPendente.tipo_acao == "update_agenda_exception",
            AssistenteIAAcaoPendente.status == "pending",
        )
        .order_by(AssistenteIAAcaoPendente.created_at.desc())
        .all()
    )
    for action in existing:
        expires_at = _as_utc_datetime(action.expires_at)
        if (
            _agenda_exception_signature(_json_loads(action.argumentos_json, {}))
            == _agenda_exception_signature(arguments)
            and expires_at
            and expires_at > now_utc
        ):
            return {
                "ok": True,
                "requires_approval": True,
                "pending_action": serialize_pending_action(action),
                "message": "Esta alteracao de funcionamento ja aguarda confirmacao.",
            }

    action = AssistenteIAAcaoPendente(
        id=str(uuid.uuid4()),
        conversa_id=ctx.conversa.id,
        usuario_id=int(ctx.current_user.id),
        tipo_acao="update_agenda_exception",
        argumentos_json=_json_dumps(arguments),
        alvo_snapshot_json=_json_dumps(snapshot),
        status="pending",
        expires_at=now_utc + timedelta(minutes=max(5, int(settings.ASSISTENTE_IA_ACTION_TTL_MINUTES))),
    )
    ctx.db.add(action)
    ctx.db.commit()
    ctx.db.refresh(action)
    registrar_auditoria(
        current_user=ctx.current_user,
        modulo="assistente_ia",
        entidade="configuracao_agenda",
        entidade_id=reference_date.isoformat(),
        acao="ASSISTENTE_IA_EXCECAO_AGENDA_SOLICITADA",
        descricao="Mente FortCordis preparou excecao de funcionamento para confirmacao do admin.",
        detalhes={
            "acao_pendente_id": action.id,
            "antes": before,
            "depois": desired,
        },
        request=ctx.request,
    )
    return {
        "ok": True,
        "requires_approval": True,
        "pending_action": serialize_pending_action(action),
        "message": "A alteracao foi preparada e so sera aplicada depois da confirmacao explicita.",
    }


def _record_version(record: Any | None) -> dict[str, Any] | None:
    if record is None:
        return None
    updated_at = getattr(record, "updated_at", None)
    return {
        "id": int(record.id),
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at or ""),
    }


def _contact_numbers(*values: Any) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            raw = str(candidate or "").strip()
            digits = "".join(char for char in raw if char.isdigit())
            key = digits or raw
            if not raw or not key or key in seen:
                continue
            seen.add(key)
            numbers.append(raw)
    return numbers[:10]


def _resolve_patient_record(
    db: Session,
    requested_name: str,
    *,
    tutor: Optional[Tutor],
) -> tuple[Paciente | None, dict[str, Any] | None]:
    filters = [Paciente.tutor_id == tutor.id] if tutor is not None else None
    patient, error = _resolve_named_record(
        db,
        Paciente,
        requested_name,
        entity_label="paciente",
        filters=filters,
    )
    if not error or not isinstance(error.get("matches"), list):
        return patient, error

    patient_ids = [int(item.get("id") or 0) for item in error["matches"] if int(item.get("id") or 0) > 0]
    rows = db.query(Paciente).filter(Paciente.id.in_(patient_ids)).all() if patient_ids else []
    tutor_ids = {int(row.tutor_id) for row in rows if row.tutor_id}
    tutor_map = {
        int(row.id): str(row.nome or "")
        for row in db.query(Tutor).filter(Tutor.id.in_(tutor_ids)).all()
    } if tutor_ids else {}
    by_id = {int(row.id): row for row in rows}
    enriched = []
    for item in error["matches"]:
        row = by_id.get(int(item.get("id") or 0))
        enriched.append(
            {
                **item,
                "tutor": tutor_map.get(int(row.tutor_id)) if row is not None and row.tutor_id else None,
            }
        )
    return patient, {**error, "matches": enriched}


def _build_appointment_candidate(
    *,
    clinic: Optional[Clinica],
    service: Servico,
    patient: Optional[Paciente],
    tutor: Optional[Tutor],
    appointment_type: str,
    origin: str,
    start: datetime,
    reservation_expires_at: Optional[datetime],
    notes: Optional[str],
) -> Agendamento:
    return Agendamento(
        paciente_id=int(patient.id) if patient is not None else None,
        tutor_id=int(tutor.id) if tutor is not None else None,
        clinica_id=int(clinic.id) if clinic is not None else None,
        servico_id=int(service.id),
        origem_atendimento=origin,
        inicio=start,
        fim=start + timedelta(minutes=max(5, int(service.duracao_minutos or 30))),
        status="Reservado" if appointment_type == "reserva" else "Agendado",
        reserva_expira_em=reservation_expires_at,
        observacoes=str(notes or "").strip() or None,
    )


def _validate_appointment_candidate(db: Session, candidate: Agendamento) -> None:
    agenda._validar_regras_origem_agendamento(db, candidate, contexto="preparar o agendamento pela Mente FortCordis")
    agenda._apply_service_duration_if_needed(db, candidate, force_from_service=True)
    agenda._validar_prazo_reserva(candidate)
    agenda._validar_agendamento_no_funcionamento(db, candidate)
    agenda._validar_slot_disponivel(db, candidate)
    agenda._validar_deslocamento_agendamento(
        db,
        candidate,
        confirmar_conflito_deslocamento=False,
    )
    related = agenda._fetch_related_names(db, candidate)
    agenda._validar_paciente_tutor_para_status(
        db,
        candidate,
        status_destino=candidate.status,
        related=related,
    )


def _appointment_creation_snapshot(
    *,
    clinic: Optional[Clinica],
    service: Servico,
    patient: Optional[Paciente],
    tutor: Optional[Tutor],
    candidate: Agendamento,
    recipient_type: str,
) -> dict[str, Any]:
    recipient = clinic if recipient_type == "clinica" else tutor
    recipient_numbers = (
        _contact_numbers(getattr(clinic, "whatsapps", None), getattr(clinic, "telefone", None))
        if recipient_type == "clinica"
        else _contact_numbers(getattr(tutor, "whatsapp", None), getattr(tutor, "telefone", None))
    )
    inicio = _as_local_datetime(candidate.inicio)
    fim = _as_local_datetime(candidate.fim)
    expires_at = _as_local_datetime(candidate.reserva_expira_em)
    return {
        "status": str(candidate.status),
        "tipo": "reserva" if str(candidate.status) == "Reservado" else "agendamento",
        "origem_atendimento": str(candidate.origem_atendimento),
        "inicio": inicio.isoformat() if inicio else None,
        "fim": fim.isoformat() if fim else None,
        "reserva_expira_em": expires_at.isoformat() if expires_at else None,
        "clinica_id": int(clinic.id) if clinic is not None else None,
        "clinica_nome": str(clinic.nome) if clinic is not None else None,
        "servico_id": int(service.id),
        "servico_nome": str(service.nome),
        "duracao_minutos": int(service.duracao_minutos or 30),
        "paciente_id": int(patient.id) if patient is not None else None,
        "paciente_nome": str(patient.nome) if patient is not None else None,
        "paciente_primeiro_nome": (
            str(patient.nome or "").strip().split()[0]
            if patient is not None and str(patient.nome or "").strip()
            else None
        ),
        "tutor_id": int(tutor.id) if tutor is not None else None,
        "tutor_nome": str(tutor.nome) if tutor is not None else None,
        "destinatario_mensagem": {
            "tipo": recipient_type,
            "nome": str(getattr(recipient, "nome", None) or "").strip() or None,
            "telefones": recipient_numbers,
        },
        "referencias": {
            "clinica": _record_version(clinic),
            "servico": _record_version(service),
            "paciente": _record_version(patient),
            "tutor": _record_version(tutor),
        },
    }


def _creation_signature(arguments: dict[str, Any]) -> tuple[Any, ...]:
    return (
        arguments.get("tipo"),
        arguments.get("origem_atendimento"),
        arguments.get("clinica_id"),
        arguments.get("servico_id"),
        arguments.get("paciente_id"),
        arguments.get("tutor_id"),
        arguments.get("inicio"),
        arguments.get("destinatario_mensagem"),
        arguments.get("prazo_confirmacao_horas"),
        arguments.get("observacoes"),
    )


def solicitar_criacao_agendamento(
    ctx: AssistenteIAToolContext,
    *,
    tipo: str,
    origem_atendimento: str,
    clinica: Optional[str],
    tutor: Optional[str],
    paciente: Optional[str],
    servico: str,
    data: str,
    horario: str,
    destinatario_mensagem: str,
    prazo_confirmacao_horas: Optional[float],
    observacoes: Optional[str],
) -> dict[str, Any]:
    if not ctx.current_user.tem_papel("admin"):
        return {"ok": False, "error": "Apenas administradores podem preparar agendamentos."}

    appointment_type = _normalize_text(tipo)
    if appointment_type not in {"agendamento", "reserva"}:
        return {"ok": False, "error": "Tipo invalido. Use agendamento ou reserva."}
    origin = _normalize_text(origem_atendimento).replace(" ", "_") or "clinica_parceira"
    if origin not in {"clinica_parceira", "domiciliar"}:
        return {"ok": False, "error": "Origem invalida. Use clinica_parceira ou domiciliar."}
    recipient_type = _normalize_text(destinatario_mensagem)
    if recipient_type not in {"clinica", "tutor"}:
        return {"ok": False, "error": "Destinatario invalido. Use clinica ou tutor."}

    clinic_obj: Optional[Clinica] = None
    if origin == "clinica_parceira":
        clinic_obj, error = _resolve_named_record(
            ctx.db,
            Clinica,
            str(clinica or ""),
            entity_label="clinica",
        )
        if error:
            return error
    elif recipient_type == "clinica":
        return {"ok": False, "error": "Atendimento domiciliar nao possui clinica destinataria; escolha o tutor."}

    service_obj, error = _resolve_named_record(
        ctx.db,
        Servico,
        servico,
        entity_label="servico",
    )
    if error:
        return error

    tutor_obj: Optional[Tutor] = None
    if str(tutor or "").strip():
        tutor_obj, error = _resolve_named_record(
            ctx.db,
            Tutor,
            str(tutor),
            entity_label="tutor",
            exigir_id=True,
        )
        if error:
            return error

    patient_obj: Optional[Paciente] = None
    if str(paciente or "").strip():
        patient_obj, error = _resolve_patient_record(
            ctx.db,
            str(paciente),
            tutor=tutor_obj,
        )
        if error:
            return error
        if tutor_obj is not None and patient_obj.tutor_id and int(patient_obj.tutor_id) != int(tutor_obj.id):
            return {"ok": False, "error": "O paciente informado nao pertence ao tutor selecionado."}
        if tutor_obj is None and patient_obj.tutor_id:
            tutor_obj = (
                ctx.db.query(Tutor)
                .filter(Tutor.id == int(patient_obj.tutor_id), tutores._filtro_tutor_ativo())
                .first()
            )

    if appointment_type == "agendamento" and patient_obj is None:
        return {"ok": False, "error": "Informe o paciente para criar um agendamento confirmado."}
    if appointment_type == "agendamento" and tutor_obj is None:
        return {"ok": False, "error": "O paciente precisa ter um tutor ativo para criar o agendamento."}
    if origin == "domiciliar" and tutor_obj is None:
        return {"ok": False, "error": "Informe o tutor para o atendimento domiciliar."}
    if recipient_type == "tutor" and tutor_obj is None:
        return {"ok": False, "error": "Informe um tutor para preparar a mensagem ao tutor."}

    try:
        start_date = _parse_iso_date(data)
        start_time = _parse_hhmm(horario)
        if start_time is None:
            raise ValueError("Informe o horario no formato HH:MM.")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    start = datetime.combine(start_date, start_time, tzinfo=LOCAL_TZ)
    now_local = datetime.now(LOCAL_TZ)
    if start <= now_local:
        return {"ok": False, "error": "O horario do agendamento deve estar no futuro."}

    reservation_expires_at: Optional[datetime] = None
    reservation_hours: Optional[float] = None
    if appointment_type == "reserva":
        try:
            reservation_hours = float(prazo_confirmacao_horas or 3)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Prazo de confirmacao invalido."}
        if reservation_hours < 0.5 or reservation_hours > 72:
            return {"ok": False, "error": "O prazo da reserva deve ficar entre 0,5 e 72 horas."}
        reservation_expires_at = now_local + timedelta(hours=reservation_hours)
        if reservation_expires_at >= start:
            return {"ok": False, "error": "O prazo de confirmacao precisa terminar antes do horario reservado."}

    clean_notes = str(observacoes or "").strip()[:2000] or None
    candidate = _build_appointment_candidate(
        clinic=clinic_obj,
        service=service_obj,
        patient=patient_obj,
        tutor=tutor_obj,
        appointment_type=appointment_type,
        origin=origin,
        start=start,
        reservation_expires_at=reservation_expires_at,
        notes=clean_notes,
    )
    try:
        _validate_appointment_candidate(ctx.db, candidate)
    except GoogleMapsCostBlocked:
        ctx.db.rollback()
        raise
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}

    snapshot = _appointment_creation_snapshot(
        clinic=clinic_obj,
        service=service_obj,
        patient=patient_obj,
        tutor=tutor_obj,
        candidate=candidate,
        recipient_type=recipient_type,
    )
    arguments = {
        "tipo": appointment_type,
        "origem_atendimento": origin,
        "clinica_id": int(clinic_obj.id) if clinic_obj is not None else None,
        "servico_id": int(service_obj.id),
        "paciente_id": int(patient_obj.id) if patient_obj is not None else None,
        "tutor_id": int(tutor_obj.id) if tutor_obj is not None else None,
        "inicio": snapshot["inicio"],
        "fim": snapshot["fim"],
        "reserva_expira_em": snapshot["reserva_expira_em"],
        "destinatario_mensagem": recipient_type,
        "prazo_confirmacao_horas": reservation_hours,
        "observacoes": clean_notes,
    }

    now_utc = datetime.now(timezone.utc)
    existing = (
        ctx.db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.usuario_id == ctx.current_user.id,
            AssistenteIAAcaoPendente.conversa_id == ctx.conversa.id,
            AssistenteIAAcaoPendente.tipo_acao == "create_appointment",
            AssistenteIAAcaoPendente.status == "pending",
        )
        .order_by(AssistenteIAAcaoPendente.created_at.desc())
        .all()
    )
    for action in existing:
        expires_at = _as_utc_datetime(action.expires_at)
        if (
            _creation_signature(_json_loads(action.argumentos_json, {})) == _creation_signature(arguments)
            and expires_at
            and expires_at > now_utc
        ):
            return {
                "ok": True,
                "requires_approval": True,
                "pending_action": serialize_pending_action(action),
                "message": "Esta criacao ja esta aguardando confirmacao do administrador.",
            }

    action = AssistenteIAAcaoPendente(
        id=str(uuid.uuid4()),
        conversa_id=ctx.conversa.id,
        usuario_id=int(ctx.current_user.id),
        tipo_acao="create_appointment",
        argumentos_json=_json_dumps(arguments),
        alvo_snapshot_json=_json_dumps(snapshot),
        status="pending",
        expires_at=now_utc + timedelta(minutes=max(5, int(settings.ASSISTENTE_IA_ACTION_TTL_MINUTES))),
    )
    ctx.db.add(action)
    ctx.db.commit()
    ctx.db.refresh(action)
    registrar_auditoria(
        current_user=ctx.current_user,
        modulo="assistente_ia",
        entidade="agendamento",
        acao="ASSISTENTE_IA_AGENDAMENTO_SOLICITADO",
        descricao="Mente FortCordis preparou criacao de horario para confirmacao do admin.",
        detalhes={
            "acao_pendente_id": action.id,
            "tipo": appointment_type,
            "clinica_id": snapshot.get("clinica_id"),
            "servico_id": snapshot.get("servico_id"),
            "paciente_id": snapshot.get("paciente_id"),
            "tutor_id": snapshot.get("tutor_id"),
            "inicio": snapshot.get("inicio"),
            "destinatario_mensagem": recipient_type,
        },
        request=ctx.request,
    )
    return {
        "ok": True,
        "requires_approval": True,
        "pending_action": serialize_pending_action(action),
        "message": "A acao foi preparada. O horario so sera criado depois da confirmacao explicita.",
    }


def _appointment_snapshot(db: Session, appointment: Agendamento) -> dict[str, Any]:
    clinic = db.query(Clinica).filter(Clinica.id == appointment.clinica_id).first() if appointment.clinica_id else None
    service = db.query(Servico).filter(Servico.id == appointment.servico_id).first() if appointment.servico_id else None
    patient = db.query(Paciente).filter(Paciente.id == appointment.paciente_id).first() if appointment.paciente_id else None
    inicio = _as_local_datetime(appointment.inicio)
    fim = _as_local_datetime(appointment.fim)
    return {
        "agendamento_id": int(appointment.id),
        "inicio": inicio.isoformat() if inicio else None,
        "fim": fim.isoformat() if fim else None,
        "status": str(appointment.status or ""),
        "clinica_id": int(appointment.clinica_id) if appointment.clinica_id else None,
        "clinica_nome": str(clinic.nome) if clinic else str(appointment.clinica or ""),
        "servico_id": int(appointment.servico_id) if appointment.servico_id else None,
        "servico_nome": str(service.nome) if service else str(appointment.servico or ""),
        "paciente_id": int(appointment.paciente_id) if appointment.paciente_id else None,
        "tutor_id": int(getattr(appointment, "tutor_id", 0) or 0) or None,
        "paciente_primeiro_nome": (
            str(patient.nome or "").strip().split()[0]
            if patient and str(patient.nome or "").strip()
            else str(appointment.paciente or "").strip().split()[0]
            if str(appointment.paciente or "").strip()
            else None
        ),
    }


def _snapshot_fingerprint(snapshot: dict[str, Any]) -> tuple[Any, ...]:
    return (
        snapshot.get("agendamento_id"),
        snapshot.get("inicio"),
        snapshot.get("fim"),
        snapshot.get("status"),
        snapshot.get("clinica_id"),
        snapshot.get("servico_id"),
    )


def solicitar_exclusao_agendamento(
    ctx: AssistenteIAToolContext,
    *,
    agendamento_id: int,
    motivo: str,
) -> dict[str, Any]:
    if not ctx.current_user.tem_papel("admin"):
        return {"ok": False, "error": "Apenas administradores podem preparar exclusoes."}
    motivo = str(motivo or "").strip()
    if len(motivo) < 5:
        return {"ok": False, "error": "Informe um motivo claro para a exclusao."}

    appointment = ctx.db.query(Agendamento).filter(Agendamento.id == int(agendamento_id)).first()
    if appointment is None:
        return {"ok": False, "error": "Agendamento nao encontrado."}

    now_utc = datetime.now(timezone.utc)
    existing = (
        ctx.db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.usuario_id == ctx.current_user.id,
            AssistenteIAAcaoPendente.conversa_id == ctx.conversa.id,
            AssistenteIAAcaoPendente.tipo_acao == "delete_appointment",
            AssistenteIAAcaoPendente.status == "pending",
        )
        .order_by(AssistenteIAAcaoPendente.created_at.desc())
        .all()
    )
    for action in existing:
        args = _json_loads(action.argumentos_json, {})
        expires_at = _as_utc_datetime(action.expires_at)
        if int(args.get("agendamento_id") or 0) == int(agendamento_id) and expires_at and expires_at > now_utc:
            return {
                "ok": True,
                "requires_approval": True,
                "pending_action": serialize_pending_action(action),
                "message": "Esta exclusao ja esta aguardando confirmacao do administrador.",
            }

    snapshot = _appointment_snapshot(ctx.db, appointment)
    action = AssistenteIAAcaoPendente(
        id=str(uuid.uuid4()),
        conversa_id=ctx.conversa.id,
        usuario_id=int(ctx.current_user.id),
        tipo_acao="delete_appointment",
        argumentos_json=_json_dumps(
            {
                "agendamento_id": int(agendamento_id),
                "motivo": motivo,
            }
        ),
        alvo_snapshot_json=_json_dumps(snapshot),
        status="pending",
        expires_at=now_utc + timedelta(minutes=max(5, int(settings.ASSISTENTE_IA_ACTION_TTL_MINUTES))),
    )
    ctx.db.add(action)
    ctx.db.commit()
    ctx.db.refresh(action)

    registrar_auditoria(
        current_user=ctx.current_user,
        modulo="assistente_ia",
        entidade="agendamento",
        entidade_id=agendamento_id,
        acao="ASSISTENTE_IA_EXCLUSAO_SOLICITADA",
        descricao="Assistente IA preparou exclusao de agendamento para confirmacao do admin.",
        detalhes={
            "acao_pendente_id": action.id,
            "motivo": motivo,
            "snapshot": snapshot,
        },
        request=ctx.request,
    )
    return {
        "ok": True,
        "requires_approval": True,
        "pending_action": serialize_pending_action(action),
        "message": "A exclusao foi apenas preparada. O agendamento continua intacto ate a confirmacao explicita.",
    }


def _prepare_pending_action(
    ctx: AssistenteIAToolContext,
    *,
    action_type: str,
    arguments: dict[str, Any],
    snapshot: dict[str, Any],
    audit_entity: str,
    audit_entity_id: Any,
    audit_description: str,
) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    signature = _json_dumps(arguments)
    existing = (
        ctx.db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.usuario_id == ctx.current_user.id,
            AssistenteIAAcaoPendente.conversa_id == ctx.conversa.id,
            AssistenteIAAcaoPendente.tipo_acao == action_type,
            AssistenteIAAcaoPendente.status == "pending",
        )
        .order_by(AssistenteIAAcaoPendente.created_at.desc())
        .all()
    )
    for row in existing:
        expires_at = _as_utc_datetime(row.expires_at)
        if row.argumentos_json == signature and expires_at and expires_at > now_utc:
            return {
                "ok": True,
                "requires_approval": True,
                "pending_action": serialize_pending_action(row),
                "message": "Esta acao ja esta aguardando confirmacao do administrador.",
            }
    action = AssistenteIAAcaoPendente(
        id=str(uuid.uuid4()),
        conversa_id=ctx.conversa.id,
        usuario_id=int(ctx.current_user.id),
        tipo_acao=action_type,
        argumentos_json=signature,
        alvo_snapshot_json=_json_dumps(snapshot),
        status="pending",
        expires_at=now_utc + timedelta(minutes=max(5, int(settings.ASSISTENTE_IA_ACTION_TTL_MINUTES))),
    )
    ctx.db.add(action)
    ctx.db.commit()
    ctx.db.refresh(action)
    registrar_auditoria(
        current_user=ctx.current_user,
        modulo="assistente_ia",
        entidade=audit_entity,
        entidade_id=audit_entity_id,
        acao="ASSISTENTE_IA_ACAO_SOLICITADA",
        descricao=audit_description,
        detalhes={"acao_pendente_id": action.id, "tipo_acao": action_type, "snapshot": snapshot},
        request=ctx.request,
    )
    return {
        "ok": True,
        "requires_approval": True,
        "pending_action": serialize_pending_action(action),
        "message": "A acao foi preparada e so sera executada depois da confirmacao explicita.",
    }


def solicitar_vinculo_paciente_reserva(
    ctx: AssistenteIAToolContext,
    *,
    agendamento_id: int,
    tutor: str,
    paciente: str,
) -> dict[str, Any]:
    if not ctx.current_user.tem_papel("admin"):
        return {"ok": False, "error": "Apenas administradores podem preparar a vinculacao."}
    appointment = ctx.db.query(Agendamento).filter(Agendamento.id == int(agendamento_id)).first()
    if appointment is None:
        return {"ok": False, "error": "Agendamento nao encontrado."}
    if str(appointment.status or "") != "Reservado":
        return {"ok": False, "error": "Apenas uma reserva ativa pode receber paciente por esta ferramenta."}
    if appointment.paciente_id:
        return {"ok": False, "error": "A reserva ja possui paciente vinculado."}

    tutor_obj, error = _resolve_named_record(
        ctx.db,
        Tutor,
        tutor,
        entity_label="tutor",
        exigir_id=True,
    )
    if error:
        return error
    patient_obj, error = _resolve_patient_record(
        ctx.db,
        paciente,
        tutor=tutor_obj,
    )
    if error:
        return error
    if patient_obj.tutor_id and int(patient_obj.tutor_id) != int(tutor_obj.id):
        return {"ok": False, "error": "O paciente informado nao pertence ao tutor selecionado."}

    before = _appointment_snapshot(ctx.db, appointment)
    snapshot = {
        "before": before,
        "after": {
            **before,
            "paciente_id": int(patient_obj.id),
            "paciente_primeiro_nome": str(patient_obj.nome or "").strip().split()[0],
            "tutor_id": int(tutor_obj.id),
            "tutor_nome": str(tutor_obj.nome),
        },
        "referencias": {
            "paciente": _record_version(patient_obj),
            "tutor": _record_version(tutor_obj),
        },
    }
    return _prepare_pending_action(
        ctx,
        action_type="attach_patient_to_reservation",
        arguments={
            "agendamento_id": int(appointment.id),
            "paciente_id": int(patient_obj.id),
            "tutor_id": int(tutor_obj.id),
        },
        snapshot=snapshot,
        audit_entity="agendamento",
        audit_entity_id=appointment.id,
        audit_description="Mente FortCordis preparou o vinculo de paciente a uma reserva.",
    )


def solicitar_remarcacao_agendamento(
    ctx: AssistenteIAToolContext,
    *,
    agendamento_id: int,
    data: str,
    horario: str,
    motivo: str,
) -> dict[str, Any]:
    appointment = ctx.db.query(Agendamento).filter(Agendamento.id == int(agendamento_id)).first()
    if appointment is None:
        return {"ok": False, "error": "Agendamento nao encontrado."}
    try:
        reference = _parse_iso_date(data)
        hour = _parse_hhmm(horario)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if hour is None:
        return {"ok": False, "error": "Informe o novo horario no formato HH:MM."}
    start = datetime.combine(reference, hour, tzinfo=LOCAL_TZ)
    if start <= datetime.now(LOCAL_TZ):
        return {"ok": False, "error": "O novo horario deve estar no futuro."}
    old_start = _as_local_datetime(appointment.inicio)
    old_end = _as_local_datetime(appointment.fim)
    duration = (old_end - old_start) if old_start and old_end and old_end > old_start else timedelta(minutes=30)
    end = start + duration
    candidate = Agendamento(
        id=appointment.id,
        paciente_id=appointment.paciente_id,
        tutor_id=getattr(appointment, "tutor_id", None),
        clinica_id=appointment.clinica_id,
        servico_id=appointment.servico_id,
        origem_atendimento=appointment.origem_atendimento,
        inicio=start,
        fim=end,
        status=appointment.status,
        reserva_expira_em=appointment.reserva_expira_em,
    )
    try:
        agenda._validar_agendamento_no_funcionamento(ctx.db, candidate)
        agenda._validar_slot_disponivel(ctx.db, candidate, agendamento_id_excluir=int(appointment.id))
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    before = _appointment_snapshot(ctx.db, appointment)
    after = {**before, "inicio": start.isoformat(), "fim": end.isoformat()}
    return _prepare_pending_action(
        ctx,
        action_type="reschedule_appointment",
        arguments={
            "agendamento_id": int(appointment.id),
            "inicio": start.isoformat(),
            "fim": end.isoformat(),
            "motivo": (str(motivo or "").strip() or "Remarcacao solicitada pelo administrador")[:500],
        },
        snapshot={"before": before, "after": after},
        audit_entity="agendamento",
        audit_entity_id=appointment.id,
        audit_description="Mente FortCordis preparou remarcacao de agendamento.",
    )


def solicitar_cancelamento_agendamento(
    ctx: AssistenteIAToolContext,
    *,
    agendamento_id: int,
    motivo: str,
) -> dict[str, Any]:
    appointment = ctx.db.query(Agendamento).filter(Agendamento.id == int(agendamento_id)).first()
    if appointment is None:
        return {"ok": False, "error": "Agendamento nao encontrado."}
    if str(appointment.status or "") == "Cancelado":
        return {"ok": True, "changed": False, "message": "O agendamento ja esta cancelado."}
    return _prepare_pending_action(
        ctx,
        action_type="cancel_appointment",
        arguments={
            "agendamento_id": int(appointment.id),
            "motivo": (str(motivo or "").strip() or "Cancelamento solicitado pelo administrador")[:500],
        },
        snapshot=_appointment_snapshot(ctx.db, appointment),
        audit_entity="agendamento",
        audit_entity_id=appointment.id,
        audit_description="Mente FortCordis preparou cancelamento de agendamento.",
    )


def listar_bloqueios_agenda(
    ctx: AssistenteIAToolContext,
    *,
    data_inicio: str,
    dias: int,
) -> dict[str, Any]:
    try:
        start_date = _parse_iso_date(data_inicio)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    end_date = start_date + timedelta(days=max(1, min(31, int(dias or 7))))
    items = []
    for row in ctx.db.query(AgendaBloqueio).filter(AgendaBloqueio.ativo.is_(True)).all():
        start = _as_local_datetime(row.inicio)
        end = _as_local_datetime(row.fim)
        if start is None or end is None or start.date() >= end_date or end.date() < start_date:
            continue
        items.append({
            "bloqueio_id": row.id,
            "inicio": start.isoformat(),
            "fim": end.isoformat(),
            "motivo": row.motivo,
        })
    items.sort(key=lambda item: item["inicio"])
    return {"ok": True, "periodo": {"inicio": start_date.isoformat(), "fim": end_date.isoformat()}, "items": items}


def solicitar_bloqueio_agenda(
    ctx: AssistenteIAToolContext,
    *,
    data: str,
    inicio: str,
    fim: str,
    motivo: str,
) -> dict[str, Any]:
    try:
        reference = _parse_iso_date(data)
        start_time = _parse_hhmm(inicio)
        end_time = _parse_hhmm(fim)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if start_time is None or end_time is None:
        return {"ok": False, "error": "Informe inicio e fim no formato HH:MM."}
    start = datetime.combine(reference, start_time, tzinfo=LOCAL_TZ)
    end = datetime.combine(reference, end_time, tzinfo=LOCAL_TZ)
    if end <= start:
        return {"ok": False, "error": "O fim do bloqueio deve ser posterior ao inicio."}
    if start <= datetime.now(LOCAL_TZ):
        return {"ok": False, "error": "O bloqueio deve comecar no futuro."}
    candidate = Agendamento(inicio=start, fim=end, status="Agendado")
    try:
        agenda._validar_slot_disponivel(ctx.db, candidate)
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    block_id = str(uuid.uuid4())
    target = {
        "bloqueio_id": block_id,
        "inicio": start.isoformat(),
        "fim": end.isoformat(),
        "motivo": (str(motivo or "").strip() or "Bloqueio solicitado pelo administrador")[:500],
    }
    return _prepare_pending_action(
        ctx,
        action_type="create_agenda_block",
        arguments=target,
        snapshot=target,
        audit_entity="agenda_bloqueio",
        audit_entity_id=block_id,
        audit_description="Mente FortCordis preparou bloqueio de slot da agenda.",
    )


def solicitar_liberacao_bloqueio_agenda(
    ctx: AssistenteIAToolContext,
    *,
    bloqueio_id: str,
    motivo: str,
) -> dict[str, Any]:
    row = ctx.db.query(AgendaBloqueio).filter(
        AgendaBloqueio.id == str(bloqueio_id),
        AgendaBloqueio.ativo.is_(True),
    ).first()
    if row is None:
        return {"ok": False, "error": "Bloqueio ativo nao encontrado."}
    snapshot = {
        "bloqueio_id": row.id,
        "inicio": _as_local_datetime(row.inicio).isoformat() if _as_local_datetime(row.inicio) else None,
        "fim": _as_local_datetime(row.fim).isoformat() if _as_local_datetime(row.fim) else None,
        "motivo": row.motivo,
        "ativo": bool(row.ativo),
    }
    return _prepare_pending_action(
        ctx,
        action_type="release_agenda_block",
        arguments={"bloqueio_id": row.id, "motivo": str(motivo or "").strip()[:500] or None},
        snapshot=snapshot,
        audit_entity="agenda_bloqueio",
        audit_entity_id=row.id,
        audit_description="Mente FortCordis preparou liberacao de bloqueio da agenda.",
    )


def solicitar_atualizacao_whatsapps_clinica(
    ctx: AssistenteIAToolContext,
    *,
    clinica: str,
    whatsapps: list[str],
    motivo: str,
) -> dict[str, Any]:
    clinic, error = _resolve_named_record(ctx.db, Clinica, clinica, entity_label="clinica")
    if error:
        return error
    try:
        payload = clinicas.ClinicaWhatsappsUpdate(whatsapps=whatsapps)
    except Exception as exc:
        return {"ok": False, "error": f"WhatsApps invalidos: {exc}"}
    before = _contact_numbers(getattr(clinic, "whatsapps", None))
    after = list(payload.whatsapps)
    if before == after:
        return {"ok": True, "changed": False, "message": "A clinica ja possui esses WhatsApps."}
    snapshot = {
        "clinica_id": int(clinic.id),
        "clinica_nome": str(clinic.nome),
        "whatsapps_antes": before,
        "whatsapps_depois": after,
        "versao": _record_version(clinic),
    }
    return _prepare_pending_action(
        ctx,
        action_type="update_clinic_whatsapps",
        arguments={
            "clinica_id": int(clinic.id),
            "whatsapps": after,
            "motivo": str(motivo or "").strip()[:500] or None,
        },
        snapshot=snapshot,
        audit_entity="clinica",
        audit_entity_id=clinic.id,
        audit_description="Mente FortCordis preparou atualizacao de WhatsApps da clinica.",
    )


def serialize_pending_action(action: AssistenteIAAcaoPendente) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "conversation_id": str(action.conversa_id),
        "type": str(action.tipo_acao),
        "status": str(action.status),
        "arguments": _json_loads(action.argumentos_json, {}),
        "target": _json_loads(action.alvo_snapshot_json, {}),
        "result": _json_loads(action.resultado_json, None),
        "expires_at": action.expires_at.isoformat() if action.expires_at else None,
        "decided_at": action.decided_at.isoformat() if action.decided_at else None,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


def _stored_datetime(value: Any, *, field_label: str) -> datetime:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"{field_label} da acao preparada e invalido.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _load_creation_records(
    db: Session,
    arguments: dict[str, Any],
) -> tuple[Optional[Clinica], Servico, Optional[Paciente], Optional[Tutor]]:
    clinic_id = int(arguments.get("clinica_id") or 0)
    service_id = int(arguments.get("servico_id") or 0)
    patient_id = int(arguments.get("paciente_id") or 0)
    tutor_id = int(arguments.get("tutor_id") or 0)

    clinic = (
        db.query(Clinica).filter(Clinica.id == clinic_id, Clinica.ativo.in_([True, 1])).first()
        if clinic_id > 0
        else None
    )
    service = (
        db.query(Servico).filter(Servico.id == service_id, Servico.ativo.in_([True, 1])).first()
        if service_id > 0
        else None
    )
    patient = (
        db.query(Paciente).filter(Paciente.id == patient_id, Paciente.ativo.in_([True, 1])).first()
        if patient_id > 0
        else None
    )
    tutor = (
        db.query(Tutor).filter(Tutor.id == tutor_id, tutores._filtro_tutor_ativo()).first()
        if tutor_id > 0
        else None
    )
    if service is None:
        raise HTTPException(status_code=409, detail="O servico da acao preparada nao esta mais ativo.")
    if clinic_id > 0 and clinic is None:
        raise HTTPException(status_code=409, detail="A clinica da acao preparada nao esta mais ativa.")
    if patient_id > 0 and patient is None:
        raise HTTPException(status_code=409, detail="O paciente da acao preparada nao esta mais ativo.")
    if tutor_id > 0 and tutor is None:
        raise HTTPException(status_code=409, detail="O tutor da acao preparada nao esta mais ativo.")
    if patient is not None and tutor is not None and patient.tutor_id and int(patient.tutor_id) != int(tutor.id):
        raise HTTPException(status_code=409, detail="O vinculo entre paciente e tutor mudou depois da solicitacao.")
    return clinic, service, patient, tutor


def _references_snapshot(
    clinic: Optional[Clinica],
    service: Servico,
    patient: Optional[Paciente],
    tutor: Optional[Tutor],
) -> dict[str, Any]:
    return {
        "clinica": _record_version(clinic),
        "servico": _record_version(service),
        "paciente": _record_version(patient),
        "tutor": _record_version(tutor),
    }


def _format_message_date(value: datetime) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%d/%m/%Y")


def _format_message_datetime(value: Optional[datetime]) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%d/%m/%Y às %H:%M") if value is not None else ""


def _build_manual_appointment_message(
    *,
    appointment_type: str,
    start: datetime,
    reservation_expires_at: Optional[datetime],
    service: Servico,
    patient: Optional[Paciente],
    tutor: Optional[Tutor],
    clinic: Optional[Clinica],
) -> str:
    patient_name = str(getattr(patient, "nome", None) or "").strip()
    patient_label = f"{patient_name} ({int(patient.id)})" if patient is not None and patient_name else "Pendente"
    tutor_label = str(getattr(tutor, "nome", None) or "").strip() or "Pendente"
    clinic_label = str(getattr(clinic, "nome", None) or "").strip() or "Pendente"
    title = "*RESERVA DE HORÁRIO* 🐶 🐱" if appointment_type == "reserva" else "*AGENDAMENTO* 🐶 🐱"
    lines = [
        title,
        "",
        "*Médico Veterinário:* Dr Martiniano",
        f"*Atendimento:* {str(service.nome or '').strip() or 'Pendente'}",
        f"*Data:* {_format_message_date(start)}",
        f"*Horário:* {start.astimezone(LOCAL_TZ).strftime('%H:%M')}",
        f"*Paciente:* {patient_label}",
        f"*Tutor:* {tutor_label}",
        "*Especialista:* Cardiologista",
        f"*Clinica:* {clinic_label}",
        "",
    ]
    if appointment_type == "reserva":
        lines.extend(
            [
                f"⚠️ *ATENÇÃO:* Confirme esta reserva até {_format_message_datetime(reservation_expires_at)}.",
                "Sem confirmação até esse prazo, o horário voltará a ficar disponível para outros clientes.",
            ]
        )
    else:
        lines.append("✅ *CONFIRMAÇÃO:* O horário solicitado foi agendado.")
    return "\n".join(lines)


def _invalidate_pending_action(
    db: Session,
    action: AssistenteIAAcaoPendente,
    *,
    now_utc: datetime,
    reason: str,
    detail: str,
) -> None:
    action.status = "invalidated"
    action.decided_at = now_utc
    action.resultado_json = _json_dumps({"ok": False, "reason": reason, "detail": detail})
    db.add(action)
    db.commit()


def _approve_appointment_creation(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    try:
        clinic, service, patient, tutor = _load_creation_records(db, arguments)
    except HTTPException as exc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="reference_changed",
            detail=str(exc.detail),
        )
        raise

    if _references_snapshot(clinic, service, patient, tutor) != snapshot.get("referencias"):
        detail = "Clinica, servico, paciente ou tutor mudou depois da solicitacao. Revise e solicite novamente."
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="reference_changed",
            detail=detail,
        )
        raise HTTPException(status_code=409, detail=detail)

    appointment_type = str(arguments.get("tipo") or "").strip()
    start = _stored_datetime(arguments.get("inicio"), field_label="Horario")
    end = _stored_datetime(arguments.get("fim"), field_label="Horario final")
    reservation_expires_at = (
        _stored_datetime(arguments.get("reserva_expira_em"), field_label="Prazo da reserva")
        if arguments.get("reserva_expira_em")
        else None
    )
    payload = AgendamentoCreate(
        paciente_id=int(patient.id) if patient is not None else None,
        tutor_id=int(tutor.id) if tutor is not None else None,
        clinica_id=int(clinic.id) if clinic is not None else None,
        servico_id=int(service.id),
        origem_atendimento=str(arguments.get("origem_atendimento") or "clinica_parceira"),
        inicio=start,
        fim=end,
        status="Reservado" if appointment_type == "reserva" else "Agendado",
        reserva_expira_em=reservation_expires_at,
        observacoes=str(arguments.get("observacoes") or "").strip() or None,
        confirmar_conflito_deslocamento=False,
        excecao_operacional_concedida=False,
    )

    action.status = "processing"
    action.decided_at = now_utc
    db.add(action)
    db.flush()
    try:
        created = agenda.criar_agendamento(
            agendamento=payload,
            request=request,
            db=db,
            current_user=current_user,
        )
    except GoogleMapsCostBlocked:
        # Keep the operational approval pending and discard any uncommitted
        # appointment/cache writes. The financial grant is already consumed.
        db.rollback()
        raise
    except HTTPException as exc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="agenda_validation_failed",
            detail=str(exc.detail),
        )
        raise HTTPException(
            status_code=409,
            detail=f"A agenda mudou ou a regra operacional bloqueou a criacao: {exc.detail}",
        ) from exc

    recipient_type = str(arguments.get("destinatario_mensagem") or "clinica")
    recipient = clinic if recipient_type == "clinica" else tutor
    phones = (
        _contact_numbers(getattr(clinic, "whatsapps", None), getattr(clinic, "telefone", None))
        if recipient_type == "clinica"
        else _contact_numbers(getattr(tutor, "whatsapp", None), getattr(tutor, "telefone", None))
    )
    message = _build_manual_appointment_message(
        appointment_type=appointment_type,
        start=start,
        reservation_expires_at=reservation_expires_at,
        service=service,
        patient=patient,
        tutor=tutor,
        clinic=clinic,
    )
    created_payload = created if isinstance(created, dict) else {"id": getattr(created, "id", None)}
    action.status = "executed"
    action.executed_at = now_utc
    action.resultado_json = _json_dumps(
        {
            "ok": True,
            "decision": "approved",
            "message": "Reserva criada com sucesso." if appointment_type == "reserva" else "Agendamento criado com sucesso.",
            "observation": str(observation or "").strip() or None,
            "agendamento": created_payload,
            "comunicacao": {
                "destinatario_tipo": recipient_type,
                "destinatario_nome": str(getattr(recipient, "nome", None) or "").strip() or None,
                "telefones": phones,
                "mensagem": message,
                "envio_manual": True,
            },
        }
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="acao_pendente",
        entidade_id=action.id,
        acao="ASSISTENTE_IA_ACAO_EXECUTADA",
        descricao="Administrador aprovou criacao de horario preparada pela Mente FortCordis.",
        detalhes={
            "tipo_acao": action.tipo_acao,
            "tipo_agendamento": appointment_type,
            "agendamento_id": created_payload.get("id"),
            "destinatario_mensagem": recipient_type,
            "observacao": observation,
        },
        request=request,
    )
    return serialize_pending_action(action)


def _approve_agenda_exception_update(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    desired = arguments.get("excecao") if isinstance(arguments.get("excecao"), dict) else {}
    if not desired.get("data"):
        detail = "A excecao preparada nao possui uma data valida."
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="invalid_arguments",
            detail=detail,
        )
        raise HTTPException(status_code=409, detail=detail)

    current_exceptions, _weekly, _holidays = _agenda_configuration_rules(db)
    expected_exceptions = snapshot.get("agenda_excecoes_antes")
    if not isinstance(expected_exceptions, list) or current_exceptions != expected_exceptions:
        detail = "As excecoes da agenda mudaram depois da solicitacao. Revise e solicite novamente."
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="agenda_configuration_changed",
            detail=detail,
        )
        raise HTTPException(status_code=409, detail=detail)

    date_iso = str(desired["data"])
    merged = [item for item in current_exceptions if str(item.get("data")) != date_iso]
    merged.append(
        {
            "data": date_iso,
            "ativo": bool(desired.get("ativo")),
            "inicio": str(desired.get("inicio") or DEFAULT_EXCECAO_INICIO),
            "fim": str(desired.get("fim") or DEFAULT_EXCECAO_FIM),
            "motivo": str(desired.get("motivo") or "").strip(),
        }
    )
    merged.sort(key=lambda item: str(item.get("data") or ""))

    action.status = "processing"
    action.decided_at = now_utc
    db.add(action)
    db.flush()
    try:
        configuracoes.atualizar_configuracoes(
            dados={"agenda_excecoes": merged},
            db=db,
            current_user=current_user,
        )
    except HTTPException as exc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="agenda_configuration_failed",
            detail=str(exc.detail),
        )
        raise HTTPException(
            status_code=409,
            detail=f"Nao foi possivel alterar o funcionamento da agenda: {exc.detail}",
        ) from exc

    action.status = "executed"
    action.executed_at = now_utc
    action.resultado_json = _json_dumps(
        {
            "ok": True,
            "decision": "approved",
            "message": "Funcionamento excepcional da agenda atualizado com sucesso.",
            "observation": str(observation or "").strip() or None,
            "agenda_excecao": desired,
        }
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="configuracao_agenda",
        entidade_id=date_iso,
        acao="ASSISTENTE_IA_ACAO_EXECUTADA",
        descricao="Administrador aprovou excecao de funcionamento preparada pela Mente FortCordis.",
        detalhes={
            "tipo_acao": action.tipo_acao,
            "antes": snapshot.get("antes"),
            "depois": desired,
            "observacao": observation,
        },
        request=request,
    )
    return serialize_pending_action(action)


def _mark_action_executed(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    message: str,
    result: dict[str, Any],
    observation: Optional[str],
) -> dict[str, Any]:
    action.status = "executed"
    action.decided_at = action.decided_at or now_utc
    action.executed_at = now_utc
    action.resultado_json = _json_dumps(
        {"ok": True, "decision": "approved", "message": message, "observation": observation, **result}
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="acao_pendente",
        entidade_id=action.id,
        acao="ASSISTENTE_IA_ACAO_EXECUTADA",
        descricao="Administrador aprovou e executou uma acao preparada pela Mente FortCordis.",
        detalhes={"tipo_acao": action.tipo_acao, "observacao": observation, **result},
        request=request,
    )
    return serialize_pending_action(action)


def _current_appointment_or_invalidate(
    db: Session,
    action: AssistenteIAAcaoPendente,
    *,
    now_utc: datetime,
    snapshot: dict[str, Any],
) -> Agendamento:
    arguments = _json_loads(action.argumentos_json, {})
    appointment_id = int(arguments.get("agendamento_id") or 0)
    appointment = db.query(Agendamento).filter(Agendamento.id == appointment_id).first()
    expected = snapshot.get("before") if isinstance(snapshot.get("before"), dict) else snapshot
    if appointment is None:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="target_missing",
            detail="O agendamento nao existe mais.",
        )
        raise HTTPException(status_code=409, detail="O agendamento nao existe mais; a acao foi invalidada.")
    if _snapshot_fingerprint(_appointment_snapshot(db, appointment)) != _snapshot_fingerprint(expected):
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="target_changed",
            detail="O agendamento mudou depois da solicitacao.",
        )
        raise HTTPException(status_code=409, detail="O agendamento mudou. Revise e solicite novamente.")
    return appointment


def _approve_reschedule_or_cancel(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    appointment = _current_appointment_or_invalidate(db, action, now_utc=now_utc, snapshot=snapshot)
    action.status = "processing"
    action.decided_at = now_utc
    db.add(action)
    db.flush()
    try:
        if action.tipo_acao == "reschedule_appointment":
            updated = agenda.atualizar_agendamento(
                agendamento_id=int(appointment.id),
                agendamento=AgendamentoUpdate(
                    inicio=_stored_datetime(arguments.get("inicio"), field_label="Novo horario"),
                    fim=_stored_datetime(arguments.get("fim"), field_label="Novo horario final"),
                ),
                request=request,
                db=db,
                current_user=current_user,
            )
            message = "Agendamento remarcado com sucesso."
        else:
            updated = agenda.atualizar_status(
                agendamento_id=int(appointment.id),
                request=request,
                status="Cancelado",
                tipo_horario="comercial",
                db=db,
                current_user=current_user,
            )
            message = "Agendamento cancelado com sucesso."
    except GoogleMapsCostBlocked:
        # Invalidating the IA action would commit the appointment mutation from
        # the endpoint as well. Roll it back and retain the pending approval.
        db.rollback()
        raise
    except HTTPException as exc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="agenda_validation_failed",
            detail=str(exc.detail),
        )
        raise HTTPException(status_code=409, detail=f"A agenda mudou ou bloqueou a operacao: {exc.detail}") from exc
    payload = updated if isinstance(updated, dict) else {"id": getattr(updated, "id", appointment.id)}
    return _mark_action_executed(
        db=db,
        current_user=current_user,
        request=request,
        action=action,
        now_utc=now_utc,
        message=message,
        result={"agendamento": payload, "motivo": arguments.get("motivo")},
        observation=observation,
    )


def _approve_create_agenda_block(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    start = _stored_datetime(arguments.get("inicio"), field_label="Inicio do bloqueio")
    end = _stored_datetime(arguments.get("fim"), field_label="Fim do bloqueio")
    candidate = Agendamento(inicio=start, fim=end, status="Agendado")
    try:
        agenda._validar_slot_disponivel(db, candidate)
    except HTTPException as exc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="slot_changed",
            detail=str(exc.detail),
        )
        raise HTTPException(status_code=409, detail=f"O slot nao pode mais ser bloqueado: {exc.detail}") from exc
    block_id = str(arguments.get("bloqueio_id") or uuid.uuid4())
    if db.query(AgendaBloqueio).filter(AgendaBloqueio.id == block_id).first():
        _invalidate_pending_action(db, action, now_utc=now_utc, reason="duplicate_block", detail="Bloqueio ja existe.")
        raise HTTPException(status_code=409, detail="O bloqueio ja existe.")
    row = AgendaBloqueio(
        id=block_id,
        inicio=start,
        fim=end,
        motivo=str(arguments.get("motivo") or "Bloqueio administrativo"),
        ativo=True,
        criado_por_id=int(current_user.id),
        criado_por_nome=str(current_user.nome or "Admin"),
    )
    db.add(row)
    db.commit()
    return _mark_action_executed(
        db=db,
        current_user=current_user,
        request=request,
        action=action,
        now_utc=now_utc,
        message="Slot bloqueado com sucesso.",
        result={"bloqueio": {"id": row.id, "inicio": start.isoformat(), "fim": end.isoformat(), "motivo": row.motivo}},
        observation=observation,
    )


def _approve_release_agenda_block(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    row = db.query(AgendaBloqueio).filter(AgendaBloqueio.id == arguments.get("bloqueio_id")).first()
    current = {
        "bloqueio_id": row.id if row else None,
        "inicio": _as_local_datetime(row.inicio).isoformat() if row and _as_local_datetime(row.inicio) else None,
        "fim": _as_local_datetime(row.fim).isoformat() if row and _as_local_datetime(row.fim) else None,
        "motivo": row.motivo if row else None,
        "ativo": bool(row.ativo) if row else False,
    }
    if row is None or current != snapshot:
        _invalidate_pending_action(db, action, now_utc=now_utc, reason="target_changed", detail="O bloqueio mudou.")
        raise HTTPException(status_code=409, detail="O bloqueio mudou ou ja foi liberado.")
    row.ativo = False
    row.liberado_por_id = int(current_user.id)
    row.liberado_em = now_utc
    db.add(row)
    db.commit()
    return _mark_action_executed(
        db=db,
        current_user=current_user,
        request=request,
        action=action,
        now_utc=now_utc,
        message="Bloqueio liberado com sucesso.",
        result={"bloqueio": {**current, "ativo": False}},
        observation=observation,
    )


def _approve_update_clinic_whatsapps(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    clinic = db.query(Clinica).filter(Clinica.id == int(arguments.get("clinica_id") or 0)).first()
    if clinic is None or _record_version(clinic) != snapshot.get("versao"):
        _invalidate_pending_action(db, action, now_utc=now_utc, reason="target_changed", detail="A clinica mudou.")
        raise HTTPException(status_code=409, detail="O cadastro da clinica mudou. Revise e solicite novamente.")
    updated = clinicas.atualizar_whatsapps_clinica(
        clinica_id=int(clinic.id),
        payload=clinicas.ClinicaWhatsappsUpdate(whatsapps=arguments.get("whatsapps") or []),
        db=db,
        current_user=current_user,
    )
    return _mark_action_executed(
        db=db,
        current_user=current_user,
        request=request,
        action=action,
        now_utc=now_utc,
        message="WhatsApps da clinica atualizados com sucesso.",
        result={
            "clinica": updated if isinstance(updated, dict) else {"id": clinic.id},
            "whatsapps_antes": snapshot.get("whatsapps_antes"),
            "whatsapps_depois": arguments.get("whatsapps") or [],
        },
        observation=observation,
    )


def _approve_attach_patient_to_reservation(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action: AssistenteIAAcaoPendente,
    now_utc: datetime,
    observation: Optional[str],
) -> dict[str, Any]:
    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    appointment = _current_appointment_or_invalidate(
        db,
        action,
        now_utc=now_utc,
        snapshot=snapshot,
    )
    expected_before = snapshot.get("before") if isinstance(snapshot.get("before"), dict) else {}
    if (
        int(appointment.paciente_id or 0) != int(expected_before.get("paciente_id") or 0)
        or int(getattr(appointment, "tutor_id", 0) or 0) != int(expected_before.get("tutor_id") or 0)
    ):
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="target_changed",
            detail="O vinculo da reserva mudou depois da solicitacao.",
        )
        raise HTTPException(status_code=409, detail="A reserva mudou. Revise e solicite novamente.")
    expires_at = _as_utc_datetime(getattr(appointment, "reserva_expira_em", None))
    if expires_at is not None and expires_at <= now_utc:
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="reservation_expired",
            detail="A reserva expirou antes da confirmacao.",
        )
        raise HTTPException(status_code=409, detail="A reserva expirou. Crie um novo agendamento.")

    patient = (
        db.query(Paciente)
        .filter(
            Paciente.id == int(arguments.get("paciente_id") or 0),
            Paciente.ativo.in_([True, 1]),
        )
        .first()
    )
    tutor = (
        db.query(Tutor)
        .filter(
            Tutor.id == int(arguments.get("tutor_id") or 0),
            tutores._filtro_tutor_ativo(),
        )
        .first()
    )
    references = snapshot.get("referencias") if isinstance(snapshot.get("referencias"), dict) else {}
    if (
        patient is None
        or tutor is None
        or (patient.tutor_id and int(patient.tutor_id) != int(tutor.id))
        or _record_version(patient) != references.get("paciente")
        or _record_version(tutor) != references.get("tutor")
    ):
        _invalidate_pending_action(
            db,
            action,
            now_utc=now_utc,
            reason="reference_changed",
            detail="O paciente ou tutor mudou depois da solicitacao.",
        )
        raise HTTPException(status_code=409, detail="O paciente ou tutor mudou. Revise e solicite novamente.")

    updated = agenda.atualizar_agendamento(
        agendamento_id=int(appointment.id),
        agendamento=AgendamentoUpdate(
            paciente_id=int(patient.id),
            tutor_id=int(tutor.id),
        ),
        request=request,
        db=db,
        current_user=current_user,
    )
    return _mark_action_executed(
        db=db,
        current_user=current_user,
        request=request,
        action=action,
        now_utc=now_utc,
        message="Paciente vinculado a reserva com sucesso.",
        result={
            "agendamento": updated,
            "paciente": {"id": int(patient.id), "nome": str(patient.nome)},
            "tutor": {"id": int(tutor.id), "nome": str(tutor.nome)},
        },
        observation=observation,
    )


def decide_pending_action(
    *,
    db: Session,
    current_user: User,
    request: Optional[Request],
    action_id: str,
    decision: str,
    observation: Optional[str] = None,
) -> dict[str, Any]:
    action = (
        db.query(AssistenteIAAcaoPendente)
        .filter(
            AssistenteIAAcaoPendente.id == action_id,
            AssistenteIAAcaoPendente.usuario_id == current_user.id,
        )
        .with_for_update()
        .first()
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Acao pendente nao encontrada.")
    if action.status != "pending":
        raise HTTPException(status_code=409, detail="Esta acao ja foi decidida ou processada.")

    now_utc = datetime.now(timezone.utc)
    expires_at = _as_utc_datetime(action.expires_at)
    if expires_at is None or expires_at <= now_utc:
        action.status = "expired"
        action.decided_at = now_utc
        action.resultado_json = _json_dumps({"ok": False, "reason": "approval_expired"})
        db.commit()
        raise HTTPException(status_code=409, detail="A confirmacao expirou. Solicite a acao novamente.")

    if decision == "reject":
        action.status = "rejected"
        action.decided_at = now_utc
        action.resultado_json = _json_dumps(
            {"ok": True, "decision": "rejected", "observation": str(observation or "").strip() or None}
        )
        db.commit()
        db.refresh(action)
        registrar_auditoria(
            current_user=current_user,
            modulo="assistente_ia",
            entidade="acao_pendente",
            entidade_id=action.id,
            acao="ASSISTENTE_IA_ACAO_REJEITADA",
            descricao="Administrador rejeitou acao preparada pela IA.",
            detalhes={"tipo_acao": action.tipo_acao, "observacao": observation},
            request=request,
        )
        return serialize_pending_action(action)

    if decision != "approve":
        raise HTTPException(status_code=422, detail="Decisao invalida.")
    if action.tipo_acao == "create_appointment":
        return _approve_appointment_creation(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao == "update_agenda_exception":
        return _approve_agenda_exception_update(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao in {"reschedule_appointment", "cancel_appointment"}:
        return _approve_reschedule_or_cancel(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao == "create_agenda_block":
        return _approve_create_agenda_block(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao == "release_agenda_block":
        return _approve_release_agenda_block(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao == "update_clinic_whatsapps":
        return _approve_update_clinic_whatsapps(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao == "attach_patient_to_reservation":
        return _approve_attach_patient_to_reservation(
            db=db,
            current_user=current_user,
            request=request,
            action=action,
            now_utc=now_utc,
            observation=observation,
        )
    if action.tipo_acao != "delete_appointment":
        raise HTTPException(status_code=422, detail="Tipo de acao ainda nao suportado.")

    arguments = _json_loads(action.argumentos_json, {})
    snapshot = _json_loads(action.alvo_snapshot_json, {})
    appointment_id = int(arguments.get("agendamento_id") or 0)
    appointment = db.query(Agendamento).filter(Agendamento.id == appointment_id).first()
    if appointment is None:
        action.status = "invalidated"
        action.decided_at = now_utc
        action.resultado_json = _json_dumps({"ok": False, "reason": "target_missing"})
        db.commit()
        raise HTTPException(status_code=409, detail="O agendamento nao existe mais; a acao foi invalidada.")

    current_snapshot = _appointment_snapshot(db, appointment)
    if _snapshot_fingerprint(current_snapshot) != _snapshot_fingerprint(snapshot):
        action.status = "invalidated"
        action.decided_at = now_utc
        action.resultado_json = _json_dumps(
            {
                "ok": False,
                "reason": "target_changed",
                "current_snapshot": current_snapshot,
            }
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="O agendamento mudou depois da solicitacao. Revise os dados e solicite novamente.",
        )

    agenda.deletar_agendamento(
        agendamento_id=appointment_id,
        request=request,
        db=db,
        current_user=current_user,
    )
    action.status = "executed"
    action.decided_at = now_utc
    action.executed_at = now_utc
    action.resultado_json = _json_dumps(
        {
            "ok": True,
            "decision": "approved",
            "message": "Agendamento excluido com sucesso.",
            "observation": str(observation or "").strip() or None,
        }
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="acao_pendente",
        entidade_id=action.id,
        acao="ASSISTENTE_IA_ACAO_EXECUTADA",
        descricao="Administrador aprovou e executou acao preparada pela IA.",
        detalhes={
            "tipo_acao": action.tipo_acao,
            "agendamento_id": appointment_id,
            "observacao": observation,
        },
        request=request,
    )
    return serialize_pending_action(action)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "analisar_faturamento",
        "description": "Analisa faturamento recebido por mes. Use para dinamica, tendencia, crescimento e comparacao financeira. O mes atual e parcial.",
        "parameters": {
            "type": "object",
            "properties": {
                "meses": {"type": "integer", "minimum": 2, "maximum": 24},
                "clinica": {
                    "type": ["string", "null"],
                    "description": "Nome da clinica ou null para toda a FortCordis.",
                },
            },
            "required": ["meses", "clinica"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "analisar_servicos_realizados",
        "description": "Calcula o valor dos servicos realizados pelas ordens de servico na data de atendimento, pagos ou nao. Use quando o pedido for producao, servicos realizados ou todas as OS do periodo, e nao faturamento recebido.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string", "description": "Data inicial YYYY-MM-DD."},
                "data_fim": {"type": "string", "description": "Data final YYYY-MM-DD."},
                "clinica": {
                    "type": ["string", "null"],
                    "description": "Nome da clinica ou null para toda a FortCordis.",
                },
            },
            "required": ["data_inicio", "data_fim", "clinica"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "projetar_faturamento_agenda",
        "description": "Calcula em uma unica consulta o valor previsto dos servicos da agenda em uma data futura, usando primeiro o preco negociado da clinica e depois a tabela regional oficial. Separa reservas e nao representa dinheiro ja recebido.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data da agenda em YYYY-MM-DD."},
                "clinica": {
                    "type": ["string", "null"],
                    "description": "Nome da clinica ou null para toda a agenda.",
                },
            },
            "required": ["data", "clinica"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "localizar_agendamentos",
        "description": "Localiza agendamentos ativos por data, horario, clinica e servico. Use antes de qualquer pedido de exclusao. Se houver mais de um resultado, peca desambiguacao.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data YYYY-MM-DD."},
                "horario": {"type": ["string", "null"], "description": "Horario HH:MM ou null."},
                "clinica": {"type": ["string", "null"]},
                "servico": {"type": ["string", "null"]},
            },
            "required": ["data", "horario", "clinica", "servico"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "verificar_disponibilidade",
        "description": "Consulta slots futuros com as regras reais de agenda, duracao e deslocamento. Use preferencia para restringir datas, manha, tarde ou horas antes de ordenar as opcoes. Converta esta semana/proxima semana em datas locais de Fortaleza; semana vai de segunda a domingo. Nao amplia a preferencia automaticamente e nao cria nem reserva horario.",
        "parameters": {
            "type": "object",
            "properties": {
                "clinica": {"type": "string"},
                "servico": {"type": "string"},
                "data_inicio": {"type": ["string", "null"], "description": "Data YYYY-MM-DD ou null para hoje. Usada somente quando preferencia nao define datas."},
                "dias": {"type": "integer", "minimum": 1, "maximum": 14, "description": "Horizonte quando preferencia nao define datas. Com datas explicitas, consulta exclusivamente aquele intervalo de ate 31 dias."},
                "preferencia": {
                    "type": ["object", "null"],
                    "description": "Restricoes obrigatorias do pedido ou null. Datas devem vir em par; hora_inicio pode vir sozinha para indicar a partir de quando o cliente pode ser atendido. hora_fim exige hora_inicio. O periodo tem no maximo 31 dias e todo o atendimento deve caber no turno e nas horas.",
                    "properties": {
                        "data_inicio": {"type": ["string", "null"], "description": "Data YYYY-MM-DD."},
                        "data_fim": {"type": ["string", "null"], "description": "Ultima data inclusiva YYYY-MM-DD."},
                        "turno": {"type": "string", "enum": ["qualquer", "manha", "tarde"]},
                        "hora_inicio": {"type": ["string", "null"], "description": "Inicio minimo inclusivo HH:MM local; pode ser usado sem hora_fim."},
                        "hora_fim": {"type": ["string", "null"], "description": "Limite do termino HH:MM local; exige hora_inicio."},
                    },
                    "required": ["data_inicio", "data_fim", "turno", "hora_inicio", "hora_fim"],
                    "additionalProperties": False,
                },
            },
            "required": ["clinica", "servico", "data_inicio", "dias", "preferencia"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "consultar_deslocamento_clinicas",
        "description": "Consulta distancia e tempo estimado de deslocamento entre duas clinicas cadastradas usando a matriz logistica da FortCordis.",
        "parameters": {
            "type": "object",
            "properties": {
                "origem": {"type": "string"},
                "destino": {"type": "string"},
                "perfil": {"type": "string", "enum": ["comercial", "plantao"]},
            },
            "required": ["origem", "destino", "perfil"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "relatorio_debitos_pendentes",
        "description": "Gera relatorio de ordens de servico e contas a receber pendentes de uma clinica. As fontes sao separadas para evitar conclusoes incorretas.",
        "parameters": {
            "type": "object",
            "properties": {
                "clinica": {"type": "string"},
                "somente_vencidos": {"type": "boolean"},
            },
            "required": ["clinica", "somente_vencidos"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "consultar_funcionamento_agenda",
        "description": "Consulta se a agenda geral esta aberta ou fechada em uma data e retorna os horarios efetivos, considerando rotina semanal, feriado e excecao. Nao depende de clinica ou servico.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data YYYY-MM-DD."},
            },
            "required": ["data"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "consultar_clinica_360",
        "description": "Consulta o perfil operacional vivo de uma clinica: agenda, faturamento, debitos, atividade, servicos, contatos institucionais, alertas, preferencias aprovadas, fontes e planos de acao sugeridos. Os planos podem propor missao de leitura, rascunho de contato ou revisao operacional, mas nao executam, enviam ou alteram nada sem aprovacao do admin. Nao retorna dados de pacientes ou tutores.",
        "parameters": {
            "type": "object",
            "properties": {
                "clinica": {"type": "string"},
                "periodo_dias": {"type": "integer", "minimum": 30, "maximum": 365},
            },
            "required": ["clinica", "periodo_dias"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "comparar_clinicas_360",
        "description": "Compara de duas a dez clinicas pelos mesmos indicadores operacionais vivos e explicita a origem dos dados. E somente leitura.",
        "parameters": {
            "type": "object",
            "properties": {
                "clinicas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 10,
                },
                "periodo_dias": {"type": "integer", "minimum": 30, "maximum": 365},
            },
            "required": ["clinicas", "periodo_dias"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_excecao_funcionamento_agenda",
        "description": "Prepara uma excecao de funcionamento para uma data especifica, como abrir a agenda amanha ate 18h ou fechar um dia. Preserva a rotina semanal e nunca altera a configuracao sem confirmacao explicita do admin.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data YYYY-MM-DD."},
                "ativo": {
                    "type": "boolean",
                    "description": "True para abrir a agenda na data; false para fecha-la.",
                },
                "inicio": {
                    "type": ["string", "null"],
                    "description": "Horario inicial HH:MM ou null para preservar o inicio vigente.",
                },
                "fim": {
                    "type": ["string", "null"],
                    "description": "Horario final HH:MM ou null para preservar o fim vigente.",
                },
                "motivo": {
                    "type": ["string", "null"],
                    "maxLength": 300,
                    "description": "Motivo administrativo curto ou null.",
                },
            },
            "required": ["data", "ativo", "inicio", "fim", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_criacao_agendamento",
        "description": "Prepara um agendamento ou uma reserva depois de resolver os cadastros e validar as regras reais da agenda. Nunca cria o horario diretamente: gera uma acao pendente para confirmacao explicita do admin.",
        "parameters": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["agendamento", "reserva"]},
                "origem_atendimento": {
                    "type": "string",
                    "enum": ["clinica_parceira", "domiciliar"],
                },
                "clinica": {
                    "type": ["string", "null"],
                    "description": "Nome da clinica para atendimento em clinica parceira; null para domiciliar.",
                },
                "tutor": {"type": ["string", "null"], "description": "ID do tutor escolhido explicitamente, ex.: #184, ou null. Nunca reutilize uma pessoa somente pelo nome."},
                "paciente": {"type": ["string", "null"], "description": "Nome do paciente ou null apenas para reserva."},
                "servico": {"type": "string"},
                "data": {"type": "string", "description": "Data futura YYYY-MM-DD."},
                "horario": {"type": "string", "description": "Horario HH:MM."},
                "destinatario_mensagem": {"type": "string", "enum": ["clinica", "tutor"]},
                "prazo_confirmacao_horas": {
                    "type": ["number", "null"],
                    "minimum": 0.5,
                    "maximum": 72,
                    "description": "Prazo da reserva em horas; null para usar 3 horas ou para agendamento.",
                },
                "observacoes": {"type": ["string", "null"], "maxLength": 2000},
            },
            "required": [
                "tipo",
                "origem_atendimento",
                "clinica",
                "tutor",
                "paciente",
                "servico",
                "data",
                "horario",
                "destinatario_mensagem",
                "prazo_confirmacao_horas",
                "observacoes",
            ],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_exclusao_agendamento",
        "description": "Prepara a exclusao de um agendamento ja identificado. Esta ferramenta nunca exclui: cria uma acao pendente para confirmacao explicita do admin.",
        "parameters": {
            "type": "object",
            "properties": {
                "agendamento_id": {"type": "integer", "minimum": 1},
                "motivo": {"type": "string", "minLength": 5, "maxLength": 500},
            },
            "required": ["agendamento_id", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_vinculo_paciente_reserva",
        "description": "Prepara o vinculo de um paciente e seu tutor a uma reserva ja localizada. Mantem o horario e exige confirmacao explicita do admin; nao cancele nem recrie a reserva para essa finalidade.",
        "parameters": {
            "type": "object",
            "properties": {
                "agendamento_id": {"type": "integer", "minimum": 1},
                "tutor": {"type": "string", "minLength": 1, "description": "ID do tutor escolhido explicitamente, ex.: #184. Nome sozinho nao identifica uma pessoa."},
                "paciente": {"type": "string", "minLength": 1},
            },
            "required": ["agendamento_id", "tutor", "paciente"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "gerar_resumo_executivo",
        "description": "Consolida agenda, faturamento do mes, contas vencidas, reservas proximas do prazo e aprovacoes para uma leitura executiva diaria.",
        "parameters": {
            "type": "object",
            "properties": {"data": {"type": ["string", "null"], "description": "Data YYYY-MM-DD ou null para hoje."}},
            "required": ["data"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_remarcacao_agendamento",
        "description": "Prepara a remarcacao de um agendamento identificado quando data e horario de destino estao definidos. Revalida funcionamento e slot, mas so executa apos confirmacao do admin. Se a causa nao foi informada, use o motivo neutro 'Solicitacao do administrador' e nunca invente justificativa clinica.",
        "parameters": {
            "type": "object",
            "properties": {
                "agendamento_id": {"type": "integer", "minimum": 1},
                "data": {"type": "string"},
                "horario": {"type": "string"},
                "motivo": {"type": "string", "minLength": 3, "maxLength": 500},
            },
            "required": ["agendamento_id", "data", "horario", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_cancelamento_agendamento",
        "description": "Prepara o cancelamento de um agendamento identificado pelo fluxo oficial de status. Exige confirmacao explicita.",
        "parameters": {
            "type": "object",
            "properties": {
                "agendamento_id": {"type": "integer", "minimum": 1},
                "motivo": {"type": "string", "minLength": 3, "maxLength": 500},
            },
            "required": ["agendamento_id", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "listar_bloqueios_agenda",
        "description": "Lista bloqueios administrativos ativos da agenda em um periodo. Use antes de liberar um bloqueio.",
        "parameters": {
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string"},
                "dias": {"type": "integer", "minimum": 1, "maximum": 31},
            },
            "required": ["data_inicio", "dias"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_bloqueio_agenda",
        "description": "Prepara diretamente um bloqueio futuro quando data, inicio, fim e motivo estao definidos. Nao consulte antes: o bloqueio so passa a valer depois da confirmacao explicita do admin.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "string"},
                "inicio": {"type": "string"},
                "fim": {"type": "string"},
                "motivo": {"type": "string", "minLength": 3, "maxLength": 500},
            },
            "required": ["data", "inicio", "fim", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_liberacao_bloqueio_agenda",
        "description": "Prepara a liberacao de um bloqueio ativo ja identificado. Exige confirmacao explicita.",
        "parameters": {
            "type": "object",
            "properties": {
                "bloqueio_id": {"type": "string", "minLength": 36, "maxLength": 36},
                "motivo": {"type": "string", "minLength": 3, "maxLength": 500},
            },
            "required": ["bloqueio_id", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "solicitar_atualizacao_whatsapps_clinica",
        "description": "Prepara a substituicao da lista de WhatsApps de uma clinica. Preserva os outros dados e exige confirmacao.",
        "parameters": {
            "type": "object",
            "properties": {
                "clinica": {"type": "string"},
                "whatsapps": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                "motivo": {"type": "string", "minLength": 3, "maxLength": 500},
            },
            "required": ["clinica", "whatsapps", "motivo"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "propor_memoria_operacional",
        "description": "Propoe uma memoria sobre preferencias, regras de trabalho ou convencoes da FortCordis. A memoria so passa a orientar a Mente apos aprovacao do admin.",
        "parameters": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "minLength": 3, "maxLength": 180},
                "conteudo": {"type": "string", "minLength": 3, "maxLength": 8000},
                "categoria": {"type": "string", "maxLength": 60},
            },
            "required": ["titulo", "conteudo", "categoria"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "consultar_conhecimento_interno",
        "description": "Pesquisa manuais, modelos e procedimentos que o administrador adicionou a base interna da FortCordis.",
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "minLength": 3, "maxLength": 500},
                "limite": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["consulta", "limite"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "obter_contexto_laudo",
        "description": "Le o contexto de um laudo e ate cinco laudos anteriores do paciente para apoiar comparacao e completude. Nao modifica nem finaliza o laudo.",
        "parameters": {
            "type": "object",
            "properties": {"laudo_id": {"type": "integer", "minimum": 1}},
            "required": ["laudo_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "salvar_rascunho_clinico",
        "description": "Salva uma sugestao clinica em area separada quando titulo e conteudo foram fornecidos ou obtidos do contexto do laudo. Se o pedido nao trouxer conteudo clinico suficiente, use obter_contexto_laudo antes. Nunca altera ou finaliza o laudo oficial.",
        "parameters": {
            "type": "object",
            "properties": {
                "laudo_id": {"type": "integer", "minimum": 1},
                "titulo": {"type": "string", "minLength": 3, "maxLength": 220},
                "conteudo": {"type": "string", "minLength": 20, "maxLength": 60000},
                "alertas": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "laudos_fonte_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 20},
            },
            "required": ["laudo_id", "titulo", "conteudo", "alertas", "laudos_fonte_ids"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def execute_tool(
    ctx: AssistenteIAToolContext,
    *,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if name == "analisar_faturamento":
        return analisar_faturamento(ctx, meses=arguments["meses"], clinica=arguments.get("clinica"))
    if name == "analisar_servicos_realizados":
        return analisar_servicos_realizados(
            ctx,
            data_inicio=arguments["data_inicio"],
            data_fim=arguments["data_fim"],
            clinica=arguments.get("clinica"),
        )
    if name == "projetar_faturamento_agenda":
        return projetar_faturamento_agenda(
            ctx,
            data=arguments["data"],
            clinica=arguments.get("clinica"),
        )
    if name == "localizar_agendamentos":
        return localizar_agendamentos(
            ctx,
            data=arguments["data"],
            horario=arguments.get("horario"),
            clinica=arguments.get("clinica"),
            servico=arguments.get("servico"),
        )
    if name == "verificar_disponibilidade":
        return verificar_disponibilidade(
            ctx,
            clinica=arguments["clinica"],
            servico=arguments["servico"],
            data_inicio=arguments.get("data_inicio"),
            dias=arguments["dias"],
            preferencia=arguments.get("preferencia"),
        )
    if name == "consultar_deslocamento_clinicas":
        return consultar_deslocamento_clinicas(
            ctx,
            origem=arguments["origem"],
            destino=arguments["destino"],
            perfil=arguments["perfil"],
        )
    if name == "relatorio_debitos_pendentes":
        return relatorio_debitos_pendentes(
            ctx,
            clinica=arguments["clinica"],
            somente_vencidos=bool(arguments["somente_vencidos"]),
        )
    if name == "consultar_funcionamento_agenda":
        return consultar_funcionamento_agenda(ctx, data=arguments["data"])
    if name == "consultar_clinica_360":
        return consultar_clinica_360(
            ctx,
            clinica=arguments["clinica"],
            periodo_dias=int(arguments["periodo_dias"]),
        )
    if name == "comparar_clinicas_360":
        return comparar_clinicas_360(
            ctx,
            clinicas=list(arguments["clinicas"]),
            periodo_dias=int(arguments["periodo_dias"]),
        )
    if name == "solicitar_excecao_funcionamento_agenda":
        return solicitar_excecao_funcionamento_agenda(
            ctx,
            data=arguments["data"],
            ativo=bool(arguments["ativo"]),
            inicio=arguments.get("inicio"),
            fim=arguments.get("fim"),
            motivo=arguments.get("motivo"),
        )
    if name == "solicitar_criacao_agendamento":
        return solicitar_criacao_agendamento(
            ctx,
            tipo=arguments["tipo"],
            origem_atendimento=arguments["origem_atendimento"],
            clinica=arguments.get("clinica"),
            tutor=arguments.get("tutor"),
            paciente=arguments.get("paciente"),
            servico=arguments["servico"],
            data=arguments["data"],
            horario=arguments["horario"],
            destinatario_mensagem=arguments["destinatario_mensagem"],
            prazo_confirmacao_horas=arguments.get("prazo_confirmacao_horas"),
            observacoes=arguments.get("observacoes"),
        )
    if name == "solicitar_exclusao_agendamento":
        return solicitar_exclusao_agendamento(
            ctx,
            agendamento_id=int(arguments["agendamento_id"]),
            motivo=arguments["motivo"],
        )
    if name == "solicitar_vinculo_paciente_reserva":
        return solicitar_vinculo_paciente_reserva(
            ctx,
            agendamento_id=int(arguments["agendamento_id"]),
            tutor=arguments["tutor"],
            paciente=arguments["paciente"],
        )
    if name == "gerar_resumo_executivo":
        try:
            reference = _parse_iso_date(arguments.get("data")) if arguments.get("data") else None
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return executive_summary(ctx.db, ctx.current_user, reference=reference)
    if name == "solicitar_remarcacao_agendamento":
        return solicitar_remarcacao_agendamento(
            ctx,
            agendamento_id=int(arguments["agendamento_id"]),
            data=arguments["data"],
            horario=arguments["horario"],
            motivo=arguments["motivo"],
        )
    if name == "solicitar_cancelamento_agendamento":
        return solicitar_cancelamento_agendamento(
            ctx,
            agendamento_id=int(arguments["agendamento_id"]),
            motivo=arguments["motivo"],
        )
    if name == "listar_bloqueios_agenda":
        return listar_bloqueios_agenda(ctx, data_inicio=arguments["data_inicio"], dias=arguments["dias"])
    if name == "solicitar_bloqueio_agenda":
        return solicitar_bloqueio_agenda(
            ctx,
            data=arguments["data"],
            inicio=arguments["inicio"],
            fim=arguments["fim"],
            motivo=arguments["motivo"],
        )
    if name == "solicitar_liberacao_bloqueio_agenda":
        return solicitar_liberacao_bloqueio_agenda(
            ctx,
            bloqueio_id=arguments["bloqueio_id"],
            motivo=arguments["motivo"],
        )
    if name == "solicitar_atualizacao_whatsapps_clinica":
        return solicitar_atualizacao_whatsapps_clinica(
            ctx,
            clinica=arguments["clinica"],
            whatsapps=arguments["whatsapps"],
            motivo=arguments["motivo"],
        )
    if name == "propor_memoria_operacional":
        memory = create_memory(
                ctx.db,
                ctx.current_user,
                title=arguments["titulo"],
                content=arguments["conteudo"],
                category=arguments["categoria"],
                source="assistant",
                approve_immediately=False,
            )
        registrar_auditoria(
            current_user=ctx.current_user,
            modulo="assistente_ia",
            entidade="memoria",
            entidade_id=memory["id"],
            acao="ASSISTENTE_IA_MEMORIA_PROPOSTA",
            descricao="Mente FortCordis propos memoria para revisao do administrador.",
            detalhes={"titulo": memory["title"], "categoria": memory["category"]},
            request=ctx.request,
        )
        return {
            "ok": True,
            "memory": memory,
            "requires_admin_approval": True,
        }
    if name == "consultar_conhecimento_interno":
        return search_knowledge(ctx.db, query=arguments["consulta"], limit=arguments["limite"])
    if name == "obter_contexto_laudo":
        return clinical_report_context(ctx.db, ctx.current_user, report_id=int(arguments["laudo_id"]))
    if name == "salvar_rascunho_clinico":
        draft = save_clinical_draft(
            ctx.db,
            ctx.current_user,
            conversation_id=ctx.conversa.id,
            report_id=int(arguments["laudo_id"]),
            title=arguments["titulo"],
            content=arguments["conteudo"],
            alerts=arguments["alertas"],
            source_report_ids=arguments["laudos_fonte_ids"],
        )
        if draft.get("ok") is not False:
            registrar_auditoria(
                current_user=ctx.current_user,
                modulo="assistente_ia",
                entidade="rascunho_clinico",
                entidade_id=draft.get("id"),
                acao="ASSISTENTE_IA_RASCUNHO_CLINICO_CRIADO",
                descricao="Mente FortCordis salvou rascunho clinico isolado para revisao humana.",
                detalhes={"laudo_id": draft.get("report_id"), "laudo_oficial_modificado": False},
                request=ctx.request,
            )
        return draft
    return {"ok": False, "error": f"Ferramenta desconhecida: {name}"}


def tool_result_summary(name: str, result: dict[str, Any]) -> str:
    if not bool(result.get("ok")):
        return str(result.get("error") or "Falha na ferramenta")[:180]
    if name == "analisar_faturamento":
        return f"{result.get('periodo', {}).get('meses', 0)} meses analisados"
    if name == "analisar_servicos_realizados":
        return f"{result.get('resumo', {}).get('ordens_servico', 0)} OS analisada(s)"
    if name == "projetar_faturamento_agenda":
        summary = result.get("resumo") or {}
        return (
            f"{summary.get('agendamentos_considerados', 0)} item(ns), "
            f"R$ {float(summary.get('valor_total_previsto') or 0):.2f} previsto(s)"
        )
    if name == "localizar_agendamentos":
        return f"{result.get('total', 0)} agendamento(s) localizado(s)"
    if name == "verificar_disponibilidade":
        return f"{len(result.get('slots') or [])} slot(s) candidato(s)"
    if name == "consultar_deslocamento_clinicas":
        return f"{result.get('duracao_min', 0)} min de deslocamento estimado"
    if name == "relatorio_debitos_pendentes":
        orders = result.get("ordens_servico_pendentes") or {}
        accounts = result.get("contas_receber_pendentes") or {}
        return f"{orders.get('quantidade', 0)} OS e {accounts.get('quantidade', 0)} conta(s) pendente(s)"
    if name == "consultar_funcionamento_agenda":
        funcionamento = result.get("funcionamento") or {}
        return (
            f"Agenda aberta ate {funcionamento.get('fim')}"
            if funcionamento.get("ativo")
            else "Agenda fechada na data"
        )
    if name == "consultar_clinica_360":
        profile = result.get("profile") or {}
        clinic = profile.get("clinic") or {}
        return f"Perfil 360 de {clinic.get('name', 'clinica')} atualizado"
    if name == "comparar_clinicas_360":
        return f"{len(result.get('items') or [])} clinicas comparadas"
    if name == "solicitar_excecao_funcionamento_agenda":
        if result.get("changed") is False:
            return "A agenda ja possui o funcionamento solicitado"
        return "Aguardando confirmacao para alterar o funcionamento"
    if name == "solicitar_criacao_agendamento":
        return "Aguardando confirmacao para criar o horario"
    if name == "solicitar_exclusao_agendamento":
        return "Aguardando confirmacao do administrador"
    if name == "gerar_resumo_executivo":
        return f"Resumo executivo de {result.get('date')} gerado"
    if name in {
        "solicitar_remarcacao_agendamento",
        "solicitar_cancelamento_agendamento",
        "solicitar_bloqueio_agenda",
        "solicitar_liberacao_bloqueio_agenda",
        "solicitar_atualizacao_whatsapps_clinica",
        "solicitar_vinculo_paciente_reserva",
    }:
        return "Aguardando confirmacao do administrador"
    if name == "listar_bloqueios_agenda":
        return f"{len(result.get('items') or [])} bloqueio(s) ativo(s)"
    if name == "propor_memoria_operacional":
        return "Memoria proposta para revisao do administrador"
    if name == "consultar_conhecimento_interno":
        return f"{result.get('total', 0)} documento(s) relevante(s)"
    if name == "obter_contexto_laudo":
        return "Contexto clinico carregado sem modificar o laudo"
    if name == "salvar_rascunho_clinico":
        return "Rascunho clinico salvo para revisao"
    return "Ferramenta executada"


def tool_result_for_model(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if name == "solicitar_excecao_funcionamento_agenda" and isinstance(result.get("pending_action"), dict):
        action = result["pending_action"]
        target = action.get("target") if isinstance(action.get("target"), dict) else {}
        return {
            "ok": bool(result.get("ok")),
            "requires_approval": bool(result.get("requires_approval")),
            "message": result.get("message"),
            "pending_action": {
                "id": action.get("id"),
                "type": action.get("type"),
                "status": action.get("status"),
                "target": {
                    "data": target.get("data"),
                    "antes": target.get("antes"),
                    "depois": target.get("depois"),
                    "motivo": target.get("motivo"),
                },
            },
        }
    if name != "solicitar_criacao_agendamento" or not isinstance(result.get("pending_action"), dict):
        return result
    action = result["pending_action"]
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    recipient = (
        target.get("destinatario_mensagem")
        if isinstance(target.get("destinatario_mensagem"), dict)
        else {}
    )
    phones = recipient.get("telefones") if isinstance(recipient.get("telefones"), list) else []
    return {
        "ok": bool(result.get("ok")),
        "requires_approval": bool(result.get("requires_approval")),
        "message": result.get("message"),
        "pending_action": {
            "id": action.get("id"),
            "type": action.get("type"),
            "status": action.get("status"),
            "target": {
                "tipo": target.get("tipo"),
                "status": target.get("status"),
                "inicio": target.get("inicio"),
                "fim": target.get("fim"),
                "reserva_expira_em": target.get("reserva_expira_em"),
                "clinica_nome": target.get("clinica_nome"),
                "servico_nome": target.get("servico_nome"),
                "paciente_nome": target.get("paciente_nome"),
                "tutor_nome": target.get("tutor_nome"),
                "destinatario_mensagem": {
                    "tipo": recipient.get("tipo"),
                    "nome": recipient.get("nome"),
                    "possui_contato": bool(phones),
                    "quantidade_contatos": len(phones),
                },
            },
        },
    }
