from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

IDADE_OBSERVACOES_RE = re.compile(r"(?im)^Idade:\s*(.+?)\s*$")
OPERATIONAL_TIME_ZONE = ZoneInfo("America/Fortaleza")


def normalizar_sexo_paciente(sexo: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(sexo or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.strip().lower()

    if texto.startswith("f"):
        return "Fêmea"
    if texto.startswith("m"):
        return "Macho"
    return str(sexo or "").strip()


def data_civil_referencia(value: Any, *, data_calendario: bool = False) -> date | None:
    """Date-only exam fields and report instants have different midnight semantics."""
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            return value
        else:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        # Match the existing exam calendar policy: legacy midnight values keep
        # their nominal day. A data_laudo fallback is an instant, never this case.
        midnight = (parsed.hour, parsed.minute, parsed.second, parsed.microsecond) == (0, 0, 0, 0)
        if parsed.utcoffset() is not None and not (data_calendario and midnight):
            parsed = parsed.astimezone(OPERATIONAL_TIME_ZONE)
        return parsed.date()
    except (TypeError, ValueError, OverflowError):
        return None


def extrair_idade_paciente(
    nascimento: Any, observacoes: Any, *, data_referencia: Any = None,
    data_calendario: bool = False,
) -> str:
    referencia = date.today()
    if data_referencia is not None:
        referencia = data_civil_referencia(data_referencia, data_calendario=data_calendario)
        if referencia is None:
            return ""
        if referencia > datetime.now(OPERATIONAL_TIME_ZONE).date():
            return ""

    if nascimento:
        try:
            if isinstance(nascimento, datetime):
                data_nascimento = nascimento.date()
            elif isinstance(nascimento, date):
                data_nascimento = nascimento
            else:
                data_nascimento = datetime.strptime(str(nascimento), "%Y-%m-%d").date()

            if data_referencia is not None and referencia < data_nascimento:
                return ""
            meses = (referencia.year - data_nascimento.year) * 12 + referencia.month - data_nascimento.month
            # Historical studies require completed months; never turn the day
            # before the first birthday into an adult reference automatically.
            if data_referencia is not None and referencia.day < data_nascimento.day:
                meses -= 1
            if meses < 12:
                return f"{meses}m"

            anos = meses // 12
            meses_restantes = meses % 12
            if meses_restantes > 0:
                return f"{anos}a {meses_restantes}m"
            return f"{anos}a"
        except Exception:
            nascimento_texto = str(nascimento).strip()
            if nascimento_texto:
                return nascimento_texto

    match = IDADE_OBSERVACOES_RE.search(str(observacoes or ""))
    if match:
        return match.group(1).strip()
    return ""


def atualizar_observacoes_com_idade(observacoes: Any, idade: Any) -> str:
    idade_texto = str(idade or "").strip()
    observacoes_texto = str(observacoes or "").replace("\r\n", "\n")
    observacoes_sem_idade = IDADE_OBSERVACOES_RE.sub("", observacoes_texto)
    linhas_restantes = [linha.strip() for linha in observacoes_sem_idade.split("\n") if linha.strip()]

    if idade_texto:
        return "\n".join([f"Idade: {idade_texto}", *linhas_restantes]).strip()
    return "\n".join(linhas_restantes).strip()
