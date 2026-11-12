"""Age provenance shared by every patient consumer; never invent a birthday."""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app.utils.paciente_helpers import (
    IDADE_OBSERVACOES_RE, OPERATIONAL_TIME_ZONE, atualizar_observacoes_com_idade,
    data_civil_referencia, extrair_idade_paciente,
)

AGE_FIELDS = ("idade_informada", "idade_referencia", "idade_fonte")
AGE_INPUT_FIELDS = (*AGE_FIELDS, "idade", "data_nascimento")
_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(anos?|a|meses|m[eê]s|m|semanas?|s|dias?|d)\b", re.I)


def _get(record: Any, key: str, default=None):
    return record.get(key, default) if isinstance(record, dict) else getattr(record, key, default)


def hoje_operacional() -> date:
    return datetime.now(OPERATIONAL_TIME_ZONE).date()


def referencia_documento(exam: Any, created: Any = None) -> date | None:
    if exam:
        return data_civil_referencia(exam, data_calendario=True)
    if created is None:
        return hoje_operacional()
    if isinstance(created, date) and not isinstance(created, datetime):
        return created  # A civil date carries no UTC time to convert.
    try:
        instant = created if isinstance(created, datetime) else datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            # SQLite/legacy DateTime also stores date-only values at naive midnight.
            if (instant.hour, instant.minute, instant.second, instant.microsecond) == (0, 0, 0, 0):
                return instant.date()
            instant = instant.replace(tzinfo=timezone.utc)
        return data_civil_referencia(instant)
    except (TypeError, ValueError):
        return None


def parse_idade(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip().lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        text += " anos"
    tokens = list(_TOKEN.finditer(text))
    remaining = _TOKEN.sub("", text)
    if not tokens or re.sub(r"\s|\be\b|[,;+]", "", remaining):
        return None
    months = days = 0.0
    seen = set()
    for token in tokens:
        number = float(token[1].replace(",", "."))
        unit = token[2][0]
        if unit in seen:
            return None
        seen.add(unit)
        if unit in ("a", "m"):
            months += number * (12 if unit == "a" else 1)
        else:
            days += number * (7 if unit == "s" else 1)
    days += (months % 1) * 30
    if months > 6000 or days > 183000:
        return None
    return int(months), int(days)


def _months(start: date, end: date) -> int:
    if end < start:
        return -_months(end, start)
    count = (end.year - start.year) * 12 + end.month - start.month
    anniversary = min(start.day, calendar.monthrange(end.year, end.month)[1])
    return count - (end.day < anniversary)


def _format(months: int, days: int = 0) -> str:
    if months < 0 or days < 0:
        return ""
    if not months and days:
        return f"{days}d" if days < 30 else f"{days // 30}m"
    years, remainder = divmod(months, 12)
    return (f"{years}a" + (f" {remainder}m" if remainder else "")) if years else f"{remainder}m"


def _reference(value: Any = None, *, data_calendario=False) -> date | None:
    ref = hoje_operacional() if value is None else data_civil_referencia(value, data_calendario=data_calendario)
    return ref if ref and ref <= hoje_operacional() else None


def idade_do_paciente(record: Any, *, data_referencia=None, data_calendario=False) -> str:
    if record is None:
        return ""
    source = _get(record, "idade_fonte")
    birth = _get(record, "nascimento", _get(record, "data_nascimento"))
    if source not in ("idade", "nascimento"):
        # No guessed provenance/backfill for legacy rows.
        return extrair_idade_paciente(birth, _get(record, "observacoes"),
                                     data_referencia=data_referencia, data_calendario=data_calendario)
    ref = _reference(data_referencia, data_calendario=data_calendario)
    if ref is None:
        return ""
    if source == "idade":
        amount = parse_idade(_get(record, "idade_informada"))
        anchor = data_civil_referencia(_get(record, "idade_referencia"), data_calendario=True)
        if amount is None or anchor is None or anchor > hoje_operacional():
            return ""
        months, days = amount
        # Calendar arithmetic only: this estimate is never persisted as a birthday.
        year, month = divmod(anchor.year * 12 + anchor.month - 1 - months, 12)
        try:
            origin = date(year, month + 1, min(anchor.day, calendar.monthrange(year, month + 1)[1])) - timedelta(days=days)
        except (ValueError, OverflowError):
            return ""
        if ref < origin:
            return ""
        months = _months(origin, ref)
        formatted = _format(months, (ref - origin).days if not months else 0)
        return f"{formatted} (estimada)" if formatted else ""
    raw = str(birth or "").strip()
    if re.fullmatch(r"\d{4}", raw):
        years = ref.year - int(raw)
        if years < 0:
            return ""
        return "0–11 meses (estimada pelo ano)" if years == 0 else f"{years - 1}–{years} anos (estimada pelo ano)"
    born = data_civil_referencia(raw, data_calendario=True)
    if born is None or ref < born:
        return ""
    months = _months(born, ref)
    return _format(months, (ref - born).days if not months else 0)


def dados_idade_paciente(record: Any, **reference) -> dict:
    anchor = _get(record, "idade_referencia")
    return {
        "idade": idade_do_paciente(record, **reference),
        "data_nascimento": _get(record, "nascimento"),
        "idade_informada": _get(record, "idade_informada"),
        "idade_referencia": anchor.isoformat() if isinstance(anchor, (date, datetime)) else anchor,
        "idade_fonte": _get(record, "idade_fonte"),
    }


def alteracoes_idade(record: Any, payload: dict, *, data_referencia=None) -> dict:
    """Patch only explicit inputs. Preserve the anchor on unrelated/full-form saves."""
    changes: dict = {}
    if not any(key in payload for key in AGE_INPUT_FIELDS):
        # Older editors put the only explicit age input in observations.
        if "observacoes" not in payload or payload["observacoes"] == _get(record, "observacoes"):
            return changes
        match = IDADE_OBSERVACOES_RE.search(str(payload["observacoes"] or ""))
        previous = IDADE_OBSERVACOES_RE.search(str(_get(record, "observacoes") or ""))
        if not match or (previous and match[1].strip() == previous[1].strip()):
            return changes
        payload = {**payload, "idade": match[1].strip()}
    if "data_nascimento" in payload:
        raw = str(payload["data_nascimento"] or "").strip() or None
        current_birth = _get(record, "nascimento") or None
        selecting_birth = payload.get("idade_fonte") == "nascimento" and _get(record, "idade_fonte") != "nascimento"
        if raw and (raw != current_birth or selecting_birth):
            if re.fullmatch(r"\d{4}", raw):
                valid = 1000 <= int(raw) <= hoje_operacional().year
            else:
                born = data_civil_referencia(raw, data_calendario=True)
                valid = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) and born and born <= hoje_operacional())
            if not valid:
                raise HTTPException(422, "Informe nascimento válido (data ou ano), sem data futura.")
        if raw != current_birth:
            changes["nascimento"] = raw
    age_key = "idade_informada" if "idade_informada" in payload else "idade" if "idade" in payload else None
    age = str(payload.get(age_key) or "").strip() or None if age_key else _get(record, "idade_informada")
    clearing_legacy = bool(age_key and not age and payload.get("idade_fonte") == "idade"
                           and IDADE_OBSERVACOES_RE.search(str(_get(record, "observacoes") or "")))
    if age_key and (age != (_get(record, "idade_informada") or None) or clearing_legacy):
        if age and parse_idade(age) is None:
            raise HTTPException(422, "Informe idade em anos, meses, semanas ou dias (ex.: 12 anos ou 8 meses).")
        changes["idade_informada"] = age
        if age:
            reference = payload.get("idade_referencia") or data_referencia or hoje_operacional()
            anchor = _reference(reference, data_calendario=True)
            if anchor is None:
                raise HTTPException(422, "A data de referência da idade deve ser válida e não futura.")
            changes["idade_referencia"] = anchor
        else:
            changes["idade_referencia"] = None
        changes["observacoes"] = atualizar_observacoes_com_idade(
            payload.get("observacoes", _get(record, "observacoes")), age) or None
    explicit_source = payload.get("idade_fonte")
    if explicit_source not in (None, "", "idade", "nascimento"):
        raise HTTPException(422, "Origem da idade inválida.")
    birth = changes.get("nascimento", _get(record, "nascimento"))
    if explicit_source:
        source = explicit_source
    elif "idade_informada" in changes:
        source = "idade" if age else "nascimento" if birth else None
    elif "nascimento" in changes:
        source = "nascimento" if birth else "idade" if age else None
    else:
        source = _get(record, "idade_fonte")
    if source == "idade" and not age:
        source = "nascimento" if birth else None
    if source == "nascimento" and not birth:
        source = "idade" if age else None
    if source != _get(record, "idade_fonte"):
        changes["idade_fonte"] = source
    if source is None and _get(record, "idade_fonte") in ("idade", "nascimento"):
        # Clearing the last explicit source must not revive an old observations line.
        changes["observacoes"] = atualizar_observacoes_com_idade(
            payload.get("observacoes", _get(record, "observacoes")), None) or None
    # An explicit new observation may refresh an equal age on a different date.
    if age_key and age and payload.get("idade_referencia"):
        anchor = _reference(payload["idade_referencia"], data_calendario=True)
        if anchor is None:
            raise HTTPException(422, "Data de referência da idade inválida.")
        if anchor != _get(record, "idade_referencia"):
            changes["idade_referencia"] = anchor
    return changes
