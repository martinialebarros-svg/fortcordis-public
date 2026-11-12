"""Fail-closed Google Maps cost boundary, independent of business transactions.

Every outgoing attempt is committed BEFORE HTTP. A timeout is never refunded:
Google may have billed it. PostgreSQL advisory transaction locks (all workers)
and SQLite BEGIN IMMEDIATE serialize checks plus reservations. No process-local
counter, billing lag or assumed free account allowance is used as authority.

An explicitly enabled server emergency release suspends this cost policy and
records sanitized attempts in server logs. It does not claim a financial cap.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any, Callable, Literal
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from sqlalchemy import func, insert, select, text, update

from app.core.config import settings
from app.db import database
from app.models.google_maps_cost_control import (
    GoogleMapsCostAction, GoogleMapsCostConfig, GoogleMapsCostEvent,
)

logger = logging.getLogger(__name__)
SKUS = (
    "routes_essentials", "routes_pro", "distance_matrix_essentials",
    "distance_matrix_pro", "geocoding",
)
ROUTE_SKUS = SKUS[:4]
# Public highest marginal tier per billable unit, verified against the Google
# Maps global price list on this date. Discounts/free tiers never lower guard
# reservations. The configured envelope may be higher, but not below this floor.
PRICING_REFERENCE_DATE = "2026-10-18"
MIN_UNIT_PRICES_USD = {
    "routes_essentials": Decimal("0.005"), "routes_pro": Decimal("0.01"),
    "distance_matrix_essentials": Decimal("0.005"), "distance_matrix_pro": Decimal("0.01"),
    "geocoding": Decimal("0.005"),
}
CONFIG = GoogleMapsCostConfig.__table__
ACTIONS = GoogleMapsCostAction.__table__
EVENTS = GoogleMapsCostEvent.__table__
LEDGER_TIMEZONE = ZoneInfo("America/Fortaleza")
QUOTE_TTL_SECONDS = 300
EXECUTION_TTL_SECONDS = 600
_LOCK_ID = 715064291071
_execution: ContextVar[Execution | None] = ContextVar("google_maps_cost_execution", default=None)
EMERGENCY_RELEASE_MESSAGE = (
    "Liberação temporária do Google Maps ativa: confirmação e limites de custo "
    "estão suspensos. Novas consultas podem gerar cobrança, sem teto financeiro."
)


def emergency_release_enabled() -> bool:
    # Only the server setting can authorize the exception; a request, token or
    # previously created execution can never keep it active after revocation.
    return settings.GOOGLE_MAPS_COST_EMERGENCY_RELEASE is True


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    skus: tuple[str, ...] = SKUS
    theoretical_cap: int | None = None


ACTION_ROUTES = (
    ("POST", r"/api/v1/agenda/geocode-endereco-tutor", ActionSpec("agenda_tutor_geocode", "Localizar endereço do tutor para agendamento", ("geocoding",), 1)),
    ("POST", r"/api/v1/agenda/sugestoes-horario", ActionSpec("agenda_search", "Buscar horários na agenda")),
    ("POST", r"/api/v1/agenda/assistente/validar-oferta", ActionSpec("agenda_validate_offer", "Validar oferta da agenda")),
    ("POST", r"/api/v1/agenda/sugestao-proximidade", ActionSpec("agenda_proximity", "Buscar horários por proximidade")),
    ("POST", r"/api/v1/agenda/assistente/ofertas", ActionSpec("agenda_offers", "Preparar ofertas da agenda")),
    ("POST", r"/api/v1/agenda", ActionSpec("agenda_create", "Criar agendamento e validar deslocamentos")),
    ("PUT", r"/api/v1/agenda/\d+", ActionSpec("agenda_update", "Atualizar agendamento e validar deslocamentos")),
    ("PATCH", r"/api/v1/agenda/\d+/status", ActionSpec("agenda_status", "Alterar situação do agendamento")),
    ("POST", r"/api/v1/agenda/\d+/reabilitar-reserva", ActionSpec("agenda_reservation", "Reabilitar reserva da agenda")),
    ("GET", r"/api/v1/logistica/deslocamento", ActionSpec("route_lookup", "Consultar deslocamento entre clínicas", ROUTE_SKUS, 2)),
    ("POST", r"/api/v1/logistica/recalcular", ActionSpec("matrix_recalculate", "Recalcular matriz de deslocamentos", ROUTE_SKUS)),
    ("POST", r"/api/v1/clinicas/geocode-endereco", ActionSpec("clinic_geocode", "Consultar coordenadas da clínica", ("geocoding",), 1)),
    ("POST", r"/api/v1/tutores/geocode-endereco", ActionSpec("tutor_geocode", "Consultar coordenadas do tutor", ("geocoding",), 1)),
    ("POST", r"/api/v1/assistente-ia/chat", ActionSpec("assistant_chat", "Executar assistente com consultas de rota")),
    ("POST", r"/api/v1/assistente-ia/acoes/[a-zA-Z0-9-]+/decisao", ActionSpec("assistant_decision", "Confirmar ação do assistente com consultas de rota")),
)
ACTION_SPECS = {spec.key: spec for _, _, spec in ACTION_ROUTES}


def identify_action(method: str, path: str, query=None, body=None) -> ActionSpec | None:
    for expected_method, pattern, spec in ACTION_ROUTES:
        if method.upper() == expected_method and re.fullmatch(pattern, path.rstrip("/")):
            if spec.key == "agenda_status" and query is not None:
                values = parse_qs(query, keep_blank_values=True) if isinstance(query, str) else query
                status = values.get("status")
                status = status[-1] if isinstance(status, list) and status else status
                # Endpoint takes status from QUERY, never from JSON. These final
                # states do not enter AGENDA_STATUS_BLOQUEIAM_SLOT and no route
                # validation is run. Provider boundary remains fail-closed.
                if isinstance(status, str) and status.strip().casefold() in {"cancelado", "faltou", "expirado", "realizado"}:
                    return None
            return spec
    return None


def agenda_cache_first_enabled(spec: ActionSpec | None) -> bool:
    return settings.GOOGLE_MAPS_AGENDA_CACHE_FIRST is True and spec is not None and spec.key.startswith("agenda_")


def cache_first_operation() -> bool:
    execution = _execution.get()
    return execution is not None and execution.cache_first


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calls: StrictInt = Field(ge=0, le=10_000_000)
    estimated_brl: Decimal = Field(ge=0, le=100_000_000, max_digits=16, decimal_places=6)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Budget
    day: Budget
    month: Budget


class OpeningUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: Budget
    month: Budget

    @model_validator(mode="after")
    def month_includes_day(self):
        if self.month.calls < self.day.calls or self.month.estimated_brl < self.day.estimated_brl:
            raise ValueError("O saldo inicial mensal deve incluir o consumo do dia.")
        return self


class AutomaticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    limits: Limits
    skus: list[str]

    @model_validator(mode="after")
    def known_skus(self):
        if not self.skus or set(self.skus) - set(SKUS):
            raise ValueError("Política automática precisa de SKUs reconhecidos.")
        return self


class CostConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_mode: Literal["paid_budget", "cache_only"] = "paid_budget"
    enabled: StrictBool
    agenda_budget_mode: Literal["enforce", "monitor"] = "enforce"
    clinic_geocode_manual_enabled: StrictBool = False
    limits: Limits
    prices_usd: dict[str, Decimal] | None = None
    fx_brl_per_usd_upper: Decimal | None = Field(default=None, gt=0, le=1000)
    price_multiplier: Decimal | None = Field(default=None, ge=1, le=100)
    pricing_valid_until: datetime | None = None
    action_call_caps: dict[str, StrictInt] = Field(default_factory=dict)
    automatic_policies: dict[str, AutomaticPolicy] = Field(default_factory=dict)
    opening_usage: OpeningUsage | None = None
    opening_usage_as_of: date | None = None
    opening_usage_basis: Literal["verified_telemetry", "conservative_upper_bound", "synthetic_stage"] | None = None

    @model_validator(mode="after")
    def validate_financial_envelope(self):
        if self.clinic_geocode_manual_enabled and (self.operation_mode != "paid_budget" or self.action_call_caps.get("clinic_geocode") != 1):
            raise ValueError("Geocodificação manual de clínicas exige orçamento pago e teto explícito de uma chamada por execução.")
        if self.operation_mode == "cache_only":
            if self.agenda_budget_mode != "enforce":
                raise ValueError("Somente cache não permite liberação de consultas da Agenda.")
            if any(getattr(self.limits, period).calls != 0 or getattr(self.limits, period).estimated_brl != 0 for period in ("action", "day", "month")):
                raise ValueError("O modo somente cache exige limites de chamadas e novas cobranças exatamente zero.")
            if self.prices_usd is not None or self.fx_brl_per_usd_upper is not None or self.price_multiplier is not None or self.pricing_valid_until is not None:
                raise ValueError("O modo somente cache não usa preços ou câmbio; não informe estimativas financeiras.")
            if self.action_call_caps or self.automatic_policies:
                raise ValueError("O modo somente cache não autoriza chamadas por ação nem por política automática.")
            return self
        if any(value is None for value in (self.prices_usd, self.fx_brl_per_usd_upper, self.price_multiplier, self.pricing_valid_until)):
            raise ValueError("O modo com orçamento exige preços, câmbio, multiplicador e validade explícitos.")
        if set(self.prices_usd) != set(SKUS):
            raise ValueError("Informe o preço USD por unidade de todos os SKUs conhecidos.")
        if any(not price.is_finite() or not (0 < price <= 100) for price in self.prices_usd.values()):
            raise ValueError("Preços por unidade devem ser positivos e finitos.")
        if any(price < MIN_UNIT_PRICES_USD[sku] for sku, price in self.prices_usd.items()):
            raise ValueError("O envelope de preços não pode ser menor que a maior faixa marginal pública por unidade: USD 0.005 Essentials/Geocoding e USD 0.01 Pro.")
        if self.agenda_budget_mode == "monitor" and self.limits.action.calls * (max(self.prices_usd.values()) * self.fx_brl_per_usd_upper * self.price_multiplier * 1_000_000).to_integral_value(rounding=ROUND_CEILING) > 2**63 - 1:
            raise ValueError("O envelope por confirmação excede a capacidade do registro financeiro; reduza o máximo de chamadas ou revise preços/câmbio.")
        if self.pricing_valid_until.tzinfo is None:
            raise ValueError("Validade de preços/câmbio deve incluir fuso horário.")
        if any(key not in ACTION_SPECS or cap < 0 or cap > 10_000_000 for key, cap in self.action_call_caps.items()):
            raise ValueError("Teto por ação inválido.")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) for key in self.automatic_policies):
            raise ValueError("Identificador de política automática inválido.")
        if self.enabled and (self.opening_usage is None or self.opening_usage_as_of is None or self.opening_usage_basis is None):
            raise ValueError("A ativação exige consumo inicial do dia/mês, data e base da apuração explícitos.")
        if self.opening_usage_basis == "synthetic_stage" and settings.APP_ENV.lower() in {"production", "prod"}:
            raise ValueError("Consumo sintético não pode ser usado em produção.")
        return self


REASONS = {
    "clinic_manual_record": "Geocodificação manual registrada no servidor, limitada a uma chamada e aos limites diário e mensal.",
    "agenda_internal_record": "Execução da Agenda registrada com limite próprio no servidor, sem popup de custo.",
    "day_reference_exceeded": "Referência diária atingida: a Agenda continua liberada mediante confirmação; lotes e tarefas extras seguem bloqueados pelo teto.",
    "month_reference_exceeded": "Referência mensal atingida: a Agenda continua liberada mediante confirmação; lotes e tarefas extras seguem bloqueados pelo teto.",
    "day_reference_may_exceed": "Esta ação pode ultrapassar a referência diária. O consumo atual ainda está abaixo dela; a Agenda continua liberada mediante confirmação.",
    "month_reference_may_exceed": "Esta ação pode ultrapassar a referência mensal. O consumo atual ainda está abaixo dela; a Agenda continua liberada mediante confirmação.",
    "estimate_unavailable": "Não foi possível verificar as rotas necessárias para estimar esta busca. Nenhuma nova chamada paga foi autorizada; rotas válidas em cache continuam disponíveis.",
    "route_unavailable": "Não foi possível obter uma rota confiável. Os dados do formulário foram mantidos; revise a consulta de rota antes de confirmar o horário. Nenhuma distância, duração ou disponibilidade foi presumida.",
    "cache_only": "Modo somente cache: novas chamadas ao Google Maps estão bloqueadas para manter novas cobranças em R$ 0. Esta operação exige uma rota Google ainda válida ou um ajuste manual autorizado; não será criada uma estimativa alternativa.",
    "unconfigured": "Controle Google Maps sem configuração aprovada. Nenhuma chamada paga foi autorizada.",
    "disabled": "Chamadas ao Google Maps estão suspensas na configuração administrativa.",
    "pricing_review_due": "Revisão de preços/câmbio pendente: a Agenda continua liberada com a última estimativa cadastrada. O custo real pode variar. Cada nova consulta exige confirmação limitada; lotes e automações continuam sujeitos às suas restrições.",
    "pricing_expired": "A validade da estimativa de preços/câmbio expirou; atualize a configuração antes de continuar.",
    "ledger_unavailable": "Não foi possível verificar o limite compartilhado. A operação que gera custo foi suspensa.",
    "confirmation_required": "Confirme esta ação no aviso de custo antes de consultar o Google Maps.",
    "invalid_grant": "A confirmação não corresponde a esta ação, expirou ou já foi usada. Revise e confirme novamente.",
    "configuration_changed": "Os limites ou preços mudaram. Revise a estimativa e confirme novamente.",
    "action_limit": "Esta ação está bloqueada pelo seu limite de chamadas ou custo. Isso não significa que o limite diário foi atingido. Nenhuma chamada extra foi enviada.",
    "day_limit": "O limite diário de chamadas ou custo estimado foi atingido.",
    "month_limit": "O limite mensal de chamadas ou custo estimado foi atingido.",
    "automatic_policy_required": "A tarefa automática não tem uma política explícita habilitada com limites próprios.",
    "automatic_replay": "Esta execução automática já foi iniciada. A repetição foi bloqueada.",
    "sku_not_authorized": "Este serviço/SKU não foi autorizado para a ação apresentada.",
    "invalid_configuration": "A configuração de limites ou preços é inválida. Chamadas pagas estão suspensas.",
}


class GoogleMapsCostBlocked(HTTPException):
    def __init__(self, reason="confirmation_required", action=None, status_code=409):
        self.reason = reason
        super().__init__(status_code=status_code, detail={
            "code": "GOOGLE_MAPS_COST_BLOCKED", "reason": reason,
            "message": REASONS.get(reason, REASONS["ledger_unavailable"]),
            "action": action,
            # Only the server's unpaid Agenda attempt may request one replay.
            # All cost reservations and single-use consent checks still apply.
            "can_retry_with_confirmation": reason == "confirmation_required" and cache_first_operation(),
        })


@dataclass
class Execution:
    action_id: str
    automatic_policy: str | None = None
    automatic_fingerprint: str | None = None
    automatic_claimed: bool = False
    closed: bool = False
    operation_mode: str | None = None
    cache_first: bool = False
    route_results: dict = field(default_factory=dict)
    request_action: str | None = None
    request_user_id: int | None = None
    request_inputs: tuple | None = None
    estimate_loader: Callable | None = None
    internal_estimate: dict | None = None
    internal_fingerprint: str | None = None
    business_session: Any = field(default=None, repr=False)


@contextmanager
def agenda_business_session(session):
    """Reuse the endpoint session for lazy planning; never nest a pool checkout."""
    execution = _execution.get()
    if not _internal_agenda_requested(execution):
        yield
        return
    previous = execution.business_session
    execution.business_session = session
    try:
        yield
    finally:
        execution.business_session = previous


def current_agenda_business_session():
    execution = _execution.get()
    return execution.business_session if _internal_agenda_requested(execution) else None


def _internal_agenda_requested(execution):
    return (settings.GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION is False
            and execution is not None and execution.cache_first and not execution.closed
            and not execution.automatic_policy and execution.request_action in ACTION_SPECS
            and execution.request_action.startswith("agenda_")
            and execution.request_user_id is not None and execution.request_inputs is not None)


def _load_internal_agenda_estimate(execution):
    if not _internal_agenda_requested(execution) or execution.operation_mode != "cache_first":
        return
    from app.services.google_maps_agenda_estimate import SEARCH_MODELS
    execution.internal_fingerprint = request_fingerprint(execution.request_user_id, *execution.request_inputs)
    if execution.request_action in SEARCH_MODELS and execution.internal_estimate is None:
        if execution.estimate_loader is None:
            raise GoogleMapsCostBlocked("estimate_unavailable", status_code=503)
        try:
            execution.internal_estimate = execution.estimate_loader()
            if execution.internal_estimate is None:
                raise ValueError("Missing search estimate")
        except HTTPException:
            raise
        except Exception:
            raise GoogleMapsCostBlocked("estimate_unavailable", status_code=503) from None


def _record_internal_agenda(conn, execution, cfg, revision):
    """One server-owned, finite scope; never fabricate a user's confirmation."""
    spec = ACTION_SPECS[execution.request_action]
    estimate = execution.internal_estimate
    skus = tuple(estimate["services"]) if estimate is not None else spec.skus
    if not skus or set(skus) - set(spec.skus):
        _deny(conn, "estimate_unavailable", action=spec.key, user_id=execution.request_user_id)
    cap = min(cfg.limits.action.calls, cfg.action_call_caps.get(spec.key, cfg.limits.action.calls))
    if estimate is not None:
        cap = min(cap, estimate["max_calls"])
    if spec.theoretical_cap is not None:
        cap = min(cap, spec.theoretical_cap)
    if cap <= 0:
        _deny(conn, "action_limit", action=spec.key, user_id=execution.request_user_id)
    now = _now()
    conn.execute(insert(ACTIONS).values(
        id=execution.action_id, user_id=execution.request_user_id,
        fingerprint=execution.internal_fingerprint, action=spec.key, revision=revision,
        state="claimed", max_calls=cap, max_cost_micros=cap * max(_unit_cost(cfg, sku) for sku in skus),
        used_calls=0, used_cost_micros=0, skus_json=json.dumps(skus), created_at=now,
        claimed_at=now, expires_at=now + EXECUTION_TTL_SECONDS,
    ))
    _event(conn, kind="internal_authorized", action=spec.key, action_id=execution.action_id,
           user_id=execution.request_user_id, reason="agenda_internal_record")
    execution.operation_mode = "agenda_internal"


def agenda_execution_route_cache(fallback=None):
    execution = _execution.get()
    return execution.route_results if execution and execution.cache_first else fallback


def _now() -> int:
    return int(time.time())


def _micros(amount: Decimal | str | float) -> int:
    return int((Decimal(str(amount)) * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))


def _brl(micros: int) -> float:
    return float(Decimal(micros) / Decimal(1_000_000))


def _periods(now: int):
    local = datetime.fromtimestamp(now, tz=timezone.utc).astimezone(LEDGER_TIMEZONE)
    return local.strftime("%Y-%m-%d"), local.strftime("%Y-%m")


def _iso(now: int):
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


@contextmanager
def _locked():
    """Never borrow/commit the caller's business session or silently fall back."""
    try:
        with database.engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_ID})
            elif conn.dialect.name == "sqlite":
                conn.exec_driver_sql("PRAGMA busy_timeout = 5000")
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                raise GoogleMapsCostBlocked("ledger_unavailable", status_code=503)
            try:
                yield conn
            except GoogleMapsCostBlocked:
                # Persist the redacted denial even when the action itself aborts.
                conn.commit()
                raise
            else:
                conn.commit()
    except GoogleMapsCostBlocked:
        raise
    except Exception:
        # Do not log DB URLs, bound parameters or exception payloads.
        logger.warning("google_maps_cost_guard: ledger_unavailable")
        raise GoogleMapsCostBlocked("ledger_unavailable", status_code=503) from None


def _event(conn, *, kind, action="unscoped", action_id=None, user_id=None, policy=None, sku=None, reason=None, cost=0, calls=0):
    now = _now()
    day, month = _periods(now)
    conn.execute(insert(EVENTS).values(
        action_id=action_id, action=action, user_id=user_id, policy=policy, sku=sku,
        kind=kind, reason=reason, calls=calls, estimated_cost_micros=cost,
        day=day, month=month, created_at=now,
    ))


def _deny(conn, reason, *, action="unscoped", action_id=None, user_id=None, policy=None):
    _event(conn, kind="blocked", reason=reason, action=action, action_id=action_id, user_id=user_id, policy=policy)
    raise GoogleMapsCostBlocked(reason, action)


def _configuration(conn, *, require_enabled=True, action=None):
    row = conn.execute(select(CONFIG).where(CONFIG.c.id == 1)).mappings().first()
    if row is None:
        if require_enabled:
            _deny(conn, "unconfigured")
        return None, 0
    try:
        cfg = CostConfiguration.model_validate_json(row["config_json"])
    except Exception:
        _deny(conn, "invalid_configuration")
    if require_enabled:
        if not cfg.enabled:
            _deny(conn, "disabled")
        if _pricing_review_due(cfg) and not agenda_monitored(cfg, action):
            _deny(conn, "pricing_expired")
    return cfg, row["revision"]


def _pricing_review_due(cfg):
    return cfg is not None and cfg.operation_mode == "paid_budget" and cfg.pricing_valid_until.timestamp() <= _now()


def _configuration_reason(cfg, *, action=None):
    if cfg is None:
        return "unconfigured"
    if not cfg.enabled:
        return "disabled"
    if _pricing_review_due(cfg) and not agenda_monitored(cfg, action):
        return "pricing_expired"
    return None


def cache_only_operation() -> bool:
    """A cache-only execution never becomes paid after an admin mode change.

    Internal/automatic callers also inspect durable policy. This is a read-only
    connection: business cache reads must not acquire the ledger's writer lock.
    The actual transport boundary always rechecks policy under its shared lock.
    """
    if emergency_release_enabled():
        return False
    execution = _execution.get()
    if execution is not None and execution.cache_first:
        # A missing/down financial ledger must not stop local reads. At the
        # provider boundary the durable policy is checked before every send.
        return False
    if execution is not None and execution.operation_mode == "cache_only":
        return True
    try:
        with database.engine.connect() as conn:
            raw = conn.execute(select(CONFIG.c.config_json).where(CONFIG.c.id == 1)).scalar()
        if raw is None:
            return False
        cfg = CostConfiguration.model_validate_json(raw)
    except Exception:
        raise GoogleMapsCostBlocked("ledger_unavailable", status_code=503) from None
    if cfg.operation_mode == "cache_only":
        if execution is not None:
            execution.operation_mode = "cache_only"
        return True
    return False


def block_cache_only_lookup() -> None:
    """No fallback, expired cache reuse or TTL extension after a missing route."""
    execution = _execution.get()
    with _locked() as conn:
        _deny(conn, "cache_only", action_id=execution.action_id if execution else None)


def _usage(conn, policy=None):
    day, month = _periods(_now())
    result = {}
    for period, value in (("day", day), ("month", month)):
        statement = select(
            func.coalesce(func.sum(EVENTS.c.calls), 0),
            func.coalesce(func.sum(EVENTS.c.estimated_cost_micros), 0),
        ).where(EVENTS.c.kind.in_(("reserved", "opening")), EVENTS.c[period] == value)
        if policy is not None:
            statement = statement.where(EVENTS.c.policy == policy)
        calls, cost = conn.execute(statement).one()
        result[period] = {"calls": int(calls), "cost": int(cost)}
    return result


def _usage_view(usage):
    return {period: {"calls": value["calls"], "estimated_brl": _brl(value["cost"])} for period, value in usage.items()}


def _limits_view(limits):
    return {period: {"calls": getattr(limits, period).calls, "estimated_brl": float(getattr(limits, period).estimated_brl)} for period in ("action", "day", "month")}


def _remaining(cfg, usage):
    return {period: {
        "calls": max(0, getattr(cfg.limits, period).calls - usage[period]["calls"]),
        "estimated_brl": _brl(max(0, _micros(getattr(cfg.limits, period).estimated_brl) - usage[period]["cost"])),
    } for period in ("day", "month")}


def _unit_cost(cfg, sku):
    return _micros(cfg.prices_usd[sku] * cfg.fx_brl_per_usd_upper * cfg.price_multiplier)


def agenda_monitored(cfg, action):
    # Only registered human HTTP actions qualify. Automatic executions always
    # store action="automatic", even when calling Agenda services internally.
    return cfg is not None and cfg.agenda_budget_mode == "monitor" and action in ACTION_SPECS and action.startswith("agenda_")


def agenda_internal_policy(cfg, action):
    return (settings.GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION is False
            and agenda_cache_first_enabled(ACTION_SPECS.get(action)) and agenda_monitored(cfg, action))


def _reason_message(reason, cfg, action):
    if agenda_internal_policy(cfg, action):
        internal = {
            "day_reference_exceeded": "Referência diária atingida: a Agenda continua liberada com registro interno; lotes e tarefas extras mantêm seus bloqueios.",
            "month_reference_exceeded": "Referência mensal atingida: a Agenda continua liberada com registro interno; lotes e tarefas extras mantêm seus bloqueios.",
            "day_reference_may_exceed": "Esta execução pode ultrapassar a referência diária. A Agenda continua liberada com limite próprio e registro interno.",
            "month_reference_may_exceed": "Esta execução pode ultrapassar a referência mensal. A Agenda continua liberada com limite próprio e registro interno.",
            "pricing_review_due": "Revisão de preços/câmbio pendente: a Agenda continua liberada com a última estimativa cadastrada e registro interno. O custo real pode variar; cada execução mantém seu limite próprio. Lotes e automações continuam sujeitos às suas restrições.",
        }
        if reason in internal:
            return internal[reason]
    return REASONS.get(reason)


def _reference_alerts(cfg, usage, calls=0, cost=0):
    alerts = ["pricing_review_due"] if _pricing_review_due(cfg) else []
    for period in ("day", "month"):
        limit = getattr(cfg.limits, period)
        if usage[period]["calls"] >= limit.calls or usage[period]["cost"] >= _micros(limit.estimated_brl):
            alerts.append(f"{period}_reference_exceeded")
        elif usage[period]["calls"] + calls > limit.calls or usage[period]["cost"] + cost > _micros(limit.estimated_brl):
            alerts.append(f"{period}_reference_may_exceed")
    return alerts


def request_fingerprint(user_id: int, method: str, path: str, query: Any, body: Any) -> str:
    """Store a keyed digest only, including identity and all execution inputs."""
    if isinstance(query, str):
        query = parse_qs(query, keep_blank_values=True)
    else:
        query = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (query or {}).items()}
    canonical = json.dumps({
        "user_id": user_id, "method": method.upper(), "path": path.rstrip("/"),
        "query": query, "body": body,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    key = settings.SECRET_KEY
    if not key or len(key) < 32:
        raise GoogleMapsCostBlocked("invalid_configuration", status_code=503)
    return hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_preview(user_id, method, path, query=None, body=None, paid_call_required=False, route_estimate=None):
    spec = identify_action(method, path, query, body)
    if spec is None:
        return {"required": False, "blocked": False}
    if emergency_release_enabled():
        return {
            "required": False, "blocked": False, "reason": "emergency_release",
            "operation_mode": "temporary_open", "emergency_release": True,
            "paid_calls_allowed": True, "message": EMERGENCY_RELEASE_MESSAGE,
            "quote_id": None, "action": spec.label, "action_key": spec.key,
            "service": "Google Maps Platform", "services": list(spec.skus),
            "max_calls": None, "estimated_cost_min_brl": None,
            "estimated_cost_max_brl": None, "consumption": None,
            "remaining": None, "limits": None,
            "uncertainty": ["Custo e quantidade sem teto durante a liberação temporária; não há garantia de franquia gratuita."],
        }
    if agenda_cache_first_enabled(spec) and (not paid_call_required or (route_estimate is not None and route_estimate['max_calls'] == 0)):
        return {
            "required": False, "blocked": False, "reason": "local_attempt",
            "operation_mode": "cache_first", "paid_calls_allowed": False,
            "quote_id": None, "action": spec.label, "action_key": spec.key,
            "service": "Google Maps Platform", "services": list(spec.skus),
            "max_calls": 0, "estimated_cost_min_brl": 0, "estimated_cost_max_brl": 0,
            "route_estimate": route_estimate,
            "confirmation_mode": "per_action" if settings.GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION else "server_recorded",
            "message": ("A Agenda tentará usar uma rota válida já armazenada. Se precisar consultar o Google, pedirá confirmação antes do envio." if settings.GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION else "A Agenda prioriza a matriz em cache. Consultas necessárias são avaliadas e registradas internamente pelo servidor, conforme a política vigente."),
            "uncertainty": ["Esta prévia não envia chamadas. O servidor verifica a política vigente antes de qualquer envio."],
        }
    fingerprint = request_fingerprint(user_id, method, path, query, body)
    with _locked() as conn:
        cfg, revision = _configuration(conn, require_enabled=False)
        usage = _usage(conn)
        reason = _configuration_reason(cfg, action=spec.key)
        if (settings.GOOGLE_MAPS_AGENDA_REQUIRE_CONFIRMATION is False
                and agenda_cache_first_enabled(spec) and agenda_monitored(cfg, spec.key)
                and cfg.operation_mode == "paid_budget" and reason is None):
            return {"required": False, "blocked": False, "operation_mode": "cache_first",
                    "confirmation_mode": "server_recorded", "quote_id": None,
                    "action": spec.label, "action_key": spec.key,
                    "message": "A Agenda registra e limita cada execução no servidor, sem popup de custo."}
        if cfg is not None and cfg.operation_mode == "cache_only":
            return {
                "required": False, "blocked": reason is not None, "reason": reason,
                "operation_mode": "cache_only", "paid_calls_allowed": False,
                "message": REASONS[reason or "cache_only"], "quote_id": None,
                "action": spec.label, "action_key": spec.key,
                "service": "Google Maps Platform", "services": list(spec.skus),
                "max_calls": 0, "estimated_cost_min_brl": 0, "estimated_cost_max_brl": 0,
                "uncertainty": ["Saldo gratuito atual não verificado. Nenhuma nova consulta externa é permitida."],
                "consumption": _usage_view(usage), "remaining": _remaining(cfg, usage),
                "limits": _limits_view(cfg.limits),
            }
        max_calls, max_cost = 0, 0
        if cfg is not None:
            skus = tuple(route_estimate['services']) if route_estimate is not None else spec.skus
            unit = max(_unit_cost(cfg, sku) for sku in skus)
            cap = min(cfg.limits.action.calls, cfg.action_call_caps.get(spec.key, cfg.limits.action.calls))
            if route_estimate is not None:
                cap = min(cap, route_estimate['max_calls'])
            if spec.theoretical_cap is not None:
                cap = min(cap, spec.theoretical_cap)
            if cap <= 0 and reason is None:
                reason = "action_limit"
            if agenda_monitored(cfg, spec.key):
                # Daily/monthly budgets are references for the human Agenda.
                # Consent still has a finite call AND monetary envelope.
                max_calls = max(0, cap)
            else:
                budget = _micros(cfg.limits.action.estimated_brl)
                if budget < unit and reason is None:
                    reason = "action_limit"
                for period in ("day", "month"):
                    limit = getattr(cfg.limits, period)
                    cap = min(cap, limit.calls - usage[period]["calls"])
                    budget = min(budget, _micros(limit.estimated_brl) - usage[period]["cost"])
                    if (cap <= 0 or budget < unit) and reason is None:
                        reason = f"{period}_limit"
                max_calls = max(0, min(cap, budget // unit))
            max_cost = max_calls * unit
            if max_calls == 0 and reason is None:
                reason = "action_limit"
        if reason is None and cfg.clinic_geocode_manual_enabled and spec.key == "clinic_geocode":
            # A read-only quote creates no financial authorization or provider I/O.
            return {"required": False, "blocked": False, "operation_mode": "paid_budget",
                    "confirmation_mode": "server_recorded", "quote_id": None,
                    "action": spec.label, "action_key": spec.key, "max_calls": 1,
                    "estimated_cost_max_brl": _brl(max_cost),
                    "message": REASONS["clinic_manual_record"]}
        now = _now()
        quote_id = None
        if reason is None:
            quote_id = secrets.token_urlsafe(32)
            conn.execute(insert(ACTIONS).values(
                id=quote_id, user_id=user_id, fingerprint=fingerprint, action=spec.key,
                revision=revision, state="quoted", max_calls=max_calls, max_cost_micros=max_cost,
                used_calls=0, used_cost_micros=0, skus_json=json.dumps(skus),
                created_at=now, expires_at=now + QUOTE_TTL_SECONDS,
            ))
        else:
            _event(conn, kind="blocked", action=spec.key, user_id=user_id, reason=reason)
        return {
            "required": True, "blocked": reason is not None, "reason": reason,
            "pricing_review_due": _pricing_review_due(cfg),
            "pricing_reference_valid_until": cfg.pricing_valid_until.isoformat() if cfg else None,
            "budget_policy": "agenda_monitor" if agenda_monitored(cfg, spec.key) else "enforced",
            "financial_limit_enforced": not agenda_monitored(cfg, spec.key),
            "alerts": [_reason_message(key, cfg, spec.key) for key in _reference_alerts(cfg, usage, max_calls, max_cost)] if agenda_monitored(cfg, spec.key) else [],
            "operation_mode": "paid_budget", "paid_calls_allowed": reason is None,
            "message": REASONS.get(reason), "quote_id": quote_id, "action": spec.label,
            "action_key": spec.key, "service": "Google Maps Platform", "services": list(skus) if cfg is not None else list(spec.skus),
            "route_estimate": route_estimate,
            "max_calls": max_calls, "estimated_cost_min_brl": 0,
            "estimated_cost_max_brl": _brl(max_cost), "expires_at": _iso(now + QUOTE_TTL_SECONDS),
            "uncertainty": [
                "Preços/câmbio usam a última estimativa cadastrada; a data de revisão vencida gera alerta na Agenda monitorada, sem certificar o custo atual.",
                "Teto de execução verificável; consultas em cache podem reduzir o número real de chamadas.",
                "Estimativa conservadora: todas as unidades são consideradas pagas, sem descontar a franquia compartilhada da conta.",
                "A cobrança efetiva depende do SKU, faixas de volume da conta, câmbio e tributos. Dados do Billing têm atraso.",
                "Falhas e timeouts reservam custo; uma ação pode parar antes de terminar ao atingir o teto.",
            ],
            "consumption": _usage_view(usage), "remaining": _remaining(cfg, usage) if cfg else None,
            "limits": _limits_view(cfg.limits) if cfg else None,
        }


def confirm_preview(user_id: int, quote_id: str):
    with _locked() as conn:
        row = conn.execute(select(ACTIONS).where(ACTIONS.c.id == quote_id)).mappings().first()
        cfg, revision = _configuration(conn, action=row["action"] if row and not row["policy"] else None)
        if cfg.operation_mode == "cache_only":
            _deny(conn, "cache_only", user_id=user_id)
        if not row or row["user_id"] != user_id or row["state"] != "quoted" or row["expires_at"] <= _now():
            _deny(conn, "invalid_grant", user_id=user_id)
        if row["revision"] != revision:
            _deny(conn, "configuration_changed", action=row["action"], user_id=user_id)
        token = secrets.token_urlsafe(48)
        conn.execute(update(ACTIONS).where(ACTIONS.c.id == quote_id).values(state="confirmed", token_hash=_token_digest(token)))
        _event(conn, kind="confirmed", action=row["action"], action_id=row["id"], user_id=user_id)
        return {"token": token, "expires_at": _iso(row["expires_at"])}


def claim_execution(user_id, token, method, path, query=None, body=None) -> Execution:
    spec = identify_action(method, path, query, body)
    action = spec.key if spec else "unscoped"
    if emergency_release_enabled():
        # Authentication still runs in middleware. No token, ledger, fake
        # financial baseline or artificial high limit is needed for release.
        return Execution(secrets.token_urlsafe(32), operation_mode="temporary_open")
    if agenda_cache_first_enabled(spec) and not token:
        return Execution(secrets.token_urlsafe(32), operation_mode="cache_first", cache_first=True,
                         request_action=spec.key, request_user_id=user_id,
                         request_inputs=(method, path, query, body))
    with _locked() as conn:
        cfg, revision = _configuration(conn, action=action)
        if cfg.operation_mode == "cache_only":
            if spec is None:
                _deny(conn, "invalid_grant", action=action, user_id=user_id)
            action_id, now = secrets.token_urlsafe(32), _now()
            conn.execute(insert(ACTIONS).values(
                id=action_id, user_id=user_id,
                fingerprint=request_fingerprint(user_id, method, path, query, body),
                action=action, revision=revision, state="claimed", max_calls=0,
                max_cost_micros=0, used_calls=0, used_cost_micros=0, skus_json="[]",
                created_at=now, claimed_at=now, expires_at=now + EXECUTION_TTL_SECONDS,
            ))
            _event(conn, kind="cache_only", action=action, action_id=action_id, user_id=user_id)
            return Execution(action_id, operation_mode="cache_only")
        if cfg.clinic_geocode_manual_enabled and action == "clinic_geocode" and not token:
            # Only the authenticated explicit HTTP endpoint can claim this scope.
            # Each provider attempt still passes the shared atomic budget check.
            cost = _unit_cost(cfg, "geocoding")
            if cfg.limits.action.calls < 1 or _micros(cfg.limits.action.estimated_brl) < cost:
                _deny(conn, "action_limit", action=action, user_id=user_id)
            _check_periods(conn, cfg.limits, _usage(conn), cost,
                           action=action, action_id=None, user_id=user_id)
            action_id, now = secrets.token_urlsafe(32), _now()
            conn.execute(insert(ACTIONS).values(
                id=action_id, user_id=user_id,
                fingerprint=request_fingerprint(user_id, method, path, query, body),
                action=action, revision=revision, state="claimed", max_calls=1,
                max_cost_micros=cost, used_calls=0, used_cost_micros=0,
                skus_json=json.dumps(["geocoding"]), created_at=now,
                claimed_at=now, expires_at=now + EXECUTION_TTL_SECONDS,
            ))
            _event(conn, kind="internal_authorized", action=action, action_id=action_id,
                   user_id=user_id, reason="clinic_manual_record")
            return Execution(action_id, operation_mode="paid_budget")
        if not token:
            _deny(conn, "confirmation_required", action=action, user_id=user_id)
        row = conn.execute(select(ACTIONS).where(ACTIONS.c.token_hash == _token_digest(token))).mappings().first()
        expected = request_fingerprint(user_id, method, path, query, body)
        if not row or row["user_id"] != user_id or row["state"] != "confirmed" or row["expires_at"] <= _now() or not hmac.compare_digest(row["fingerprint"], expected):
            _deny(conn, "invalid_grant", action=action, user_id=user_id)
        if row["revision"] != revision:
            _deny(conn, "configuration_changed", action=action, user_id=user_id)
        now = _now()
        conn.execute(update(ACTIONS).where(ACTIONS.c.id == row["id"]).values(
            state="claimed", claimed_at=now, expires_at=now + EXECUTION_TTL_SECONDS,
        ))
        _event(conn, kind="claimed", action=row["action"], action_id=row["id"], user_id=user_id)
        return Execution(row["id"], operation_mode="paid_budget", cache_first=agenda_cache_first_enabled(spec))


def bind_execution(execution: Execution):
    return _execution.set(execution)


def reset_execution(token):
    _execution.reset(token)


def finish_execution(execution: Execution):
    execution.closed = True
    if execution.operation_mode in {"temporary_open", "cache_first"} or emergency_release_enabled():
        return
    if execution.automatic_policy and not execution.automatic_claimed:
        return
    with _locked() as conn:
        conn.execute(update(ACTIONS).where(ACTIONS.c.id == execution.action_id, ACTIONS.c.state == "claimed").values(state="finished"))


def _check_periods(conn, cfg_limits, usage, cost, *, action, action_id, user_id, policy=None):
    for period in ("day", "month"):
        limit = getattr(cfg_limits, period)
        if usage[period]["calls"] + 1 > limit.calls or usage[period]["cost"] + cost > _micros(limit.estimated_brl):
            _deny(conn, f"{period}_limit", action=action, action_id=action_id, user_id=user_id, policy=policy)


def authorize_google_call(sku: str) -> None:
    """Reserve ONE billable unit before EACH HTTP attempt, including retries.

    Distance Matrix callers must currently send exactly one origin x destination.
    Batch adapters must reserve each element; one HTTP request is not one unit.
    """
    execution = _execution.get()
    if emergency_release_enabled():
        if sku not in SKUS:
            raise GoogleMapsCostBlocked("sku_not_authorized")
        # Whitelisted metadata only: never log request inputs, IDs, tokens,
        # provider URLs, addresses, credentials or an invented zero cost.
        logger.warning("%s", json.dumps({
            "event": "google_maps_emergency_release_attempt", "sku": sku,
            "execution_type": "automatic" if execution and execution.automatic_policy else "http" if execution else "unscoped",
            "estimated_cost_brl": None, "financial_limit_enforced": False,
        }, sort_keys=True))
        return
    _load_internal_agenda_estimate(execution)
    with _locked() as conn:
        if execution is not None and execution.operation_mode == "cache_only":
            _deny(conn, "cache_only", action_id=execution.action_id, policy=execution.automatic_policy)
        # Use the durable human action, never a caller-supplied policy/name.
        row = (conn.execute(select(ACTIONS).where(ACTIONS.c.id == execution.action_id)).mappings().first()
               if execution is not None and not execution.automatic_policy else None)
        expiry_action = (row["action"] if row and not row["policy"] else
                         execution.request_action if execution is not None and execution.operation_mode == "cache_first" and not execution.automatic_policy else None)
        cfg, revision = _configuration(conn, action=expiry_action)
        if cfg.operation_mode == "cache_only":
            if execution is not None:
                execution.operation_mode = "cache_only"
            _deny(conn, "cache_only", action_id=execution.action_id if execution else None)
        if execution is None:
            _deny(conn, "confirmation_required")
        if execution.closed:
            _deny(conn, "invalid_grant")
        if execution.operation_mode == "cache_first":
            if _internal_agenda_requested(execution) and agenda_monitored(cfg, execution.request_action):
                _record_internal_agenda(conn, execution, cfg, revision)
                row = conn.execute(select(ACTIONS).where(ACTIONS.c.id == execution.action_id)).mappings().first()
            else:
                _deny(conn, "confirmation_required")
        if execution.automatic_policy and not execution.automatic_claimed:
            policy = cfg.automatic_policies.get(execution.automatic_policy)
            if not policy or not policy.enabled:
                _deny(conn, "automatic_policy_required", action="automatic", policy=execution.automatic_policy)
            if conn.execute(select(ACTIONS.c.id).where(ACTIONS.c.id == execution.action_id)).first():
                _deny(conn, "automatic_replay", action="automatic", policy=execution.automatic_policy)
            now = _now()
            conn.execute(insert(ACTIONS).values(
                id=execution.action_id, fingerprint=execution.automatic_fingerprint,
                action="automatic", policy=execution.automatic_policy,
                revision=revision, state="claimed", max_calls=min(cfg.limits.action.calls, policy.limits.action.calls),
                max_cost_micros=min(_micros(cfg.limits.action.estimated_brl), _micros(policy.limits.action.estimated_brl)),
                used_calls=0, used_cost_micros=0, skus_json=json.dumps(policy.skus), created_at=now,
                expires_at=now + EXECUTION_TTL_SECONDS, claimed_at=now,
            ))
            _event(conn, kind="claimed", action="automatic", action_id=execution.action_id, policy=execution.automatic_policy)
            execution.automatic_claimed = True
        if execution.automatic_policy:
            row = conn.execute(select(ACTIONS).where(ACTIONS.c.id == execution.action_id)).mappings().first()
        if not row or row["state"] != "claimed" or row["expires_at"] <= _now():
            _deny(conn, "invalid_grant")
        meta = {"action": row["action"], "action_id": row["id"], "user_id": row["user_id"], "policy": row["policy"]}
        if row["revision"] != revision:
            _deny(conn, "configuration_changed", **meta)
        if sku not in SKUS or sku not in json.loads(row["skus_json"]):
            _deny(conn, "sku_not_authorized", **meta)
        cost = _unit_cost(cfg, sku)
        monitored = agenda_monitored(cfg, row["action"]) and not row["policy"]
        cost_cap = row["max_cost_micros"] if monitored else min(row["max_cost_micros"], _micros(cfg.limits.action.estimated_brl))
        if row["used_calls"] + 1 > min(row["max_calls"], cfg.limits.action.calls) or row["used_cost_micros"] + cost > cost_cap:
            _deny(conn, "action_limit", **meta)
        usage = _usage(conn)
        if monitored:
            for reason in _reference_alerts(cfg, usage, 1, cost):
                # One sanitized warning per action/period; no double counting.
                exists = conn.execute(select(EVENTS.c.id).where(EVENTS.c.action_id == row["id"], EVENTS.c.kind == "budget_alert", EVENTS.c.reason == reason)).first()
                if not exists:
                    _event(conn, kind="budget_alert", reason=reason, **meta)
        else:
            _check_periods(conn, cfg.limits, usage, cost, **meta)
        if row["policy"]:
            policy = cfg.automatic_policies.get(row["policy"])
            if not policy or not policy.enabled:
                _deny(conn, "automatic_policy_required", **meta)
            _check_periods(conn, policy.limits, _usage(conn, row["policy"]), cost, **meta)
        conn.execute(update(ACTIONS).where(ACTIONS.c.id == row["id"]).values(
            used_calls=row["used_calls"] + 1, used_cost_micros=row["used_cost_micros"] + cost,
        ))
        _event(conn, kind="reserved", sku=sku, calls=1, cost=cost, **meta)


@contextmanager
def automatic_execution(policy_name: str, run_key: str):
    """Explicit machine consent; stable run_key must identify one job across retries.

    No existing worker is enrolled automatically. An administrator must configure
    this named policy and the caller must deliberately enter this context.
    """
    if not run_key or len(run_key) > 200 or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", policy_name):
        raise GoogleMapsCostBlocked("automatic_policy_required")
    digest = request_fingerprint(0, "AUTOMATIC", policy_name, None, run_key)
    # Lazy enrollment means unrelated chatbot work remains available. First paid
    # call claims the durable run atomically, including across worker restarts.
    execution = Execution("auto-" + digest[:59], policy_name, digest)
    token = bind_execution(execution)
    try:
        yield execution
    finally:
        reset_execution(token)
        finish_execution(execution)


automatic_action = automatic_execution


def update_configuration(user_id, config: CostConfiguration, expected_revision: int):
    with _locked() as conn:
        row = conn.execute(select(CONFIG).where(CONFIG.c.id == 1)).mappings().first()
        revision = row["revision"] if row else 0
        if revision != expected_revision:
            _deny(conn, "configuration_changed", action="configuration", user_id=user_id)
        initialized = conn.execute(select(EVENTS.c.id).where(EVENTS.c.kind == "opening").limit(1)).first()
        opening_fields = ("opening_usage", "opening_usage_as_of", "opening_usage_basis")
        if initialized:
            previous = CostConfiguration.model_validate_json(row["config_json"])
            if config.operation_mode == "cache_only":
                # Retain the real historical baseline on mode changes. Omission
                # is never interpreted as zero or a request to reset usage.
                if any(getattr(config, key) is not None and getattr(config, key) != getattr(previous, key) for key in opening_fields):
                    _deny(conn, "invalid_configuration", action="opening_usage", user_id=user_id)
                config = config.model_copy(update={key: getattr(previous, key) for key in opening_fields})
            elif any(getattr(config, key) != getattr(previous, key) for key in opening_fields):
                _deny(conn, "invalid_configuration", action="opening_usage", user_id=user_id)
        elif config.operation_mode == "cache_only":
            if any(getattr(config, key) is not None for key in opening_fields):
                _deny(conn, "invalid_configuration", action="opening_usage", user_id=user_id)
        elif config.enabled:
            day, month = _periods(_now())
            if config.opening_usage_as_of.isoformat() != day:
                _deny(conn, "invalid_configuration", action="opening_usage", user_id=user_id)
            opening = config.opening_usage
            for day_key, calls, cost in (
                (day, opening.day.calls, _micros(opening.day.estimated_brl)),
                ("", opening.month.calls - opening.day.calls, _micros(opening.month.estimated_brl) - _micros(opening.day.estimated_brl)),
            ):
                conn.execute(insert(EVENTS).values(
                    action="opening_usage", user_id=user_id, kind="opening",
                    reason=config.opening_usage_basis, calls=calls, estimated_cost_micros=cost,
                    day=day_key, month=month, created_at=_now(),
                ))
        values = {"revision": revision + 1, "config_json": config.model_dump_json(exclude_none=True), "updated_at": _now(), "updated_by": user_id}
        if row:
            conn.execute(update(CONFIG).where(CONFIG.c.id == 1).values(**values))
        else:
            conn.execute(insert(CONFIG).values(id=1, **values))
        _event(conn, kind="configuration", action="configuration", user_id=user_id)
    return get_status()


def get_status():
    if emergency_release_enabled():
        return {
            "agenda_cache_first": settings.GOOGLE_MAPS_AGENDA_CACHE_FIRST is True,
            "configured": False, "enabled": False, "blocked": False,
            "reason": "emergency_release", "revision": None,
            "operation_mode": "temporary_open", "emergency_release": True,
            "paid_calls_allowed": True, "message": EMERGENCY_RELEASE_MESSAGE,
            "config": None, "consumed_since": None, "opening_usage": None,
            "consumption": None, "remaining": None, "limits": None,
            "timezone": str(LEDGER_TIMEZONE), "automatic_policies": {},
            "history": [], "actions": [{"key": key, "label": spec.label} for key, spec in ACTION_SPECS.items()],
            "pricing_reference_date": PRICING_REFERENCE_DATE,
            "minimum_unit_prices_usd": {sku: str(price) for sku, price in MIN_UNIT_PRICES_USD.items()},
            "billing_note": "Estimativa indisponível durante a liberação temporária; pode haver cobrança. O histórico de limites permanece preservado, sem contabilizar estas chamadas como R$ 0. As tentativas são registradas nos logs do servidor, sem dados pessoais.",
        }
    with _locked() as conn:
        cfg, revision = _configuration(conn, require_enabled=False)
        usage = _usage(conn)
        reason = _configuration_reason(cfg, action="agenda_create" if cfg and cfg.agenda_budget_mode == "monitor" else None)
        history = conn.execute(select(EVENTS).order_by(EVENTS.c.id.desc()).limit(100)).mappings().all()
        started = conn.execute(select(func.min(EVENTS.c.created_at)).where(EVENTS.c.kind == "opening")).scalar()
        return {
            "agenda_cache_first": settings.GOOGLE_MAPS_AGENDA_CACHE_FIRST is True,
            "agenda_budget_mode": cfg.agenda_budget_mode if cfg else None,
            "agenda_confirmation_required": not agenda_internal_policy(cfg, "agenda_create"),
            "pricing_review_due": _pricing_review_due(cfg),
            "pricing_review_policy": "agenda_alert_only" if cfg and cfg.agenda_budget_mode == "monitor" else "enforced",
            "alerts": [_reason_message(key, cfg, "agenda_create") for key in _reference_alerts(cfg, usage)] if cfg and cfg.agenda_budget_mode == "monitor" else [],
            "configured": cfg is not None, "enabled": cfg.enabled if cfg else False,
            "blocked": reason is not None, "reason": reason, "revision": revision,
            "operation_mode": cfg.operation_mode if cfg else None,
            "paid_calls_allowed": cfg is not None and cfg.operation_mode == "paid_budget" and reason is None,
            "message": REASONS["cache_only"] if cfg and cfg.operation_mode == "cache_only" else REASONS.get(reason),
            "config": cfg.model_dump(mode="json", exclude_none=True) if cfg else None,
            "consumed_since": _iso(started) if started is not None else None,
            "opening_usage": cfg.opening_usage.model_dump(mode="json") if cfg and cfg.opening_usage else None,
            "consumption": _usage_view(usage), "remaining": _remaining(cfg, usage) if cfg else None,
            "limits": _limits_view(cfg.limits) if cfg else None, "timezone": str(LEDGER_TIMEZONE),
            "automatic_policies": {key: {"enabled": policy.enabled, "consumption": _usage_view(_usage(conn, key)), "limits": _limits_view(policy.limits)} for key, policy in (cfg.automatic_policies.items() if cfg else [])},
            "history": [{"id": item["id"], "created_at": _iso(item["created_at"]), "action": item["action"], "kind": item["kind"], "reason": item["reason"], "message": _reason_message(item["reason"], cfg, item["action"]), "sku": item["sku"], "policy": item["policy"], "calls": item["calls"], "estimated_brl": _brl(item["estimated_cost_micros"])} for item in history],
            "actions": [{"key": key, "label": spec.label} for key, spec in ACTION_SPECS.items()],
            "pricing_reference_date": PRICING_REFERENCE_DATE,
            "minimum_unit_prices_usd": {sku: str(price) for sku, price in MIN_UNIT_PRICES_USD.items()},
            "billing_note": ("Somente cache: teto de novas chamadas e novas cobranças R$ 0. O saldo da franquia gratuita não foi verificado; cobranças por uso anterior podem chegar com atraso. Consumo exibido é o histórico do controle, não o total da conta Google." if cfg and cfg.operation_mode == "cache_only" else "Estimativa de tentativas reservadas, não fatura Google. Não desconta franquia compartilhada nem descontos de volume; o Billing pode chegar com atraso. Falhas não devolvem a reserva."),
        }
