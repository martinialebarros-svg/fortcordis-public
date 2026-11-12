"""Helpers para configuracao de funcionamento da agenda."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

DIA_SEMANA_KEYS = ["1", "2", "3", "4", "5", "6", "7"]

NOMES_DIA_SEMANA = {
    "1": "segunda-feira",
    "2": "terca-feira",
    "3": "quarta-feira",
    "4": "quinta-feira",
    "5": "sexta-feira",
    "6": "sabado",
    "7": "domingo",
}

DEFAULT_AGENDA_SEMANAL = {
    "1": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "2": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "3": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "4": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "5": {"ativo": True, "inicio": "08:00", "fim": "14:00"},
    "6": {"ativo": True, "inicio": "09:00", "fim": "13:00"},
    "7": {"ativo": False, "inicio": "09:00", "fim": "13:00"},
}

DEFAULT_EXCECAO_INICIO = "08:00"
DEFAULT_EXCECAO_FIM = "18:00"


def _normalizar_hora_hhmm(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    raw = value.strip()
    if len(raw) != 5 or raw[2] != ":":
        return fallback

    hora_str = raw[:2]
    minuto_str = raw[3:]
    if not (hora_str.isdigit() and minuto_str.isdigit()):
        return fallback

    hora = int(hora_str)
    minuto = int(minuto_str)
    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return fallback
    return f"{hora:02d}:{minuto:02d}"


def _hora_em_minutos(value: str) -> int:
    hora_str, minuto_str = value.split(":")
    return int(hora_str) * 60 + int(minuto_str)


def carregar_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None

    texto = raw.strip()
    if not texto:
        return None

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None


def normalizar_agenda_semanal(payload: Any) -> dict[str, dict[str, Any]]:
    source = payload if isinstance(payload, dict) else {}
    agenda: dict[str, dict[str, Any]] = {}

    for dia in DIA_SEMANA_KEYS:
        default = DEFAULT_AGENDA_SEMANAL[dia]
        item = source.get(dia) if isinstance(source.get(dia), dict) else {}

        ativo = item.get("ativo", default["ativo"])
        inicio = _normalizar_hora_hhmm(item.get("inicio"), default["inicio"])
        fim = _normalizar_hora_hhmm(item.get("fim"), default["fim"])

        if _hora_em_minutos(inicio) >= _hora_em_minutos(fim):
            inicio = default["inicio"]
            fim = default["fim"]

        agenda[dia] = {
            "ativo": bool(ativo),
            "inicio": inicio,
            "fim": fim,
        }

    return agenda


def normalizar_agenda_feriados(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        return []

    itens: list[dict[str, str]] = []
    datas_vistas: set[str] = set()

    for item in payload:
        if isinstance(item, str):
            data_raw = item.strip()
            descricao_raw = ""
            tipo_raw = "local"
        elif isinstance(item, dict):
            data_raw = str(item.get("data", "")).strip()
            descricao_raw = str(item.get("descricao", "")).strip()
            tipo_raw = str(item.get("tipo", "local")).strip().lower()
        else:
            continue

        if not data_raw:
            continue

        try:
            data_iso = datetime.strptime(data_raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            continue

        if data_iso in datas_vistas:
            continue
        datas_vistas.add(data_iso)

        tipo = "nacional" if tipo_raw == "nacional" else "local"
        itens.append(
            {
                "data": data_iso,
                "descricao": descricao_raw,
                "tipo": tipo,
            }
        )

    itens.sort(key=lambda row: row["data"])
    return itens


def normalizar_agenda_excecoes(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []

    mapa_itens: dict[str, dict[str, Any]] = {}

    for item in payload:
        if not isinstance(item, dict):
            continue

        data_raw = str(item.get("data", "")).strip()
        if not data_raw:
            continue

        try:
            data_iso = datetime.strptime(data_raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            continue

        ativo = bool(item.get("ativo", True))
        inicio = _normalizar_hora_hhmm(item.get("inicio"), DEFAULT_EXCECAO_INICIO)
        fim = _normalizar_hora_hhmm(item.get("fim"), DEFAULT_EXCECAO_FIM)
        if _hora_em_minutos(inicio) >= _hora_em_minutos(fim):
            inicio = DEFAULT_EXCECAO_INICIO
            fim = DEFAULT_EXCECAO_FIM

        motivo = str(item.get("motivo", "") or "").strip()

        mapa_itens[data_iso] = {
            "data": data_iso,
            "ativo": ativo,
            "inicio": inicio,
            "fim": fim,
            "motivo": motivo,
        }

    itens = list(mapa_itens.values())
    itens.sort(key=lambda row: row["data"])
    return itens


def carregar_agenda_semanal(raw: Any) -> dict[str, dict[str, Any]]:
    payload = carregar_json(raw)
    return normalizar_agenda_semanal(payload)


def carregar_agenda_feriados(raw: Any) -> list[dict[str, str]]:
    payload = carregar_json(raw)
    return normalizar_agenda_feriados(payload)


def carregar_agenda_excecoes(raw: Any) -> list[dict[str, Any]]:
    payload = carregar_json(raw)
    return normalizar_agenda_excecoes(payload)


def serializar_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def obter_feriado(data_ref: date, agenda_feriados: list[dict[str, str]]) -> dict[str, str] | None:
    iso = data_ref.isoformat()
    for item in agenda_feriados:
        if item.get("data") == iso:
            return item
    return None


def obter_excecao_data(data_ref: date, agenda_excecoes: list[dict[str, Any]]) -> dict[str, Any] | None:
    iso = data_ref.isoformat()
    for item in agenda_excecoes:
        if item.get("data") == iso:
            return item
    return None


def validar_horario_agenda(
    inicio_local: datetime,
    fim_local: datetime,
    agenda_semanal: dict[str, dict[str, Any]],
    agenda_feriados: list[dict[str, str]],
    agenda_excecoes: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    if fim_local <= inicio_local:
        return False, "Horario invalido: o fim precisa ser maior que o inicio."

    if inicio_local.date() != fim_local.date():
        return False, "Agendamento deve comecar e terminar no mesmo dia."

    excecoes = agenda_excecoes or []
    excecao = obter_excecao_data(inicio_local.date(), excecoes)
    if excecao is not None:
        if not bool(excecao.get("ativo", False)):
            motivo = str(excecao.get("motivo") or "").strip()
            complemento = f" ({motivo})" if motivo else ""
            return False, f"Agenda fechada por excecao de data{complemento}."
        inicio_janela = _normalizar_hora_hhmm(excecao.get("inicio"), DEFAULT_EXCECAO_INICIO)
        fim_janela = _normalizar_hora_hhmm(excecao.get("fim"), DEFAULT_EXCECAO_FIM)
    else:
        feriado = obter_feriado(inicio_local.date(), agenda_feriados)
        if feriado:
            descricao = str(feriado.get("descricao") or "").strip()
            complemento = f" ({descricao})" if descricao else ""
            return False, f"Agenda fechada em feriado{complemento}."

        dia_key = str(inicio_local.isoweekday())
        dia_cfg = agenda_semanal.get(dia_key) or DEFAULT_AGENDA_SEMANAL[dia_key]

        if not bool(dia_cfg.get("ativo", False)):
            nome_dia = NOMES_DIA_SEMANA.get(dia_key, "este dia")
            return False, f"Agenda fechada para {nome_dia}."

        inicio_janela = _normalizar_hora_hhmm(dia_cfg.get("inicio"), DEFAULT_AGENDA_SEMANAL[dia_key]["inicio"])
        fim_janela = _normalizar_hora_hhmm(dia_cfg.get("fim"), DEFAULT_AGENDA_SEMANAL[dia_key]["fim"])

    inicio_janela_min = _hora_em_minutos(inicio_janela)
    fim_janela_min = _hora_em_minutos(fim_janela)
    inicio_ag_min = inicio_local.hour * 60 + inicio_local.minute
    fim_ag_min = fim_local.hour * 60 + fim_local.minute

    if inicio_ag_min < inicio_janela_min or fim_ag_min > fim_janela_min:
        if excecao is not None:
            return (
                False,
                f"Horario fora da excecao desta data ({inicio_janela} as {fim_janela}).",
            )
        return (
            False,
            f"Horario fora do funcionamento da agenda ({inicio_janela} as {fim_janela}).",
        )

    return True, ""
