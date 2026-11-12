from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.configuracao import ConfiguracaoUsuario
from app.models.push_subscription import PushSubscription

try:
    import pywebpush as _pywebpush_module
    from cryptography.hazmat.primitives.asymmetric import ec as _cryptography_ec

    # Compatibilidade: pywebpush passa classe de curva (SECP256R1) em alguns fluxos,
    # mas versoes recentes do cryptography exigem instancia.
    if not getattr(_pywebpush_module, "_fortcordis_ec_compat_patched", False):
        _orig_generate_private_key = _pywebpush_module.ec.generate_private_key

        def _compat_generate_private_key(curve, backend=None):  # type: ignore[no-untyped-def]
            curve_obj = curve
            try:
                if isinstance(curve, type) and issubclass(curve, _cryptography_ec.EllipticCurve):
                    curve_obj = curve()
            except Exception:
                curve_obj = curve
            try:
                return _orig_generate_private_key(curve_obj)
            except TypeError:
                return _orig_generate_private_key(curve_obj, backend)

        _pywebpush_module.ec.generate_private_key = _compat_generate_private_key
        _pywebpush_module._fortcordis_ec_compat_patched = True

    WebPushException = _pywebpush_module.WebPushException
    webpush = _pywebpush_module.webpush
except Exception:  # pragma: no cover - fallback for environments sem dependencia instalada
    WebPushException = Exception  # type: ignore[assignment]
    webpush = None

AGENDA_PUSH_ACTIONS_ORDER = (
    "created",
    "updated",
    "status_changed",
    "cancelled",
    "deleted",
    "whatsapp_reserva_resposta",
)
FINANCEIRO_PUSH_ACTIONS_ORDER = ("os_generated", "payment_received", "os_deleted", "payment_pending")
WHATSAPP_PUSH_ACTIONS_ORDER = ("mensagem_recebida",)
PUSH_ACTIONS_ORDER = AGENDA_PUSH_ACTIONS_ORDER + FINANCEIRO_PUSH_ACTIONS_ORDER + WHATSAPP_PUSH_ACTIONS_ORDER
PUSH_ACTIONS_SET = set(PUSH_ACTIONS_ORDER)
HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER = ("os_deleted", "payment_pending")
HIGH_PRIORITY_DEFAULT_ACTIONS_SET = set(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER)
PUSH_PRIORITY_VALUES = {"high", "normal"}

_GROUPING_LOCK = threading.Lock()
_GROUPING_STATE: dict[tuple[int, str], dict[str, Any]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def normalize_agenda_push_actions(value: Any) -> list[str]:
    raw_values: list[Any] = []
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if text:
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        raw_values = parsed
                    else:
                        raw_values = [text]
                except Exception:
                    raw_values = text.split(",")
            else:
                raw_values = text.split(",")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        action = _clean_text(item).lower()
        if action in PUSH_ACTIONS_SET and action not in seen:
            normalized.append(action)
            seen.add(action)
    return normalized


def serialize_agenda_push_actions(value: Any) -> str:
    return ",".join(normalize_agenda_push_actions(value))


def get_default_agenda_push_actions() -> list[str]:
    return list(PUSH_ACTIONS_ORDER)


def get_effective_agenda_push_actions(value: Any) -> set[str]:
    if value is None:
        return set(PUSH_ACTIONS_ORDER)
    return set(normalize_agenda_push_actions(value))


def normalize_high_priority_push_actions(value: Any) -> list[str]:
    normalized = normalize_agenda_push_actions(value)
    if value is None:
        return list(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER)
    if not normalized:
        return []
    return normalized


def serialize_high_priority_push_actions(value: Any) -> str:
    return ",".join(normalize_high_priority_push_actions(value))


def get_default_high_priority_push_actions() -> list[str]:
    return list(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER)


def get_effective_high_priority_push_actions(value: Any) -> set[str]:
    if value is None:
        return set(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER)
    return set(normalize_high_priority_push_actions(value))


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _clean_text(value).lower()
    if text in {"1", "true", "yes", "sim", "on"}:
        return True
    if text in {"0", "false", "no", "nao", "off"}:
        return False
    return default


def _extract_subscription_payload(subscription_payload: dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    endpoint = _clean_text(subscription_payload.get("endpoint"))
    keys = subscription_payload.get("keys") or {}
    p256dh = _clean_text(keys.get("p256dh"))
    auth = _clean_text(keys.get("auth"))
    expiration_raw = subscription_payload.get("expirationTime", subscription_payload.get("expiration_time"))
    expiration_time = None if expiration_raw is None else _clean_text(expiration_raw)

    if not endpoint:
        raise ValueError("Endpoint da inscricao push nao informado.")
    if not p256dh or not auth:
        raise ValueError("Chaves da inscricao push invalidas.")

    return endpoint, p256dh, auth, expiration_time


def is_web_push_enabled() -> bool:
    public_key = _clean_text(settings.WEB_PUSH_VAPID_PUBLIC_KEY)
    private_key = _clean_text(settings.WEB_PUSH_VAPID_PRIVATE_KEY)
    return bool(public_key and private_key and webpush is not None)


def get_web_push_public_key() -> str:
    return _clean_text(settings.WEB_PUSH_VAPID_PUBLIC_KEY)


def upsert_user_push_subscription(
    db: Session,
    *,
    user_id: int,
    subscription_payload: dict[str, Any],
    user_agent: Optional[str] = None,
    commit: bool = True,
) -> PushSubscription:
    if not isinstance(subscription_payload, dict):
        raise ValueError("Payload de inscricao push invalido.")

    endpoint, p256dh, auth, expiration_time = _extract_subscription_payload(subscription_payload)
    now = _utc_now()

    registro = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if not registro:
        registro = PushSubscription(endpoint=endpoint, user_id=user_id)
        db.add(registro)

    registro.user_id = user_id
    registro.p256dh = p256dh
    registro.auth = auth
    registro.expiration_time = expiration_time
    registro.user_agent = _clean_text(user_agent) or registro.user_agent
    registro.active = True
    registro.last_failure_at = None
    registro.failure_reason = None
    registro.updated_at = now

    if commit:
        db.commit()
        db.refresh(registro)
    else:
        db.flush()

    return registro


def deactivate_user_push_subscriptions(
    db: Session,
    *,
    user_id: int,
    endpoint: Optional[str] = None,
    commit: bool = True,
) -> int:
    query = db.query(PushSubscription).filter(PushSubscription.user_id == user_id)
    if endpoint:
        query = query.filter(PushSubscription.endpoint == endpoint)

    registros = query.all()
    if not registros:
        return 0

    now = _utc_now()
    total = 0
    for registro in registros:
        if not registro.active:
            continue
        registro.active = False
        registro.updated_at = now
        total += 1

    if commit:
        db.commit()
    else:
        db.flush()
    return total


def _user_push_preferences_map(db: Session, user_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not user_ids:
        return {}

    rows = (
        db.query(
            ConfiguracaoUsuario.user_id,
            ConfiguracaoUsuario.notificacoes_push,
            ConfiguracaoUsuario.notificacoes_push_tipos,
            ConfiguracaoUsuario.notificacoes_push_prioridade_alta_tipos,
            ConfiguracaoUsuario.notificacoes_push_agrupar,
            ConfiguracaoUsuario.notificacoes_push_lembrete_pendencias,
        )
        .filter(ConfiguracaoUsuario.user_id.in_(user_ids))
        .all()
    )
    resultado: dict[int, dict[str, Any]] = {}
    for (
        user_id,
        notificacoes_push,
        notificacoes_push_tipos,
        notificacoes_push_prioridade_alta_tipos,
        notificacoes_push_agrupar,
        notificacoes_push_lembrete_pendencias,
    ) in rows:
        resultado[int(user_id)] = {
            "enabled": _coerce_bool(notificacoes_push, default=True),
            "allowed_actions": get_effective_agenda_push_actions(notificacoes_push_tipos),
            "high_priority_actions": get_effective_high_priority_push_actions(
                notificacoes_push_prioridade_alta_tipos
            ),
            "grouping_enabled": _coerce_bool(notificacoes_push_agrupar, default=True),
            "reminder_enabled": _coerce_bool(notificacoes_push_lembrete_pendencias, default=True),
        }
    return resultado


def _get_target_subscriptions(
    db: Session,
    *,
    exclude_user_id: Optional[int] = None,
    notification_action: Optional[str] = None,
    include_user_ids: Optional[set[int]] = None,
) -> tuple[list[PushSubscription], dict[int, dict[str, Any]]]:
    query = db.query(PushSubscription).filter(PushSubscription.active == True)
    if exclude_user_id is not None:
        query = query.filter(PushSubscription.user_id != exclude_user_id)
    if include_user_ids:
        query = query.filter(PushSubscription.user_id.in_(include_user_ids))

    subscriptions = query.all()
    if not subscriptions:
        return [], {}

    notification_action_norm = _clean_text(notification_action).lower()
    user_ids = {int(subscription.user_id) for subscription in subscriptions}
    preferencias = _user_push_preferences_map(db, user_ids)

    default_pref = {
        "enabled": True,
        "allowed_actions": set(PUSH_ACTIONS_ORDER),
        "high_priority_actions": set(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER),
        "grouping_enabled": True,
        "reminder_enabled": True,
    }

    # Se nao houver linha em configuracoes_usuario, o default do sistema e True + todos os eventos.
    filtered = [
        subscription
        for subscription in subscriptions
        if (
            bool(preferencias.get(int(subscription.user_id), default_pref)["enabled"])
            and (
                not notification_action_norm
                or notification_action_norm
                in preferencias.get(int(subscription.user_id), default_pref)["allowed_actions"]
            )
            and (
                notification_action_norm != "payment_pending"
                or bool(preferencias.get(int(subscription.user_id), default_pref)["reminder_enabled"])
            )
        )
    ]
    return filtered, preferencias


def _mark_success(subscription: PushSubscription, when: datetime) -> None:
    subscription.last_success_at = when
    subscription.last_failure_at = None
    subscription.failure_reason = None
    subscription.updated_at = when


def _mark_failure(subscription: PushSubscription, when: datetime, reason: str, deactivate: bool = False) -> None:
    subscription.last_failure_at = when
    subscription.failure_reason = _clean_text(reason)[:800]
    subscription.updated_at = when
    if deactivate:
        subscription.active = False


def _normalize_priority(value: Any) -> str:
    priority = _clean_text(value).lower()
    if priority in PUSH_PRIORITY_VALUES:
        return priority
    return "normal"


def _resolve_priority_for_user(
    *,
    payload: dict[str, Any],
    notification_action: str,
    user_pref: dict[str, Any],
) -> str:
    explicit = _normalize_priority(payload.get("priority"))
    if explicit != "normal" or _clean_text(payload.get("priority")):
        return explicit

    if notification_action and notification_action in set(user_pref.get("high_priority_actions") or set()):
        return "high"
    return "normal"


def _cleanup_grouping_state(now: datetime) -> None:
    stale_keys = []
    for key, state in _GROUPING_STATE.items():
        expires_at = state.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= now:
            stale_keys.append(key)
    for key in stale_keys:
        _GROUPING_STATE.pop(key, None)


def _apply_grouping_for_user(
    *,
    payload: dict[str, Any],
    user_id: int,
    user_pref: dict[str, Any],
    notification_action: str,
) -> dict[str, Any]:
    if not bool(user_pref.get("grouping_enabled", True)):
        return payload

    group_key = _clean_text(payload.get("group_key"))
    if not group_key:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        module = _clean_text(data.get("module"))
        os_id = _clean_text(data.get("os_id"))
        agendamento_id = _clean_text(data.get("agendamento_id"))
        resource_ref = os_id or agendamento_id
        if module and notification_action and resource_ref:
            group_key = f"{module}:{notification_action}:{resource_ref}"
        else:
            return payload

    window_seconds = int(settings.WEB_PUSH_GROUP_WINDOW_SECONDS or 90)
    if window_seconds < 10:
        window_seconds = 10

    now = _utc_now()
    lock_key = (int(user_id), group_key)
    grouped_payload = dict(payload)
    grouped_payload["group_key"] = group_key

    with _GROUPING_LOCK:
        _cleanup_grouping_state(now)
        state = _GROUPING_STATE.get(lock_key)
        if not state or not isinstance(state.get("expires_at"), datetime) or state["expires_at"] <= now:
            _GROUPING_STATE[lock_key] = {
                "count": 1,
                "expires_at": now + timedelta(seconds=window_seconds),
            }
            return grouped_payload

        count = int(state.get("count") or 1) + 1
        state["count"] = count
        state["expires_at"] = now + timedelta(seconds=window_seconds)

    grouped_payload["stack_notifications"] = False
    grouped_payload["tag"] = f"group-{group_key}"
    grouped_payload["title"] = f"{_clean_text(payload.get('title'))} (+{count - 1})"
    grouped_payload["body"] = (
        f"{_clean_text(payload.get('body'))} | {count} notificacoes semelhantes em sequencia."
    )
    grouped_payload["grouped_count"] = count
    return grouped_payload


def send_web_push_payload(
    db: Session,
    *,
    payload: dict[str, Any],
    exclude_user_id: Optional[int] = None,
    notification_action: Optional[str] = None,
    include_user_ids: Optional[set[int]] = None,
) -> dict[str, int]:
    if not is_web_push_enabled():
        return {"sent": 0, "failed": 0, "deactivated": 0}

    subscriptions, preferencias = _get_target_subscriptions(
        db,
        exclude_user_id=exclude_user_id,
        notification_action=notification_action,
        include_user_ids=include_user_ids,
    )
    if not subscriptions:
        return {"sent": 0, "failed": 0, "deactivated": 0}

    vapid_private_key = _clean_text(settings.WEB_PUSH_VAPID_PRIVATE_KEY)
    vapid_subject = _clean_text(settings.WEB_PUSH_VAPID_CLAIMS_SUB) or "mailto:suporte@fortcordis.local"
    action_norm = _clean_text(notification_action).lower()
    default_pref = {
        "enabled": True,
        "allowed_actions": set(PUSH_ACTIONS_ORDER),
        "high_priority_actions": set(HIGH_PRIORITY_DEFAULT_ACTIONS_ORDER),
        "grouping_enabled": True,
    }

    sent = 0
    failed = 0
    deactivated = 0

    for subscription in subscriptions:
        user_id = int(subscription.user_id)
        user_pref = preferencias.get(user_id, default_pref)
        payload_for_user = dict(payload or {})
        payload_for_user = _apply_grouping_for_user(
            payload=payload_for_user,
            user_id=user_id,
            user_pref=user_pref,
            notification_action=action_norm,
        )
        priority = _resolve_priority_for_user(
            payload=payload_for_user,
            notification_action=action_norm,
            user_pref=user_pref,
        )
        payload_for_user["priority"] = priority
        if priority == "high":
            payload_for_user["require_interaction"] = True

        serialized = json.dumps(payload_for_user, ensure_ascii=False)
        now = _utc_now()
        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.p256dh,
                "auth": subscription.auth,
            },
        }
        if subscription.expiration_time:
            subscription_info["expirationTime"] = subscription.expiration_time

        try:
            webpush(
                subscription_info=subscription_info,
                data=serialized,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_subject},
            )
            _mark_success(subscription, now)
            sent += 1
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status_code = int(getattr(response, "status_code", 0) or 0)
            must_deactivate = status_code in {404, 410}
            _mark_failure(subscription, now, str(exc), deactivate=must_deactivate)
            if must_deactivate:
                deactivated += 1
            failed += 1
        except Exception as exc:  # pragma: no cover - fallback defensivo
            _mark_failure(subscription, now, str(exc), deactivate=False)
            failed += 1

    db.commit()
    return {"sent": sent, "failed": failed, "deactivated": deactivated}


_WHATSAPP_RESERVA_RESPOSTA_TITULOS = {
    "presenca_confirmada": "Presenca registrada pelo WhatsApp",
    "confirmado": "Reserva confirmada pelo WhatsApp",
    "ja_confirmado": "Reserva ja estava confirmada",
    "confirmacao_apos_prazo": "Confirmacao recebida apos o prazo",
    "confirmacao_dados_pendentes": "Confirmacao com cadastro pendente",
    "revisao_manual": "Resposta do WhatsApp exige revisao manual",
    "alteracao_solicitada": "Cliente solicitou alteracao pelo WhatsApp",
    "agendamento_nao_encontrado": "Resposta do WhatsApp sem agendamento correspondente",
}

_WHATSAPP_RESERVA_RESPOSTA_CORPOS = {
    "presenca_confirmada": "Cliente confirmou a presenca pelo lembrete; horario e status da agenda foram preservados.",
    "confirmado": "Reserva confirmada com sucesso pelo cliente via WhatsApp.",
    "ja_confirmado": "Cliente confirmou, mas a reserva ja estava confirmada.",
    "confirmacao_apos_prazo": "Cliente confirmou apos o prazo; o horario nao foi reativado automaticamente.",
    "confirmacao_dados_pendentes": "Cliente confirmou, mas paciente e tutor ainda precisam ser vinculados.",
    "revisao_manual": "Resposta recebida, mas o status atual do agendamento exige revisao manual.",
    "alteracao_solicitada": "Cliente pediu alteracao do agendamento pelo WhatsApp; confira o servico e o horario solicitados.",
    "agendamento_nao_encontrado": "Resposta recebida para um agendamento que nao foi encontrado.",
}


def _build_whatsapp_reserva_resposta_body(data: dict[str, Any]) -> str:
    resultado = _clean_text(data.get("result")).lower()
    status = _clean_text(data.get("status"))
    texto = _WHATSAPP_RESERVA_RESPOSTA_CORPOS.get(resultado, "Resposta de confirmacao do WhatsApp recebida.")
    if status:
        texto = f"{texto} Status atual: {status}."
    return texto


def _build_agenda_body(action: str, data: dict[str, Any]) -> str:
    action_norm = _clean_text(action).lower()
    if action_norm == "whatsapp_reserva_resposta":
        return _build_whatsapp_reserva_resposta_body(data)

    paciente = _first_text(data.get("paciente_nome"), data.get("paciente"))
    clinica = _first_text(data.get("clinica_nome"), data.get("clinica"))
    servico = _first_text(data.get("servico_nome"), data.get("servico"))
    data_texto = _clean_text(data.get("data"))
    hora_texto = _clean_text(data.get("hora"))
    horario = f"{data_texto} {hora_texto}".strip()

    parts: list[str] = []
    if paciente:
        parts.append(f"Paciente: {paciente}")
    if clinica:
        parts.append(f"Clinica: {clinica}")
    if servico:
        parts.append(f"Servico: {servico}")
    if horario:
        parts.append(f"Horario: {horario}")

    if not parts:
        return "Agenda atualizada."
    return " | ".join(parts)


def _build_agenda_title(action: str, agendamento_id: int, data: dict[str, Any]) -> str:
    action_norm = _clean_text(action).lower()

    if action_norm == "created":
        return f"Novo agendamento #{agendamento_id}"
    if action_norm == "updated":
        return f"Agendamento #{agendamento_id} atualizado"
    if action_norm == "deleted":
        return f"Agendamento #{agendamento_id} removido"
    if action_norm == "status_changed":
        anterior = _first_text(data.get("status_anterior"))
        novo = _first_text(data.get("status_novo"), data.get("status"))
        if anterior or novo:
            return f"Status #{agendamento_id}: {anterior or '?'} -> {novo or '?'}"
        return f"Status do agendamento #{agendamento_id} alterado"
    if action_norm == "cancelled":
        return f"Agendamento #{agendamento_id} cancelado"
    if action_norm == "whatsapp_reserva_resposta":
        resultado = _clean_text(data.get("result")).lower()
        descricao = _WHATSAPP_RESERVA_RESPOSTA_TITULOS.get(resultado, "Resposta do WhatsApp recebida")
        return f"{descricao} - agendamento #{agendamento_id}"
    return f"Agenda atualizada #{agendamento_id}"


def _build_financeiro_title(action: str, os_id: int, data: dict[str, Any]) -> str:
    numero_os = _first_text(data.get("numero_os"))
    os_ref = numero_os or f"#{os_id}"
    action_norm = _clean_text(action).lower()

    if action_norm == "os_generated":
        return f"Ordem de servico {os_ref} gerada"
    if action_norm == "payment_received":
        return f"Pagamento recebido da OS {os_ref}"
    if action_norm == "os_deleted":
        return f"Ordem de servico {os_ref} excluida"
    if action_norm == "payment_pending":
        return f"OS {os_ref} segue pendente de pagamento"
    return f"Atualizacao financeira da OS {os_ref}"


def _build_financeiro_body(data: dict[str, Any]) -> str:
    paciente = _first_text(data.get("paciente_nome"), data.get("paciente"))
    clinica = _first_text(data.get("clinica_nome"), data.get("clinica"))
    servico = _first_text(data.get("servico_nome"), data.get("servico"))
    valor = _first_text(data.get("valor_final"), data.get("valor"))
    forma_pagamento = _first_text(data.get("forma_pagamento"))
    lembrete_horas = _first_text(data.get("lembrete_horas"))

    parts: list[str] = []
    if paciente:
        parts.append(f"Paciente: {paciente}")
    if clinica:
        parts.append(f"Clinica: {clinica}")
    if servico:
        parts.append(f"Servico: {servico}")
    if valor:
        parts.append(f"Valor: R$ {valor}")
    if forma_pagamento:
        parts.append(f"Pagamento: {forma_pagamento}")
    if lembrete_horas:
        parts.append(f"Pendente ha {lembrete_horas}h")

    if not parts:
        return "Financeiro atualizado."
    return " | ".join(parts)


def send_agenda_push_notification(
    db: Session,
    *,
    action: str,
    agendamento_id: int,
    data: Optional[dict[str, Any]] = None,
    actor_user_id: Optional[int] = None,
) -> dict[str, int]:
    action_norm = _clean_text(action).lower()
    safe_data = dict(data or {})
    notification_id = uuid4().hex
    target_url = f"/agenda?agendamento_id={int(agendamento_id)}&push_action={action_norm or 'updated'}"
    payload = {
        "title": _build_agenda_title(action_norm, agendamento_id, safe_data),
        "body": _build_agenda_body(action_norm, safe_data),
        "url": target_url,
        "tag": f"agenda-{action_norm or 'updated'}-{agendamento_id}",
        "group_key": f"agenda:{action_norm or 'updated'}:{int(agendamento_id)}",
        "notification_id": notification_id,
        "stack_notifications": True,
        "require_interaction": True,
        "allow_snooze": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "module": "agenda",
            "action": action_norm or "updated",
            "agendamento_id": int(agendamento_id),
            "notification_id": notification_id,
            "resource_type": "agendamento",
            "resource_id": int(agendamento_id),
            "url": target_url,
        },
    }
    return send_web_push_payload(
        db,
        payload=payload,
        exclude_user_id=actor_user_id,
        notification_action=action_norm,
    )


def send_financeiro_push_notification(
    db: Session,
    *,
    action: str,
    os_id: int,
    data: Optional[dict[str, Any]] = None,
    actor_user_id: Optional[int] = None,
    priority: Optional[str] = None,
) -> dict[str, int]:
    action_norm = _clean_text(action).lower()
    safe_data = dict(data or {})
    notification_id = uuid4().hex
    target_url = f"/financeiro?aba=ordens&os_id={int(os_id)}&push_action={action_norm or 'os_generated'}"
    payload = {
        "title": _build_financeiro_title(action_norm, os_id, safe_data),
        "body": _build_financeiro_body(safe_data),
        "url": target_url,
        "tag": f"financeiro-{action_norm or 'os_generated'}-os-{os_id}",
        "group_key": f"financeiro:{action_norm or 'os_generated'}:{int(os_id)}",
        "notification_id": notification_id,
        "stack_notifications": True,
        "require_interaction": True,
        "allow_snooze": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "module": "financeiro",
            "action": action_norm or "os_generated",
            "os_id": int(os_id),
            "notification_id": notification_id,
            "resource_type": "ordem_servico",
            "resource_id": int(os_id),
            "url": target_url,
        },
    }
    normalized_priority = _normalize_priority(priority)
    if _clean_text(priority):
        payload["priority"] = normalized_priority
    return send_web_push_payload(
        db,
        payload=payload,
        exclude_user_id=actor_user_id,
        notification_action=action_norm,
    )


def _build_whatsapp_message_title(contact_label: str) -> str:
    return f"Nova mensagem de {contact_label}" if contact_label else "Nova mensagem no WhatsApp"


def _build_whatsapp_message_body(body_preview: str) -> str:
    text = _clean_text(body_preview)
    if not text:
        return "Abra a Central de Atendimento para ver a mensagem."
    return text[:160]


def send_whatsapp_message_push_notification(
    db: Session,
    *,
    conversation_id: str,
    contact_label: Optional[str] = None,
    body_preview: Optional[str] = None,
) -> dict[str, int]:
    action_norm = "mensagem_recebida"
    notification_id = uuid4().hex
    target_url = "/whatsapp-stage"
    safe_contact = _clean_text(contact_label)
    payload = {
        "title": _build_whatsapp_message_title(safe_contact),
        "body": _build_whatsapp_message_body(body_preview or ""),
        "url": target_url,
        "tag": f"whatsapp-mensagem-{conversation_id}",
        "group_key": f"whatsapp:{action_norm}:{conversation_id}",
        "notification_id": notification_id,
        "stack_notifications": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "module": "whatsapp",
            "action": action_norm,
            "conversation_id": conversation_id,
            "notification_id": notification_id,
            "resource_type": "conversation",
            "resource_id": conversation_id,
            "url": target_url,
        },
    }
    return send_web_push_payload(
        db,
        payload=payload,
        notification_action=action_norm,
    )
