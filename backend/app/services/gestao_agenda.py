"""Indicadores administrativos da Agenda, sem corrigir ou expirar registros.

A capacidade pertence à agenda única da Fort Cordis, não a cada parceiro. As
janelas livres são tempo de calendário, e não ofertas confirmadas de rota.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, inspect, or_
from sqlalchemy.orm import Session

from app.core.agenda_config import (
    carregar_agenda_excecoes,
    carregar_agenda_feriados,
    carregar_agenda_semanal,
    obter_excecao_data,
    obter_feriado,
)
from app.models.agenda_bloqueio import AgendaBloqueio
from app.models.agendamento import Agendamento
from app.models.auditoria_evento import AuditoriaEvento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao

LOCAL_TZ = timezone(timedelta(hours=-3))
OCCUPIED_STATUSES = {"Agendado", "Reservado", "Confirmado", "Em atendimento", "Realizado"}
KNOWN_STATUSES = OCCUPIED_STATUSES | {"Cancelado", "Expirado", "Faltou"}
Interval = tuple[datetime, datetime]


def _local(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    # A Agenda interpreta os timestamps legados sem fuso como horário local.
    return value.astimezone(LOCAL_TZ).replace(tzinfo=None) if value.tzinfo else value


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _interval(row: Any) -> tuple[datetime | None, datetime | None]:
    """Mesmo horário legado da Agenda, sem inventar duração quando falta fim."""
    start, end = _local(row.inicio), _local(row.fim)
    duration = end - start if start and end and end > start else None
    day = _date(row.data)
    try:
        clock = time.fromisoformat(str(row.hora or "").strip()[:5])
    except ValueError:
        clock = None
    if day and clock:
        start = datetime.combine(day, clock)
        end = start + duration if duration else None
    elif not duration:
        end = None
    return start, end


def _merge(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted((a, b) for a, b in intervals if b > a):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(windows: list[Interval], occupied: list[Interval]) -> list[Interval]:
    remaining = _merge(windows)
    for cut_start, cut_end in _merge(occupied):
        next_windows = []
        for start, end in remaining:
            if cut_end <= start or cut_start >= end:
                next_windows.append((start, end))
            else:
                if start < cut_start:
                    next_windows.append((start, cut_start))
                if cut_end < end:
                    next_windows.append((cut_end, end))
        remaining = next_windows
    return remaining


def _intersect(intervals: list[Interval], windows: list[Interval]) -> list[Interval]:
    return _merge([
        (max(start, window_start), min(end, window_end))
        for start, end in intervals
        for window_start, window_end in windows
        if start < window_end and end > window_start
    ])


def _minutes(intervals: list[Interval]) -> float:
    return round(sum((end - start).total_seconds() / 60 for start, end in _merge(intervals)), 2)


def _percent(numerator: float, denominator: float) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def _day_window(day: date, weekly: dict, holidays: list, exceptions: list) -> tuple[list[Interval], str | None]:
    exception = obter_excecao_data(day, exceptions)
    if exception is not None:
        if not exception["ativo"]:
            return [], "Fechada por exceção de data"
        config = exception
    else:
        if obter_feriado(day, holidays):
            return [], "Feriado cadastrado"
        config = weekly[str(day.isoweekday())]
        if not config["ativo"]:
            return [], "Dia sem expediente"
    return [(
        datetime.combine(day, time.fromisoformat(config["inicio"])),
        datetime.combine(day, time.fromisoformat(config["fim"])),
    )], None


def _history_flags(db: Session, ids: list[int], available: bool) -> tuple[set[int], set[int], set[int]]:
    """Extrai apenas transições estruturadas; nunca devolve o texto de auditoria."""
    reactivated, rescheduled, reinstated = set(), set(), set()
    if not available:
        return reactivated, rescheduled, reinstated
    for offset in range(0, len(ids), 500):
        events = db.query(AuditoriaEvento.entidade_id, AuditoriaEvento.detalhes_json).filter(
            AuditoriaEvento.modulo == "agenda",
            AuditoriaEvento.entidade == "agendamento",
            AuditoriaEvento.entidade_id.in_([str(i) for i in ids[offset:offset + 500]]),
            AuditoriaEvento.acao.in_([
                "AGENDAMENTO_ATUALIZADO", "AGENDAMENTO_STATUS_ALTERADO", "AGENDAMENTO_RESERVA_REABILITADA",
            ]),
        ).all()
        for event in events:
            try:
                details = json.loads(event.detalhes_json or "{}")
                if not isinstance(details, dict):
                    continue
                before = details.get("antes") if isinstance(details.get("antes"), dict) else {}
                after = details.get("depois") if isinstance(details.get("depois"), dict) else {}
                old_status = details.get("status_anterior", before.get("status"))
                new_status = details.get("status_novo", after.get("status"))
                identifier = int(event.entidade_id)
            except (ValueError, TypeError):
                continue
            if old_status == "Cancelado" and new_status in KNOWN_STATUSES - {"Cancelado"}:
                reactivated.add(identifier)
            if old_status == "Expirado" and new_status in OCCUPIED_STATUSES:
                reinstated.add(identifier)
            old_start, new_start = _local(before.get("inicio")), _local(after.get("inicio"))
            if old_start and new_start and old_start != new_start:
                rescheduled.add(identifier)
    return reactivated, rescheduled, reinstated


def _group_cancel(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row[field] for field in fields)].append(row)
    result = []
    for key, group in buckets.items():
        cancelled = sum(row["status"] == "Cancelado" for row in group)
        result.append({
            **dict(zip(fields, key)),
            "total_agendamentos": len(group),
            "total_cancelados": cancelled,
            "taxa_pct": _percent(cancelled, len(group)),
        })
    return sorted(result, key=lambda item: (-item["total_cancelados"], str(item[fields[-1]])))


def build_agenda_metrics(
    db: Session,
    start: date,
    end: date,
    clinic_id: int | None,
    region: str | None,
    today: date,
) -> dict:
    """Consulta apenas; filtros nunca multiplicam ou liberam a capacidade global.

    ``today`` é a data local da consulta. Quando é substituída por uma data
    sintética, reservas são avaliadas à meia-noite dessa data.
    """
    if end < start:
        raise ValueError("A data final deve ser igual ou posterior à data inicial.")
    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    if now.date() != today:
        now = datetime.combine(today, time.min)
    # Inspeciona a conexão já retida pela sessão, sem disputar outra do pool.
    tables = set(inspect(db.connection()).get_table_names())
    config = db.query(
        Configuracao.agenda_semanal, Configuracao.agenda_feriados, Configuracao.agenda_excecoes,
    ).first()
    weekly = carregar_agenda_semanal(config.agenda_semanal if config else None)
    holidays = carregar_agenda_feriados(config.agenda_feriados if config else None)
    exceptions = carregar_agenda_excecoes(config.agenda_excecoes if config else None)
    clinics = {row.id: row for row in db.query(
        Clinica.id, Clinica.nome, Clinica.regiao_operacional, Clinica.cidade, Clinica.ativo,
    ).all()}

    # Buffer protege conversões UTC/local e o legado data/hora. A seleção
    # definitiva é feita pelo horário normalizado, como na própria Agenda.
    period_start = datetime.combine(start, time.min)
    period_end = datetime.combine(end + timedelta(days=1), time.min) if end < date.max else datetime.max
    raw_start = period_start - timedelta(days=1) if start > date.min else datetime.min
    raw_end = period_end + timedelta(days=1) if end < date.max - timedelta(days=1) else datetime.max
    candidates = db.query(
        Agendamento.id, Agendamento.inicio, Agendamento.fim, Agendamento.data,
        Agendamento.hora, Agendamento.status, Agendamento.reserva_expira_em, Agendamento.clinica_id,
    ).filter(or_(
        and_(Agendamento.data >= start.isoformat(), Agendamento.data <= end.isoformat()),
        and_(Agendamento.inicio >= raw_start, Agendamento.inicio < raw_end),
        and_(Agendamento.inicio < raw_end, Agendamento.fim > raw_start),
    )).all()
    all_rows = []
    for row in candidates:
        begin, finish = _interval(row)
        day = begin.date() if begin else _date(row.data)
        in_population = day is not None and start <= day <= end
        overlaps_period = bool(begin and finish and begin < period_end and finish > period_start)
        if day is None or not (in_population or overlaps_period):
            continue
        clinic = clinics.get(row.clinica_id)
        clinic_name = clinic.nome if clinic else (
            f"Clínica {row.clinica_id} (cadastro ausente)" if row.clinica_id else "Não vinculada"
        )
        region_name = (str(clinic.regiao_operacional or "").strip() or str(clinic.cidade or "").strip()) if clinic else ""
        status = str(row.status or "").strip() or "Não informado"
        expiry = _local(row.reserva_expira_em)
        if status == "Reservado" and expiry and expiry <= now:
            status = "Expirado"
        all_rows.append({
            "agendamento_id": row.id, "data": day.isoformat(), "inicio": begin,
            "fim": finish, "status": status, "clinica_id": row.clinica_id,
            "clinica_nome": clinic_name, "clinica_ativa": bool(clinic.ativo) if clinic else None,
            "regiao": region_name or "Não informada",
            "duracao_minutos": _minutes([(begin, finish)]) if begin and finish else None,
            "incluido_populacao_cancelamentos": in_population,
        })
    all_rows.sort(key=lambda item: (item["data"], item["inicio"] or datetime.min, item["agendamento_id"]))
    selected = [row for row in all_rows if (
        (clinic_id is None or row["clinica_id"] == clinic_id)
        and (not region or row["regiao"].casefold() == region.strip().casefold())
    )]
    selected_ids = {row["agendamento_id"] for row in selected}
    population = [row for row in selected if row["incluido_populacao_cancelamentos"]]

    blocks = []
    if "agenda_bloqueios" in tables:
        for row in db.query(AgendaBloqueio.inicio, AgendaBloqueio.fim).filter(
            AgendaBloqueio.ativo.is_(True), AgendaBloqueio.inicio < raw_end, AgendaBloqueio.fim > raw_start,
        ).all():
            begin, finish = _local(row.inicio), _local(row.fim)
            if begin and finish and finish > begin:
                blocks.append((begin, finish))

    days, capacity_windows = [], []
    invalid_count = 0
    unknown_status_ids = set()
    outside_minutes = 0.0
    current = start
    while current <= end:
        windows, closed_reason = _day_window(current, weekly, holidays, exceptions)
        available = _subtract(windows, blocks)
        capacity_windows.extend(available)
        day_start = datetime.combine(current, time.min)
        day_end = datetime.combine(current + timedelta(days=1), time.min) if current < date.max else datetime.max
        day_rows = [row for row in all_rows if (
            row["data"] == current.isoformat() or (
                row["inicio"] and row["fim"] and row["inicio"] < day_end and row["fim"] > day_start
            )
        )]
        selected_day = [row for row in day_rows if row["agendamento_id"] in selected_ids]
        active = [row for row in day_rows if row["status"] in OCCUPIED_STATUSES]
        invalid = sum(not row["inicio"] or not row["fim"] for row in active)
        unknown = sum(row["status"] not in KNOWN_STATUSES for row in day_rows)
        invalid_count += invalid
        unknown_status_ids.update(row["agendamento_id"] for row in day_rows if row["status"] not in KNOWN_STATUSES)
        full_intervals = _intersect(
            [(row["inicio"], row["fim"]) for row in active if row["inicio"] and row["fim"]],
            [(day_start, day_end)],
        )
        occupied = _intersect(full_intervals, available)
        selected_intervals = [
            (row["inicio"], row["fim"]) for row in selected_day
            if row["status"] in OCCUPIED_STATUSES and row["inicio"] and row["fim"]
        ]
        realized_intervals = [
            (row["inicio"], row["fim"]) for row in selected_day
            if row["status"] == "Realizado" and row["inicio"] and row["fim"]
        ]
        # Não disfarçar atendimentos administrativos fora do expediente como
        # capacidade ampliada. Ficam no detalhe e na lacuna de reconciliação.
        outside_minutes += _minutes(full_intervals) - _minutes(occupied)
        free = _subtract(available, occupied)
        incomplete = bool(invalid or unknown or "agenda_bloqueios" not in tables)
        days.append({
            "data": current.isoformat(), "capacidade_minutos": _minutes(available),
            "bloqueados_minutos": _minutes(windows) - _minutes(available),
            "agendados_minutos": _minutes(_intersect(selected_intervals, available)),
            "agendados_totais_minutos": _minutes(occupied),
            "realizados_minutos": _minutes(_intersect(realized_intervals, available)),
            "livres_minutos": None if incomplete else _minutes(free),
            "janelas_livres": [] if incomplete else [
                {"inicio": a.strftime("%H:%M"), "fim": b.strftime("%H:%M")} for a, b in free
            ],
            "regioes_presentes": sorted({row["regiao"] for row in active}),
            "motivo_fechado": closed_reason,
            "agendamentos_sem_duracao": invalid,
        })
        if current == end:
            break
        current += timedelta(days=1)

    gaps = []
    if invalid_count:
        gaps.append(f"{invalid_count} agendamento(s) ocupado(s) sem duração válida; minutos conhecidos são parciais e livre/taxas não são calculados.")
    if unknown_status_ids:
        gaps.append(f"{len(unknown_status_ids)} registro(s) com estado não reconhecido; não foi inferida ocupação nem cancelamento.")
    if "agenda_bloqueios" not in tables:
        gaps.append("Fonte de bloqueios indisponível; capacidade bruta é parcial e livre/taxas não são calculados.")
    if outside_minutes > 0:
        gaps.append(f"{round(outside_minutes, 2)} minuto(s) de agendamentos fora da capacidade vigente (fechamento ou bloqueio); consulte os registros.")
    capacity = round(sum(day["capacidade_minutos"] for day in days), 2)
    scheduled = round(sum(day["agendados_minutos"] for day in days), 2)
    realized = round(sum(day["realizados_minutos"] for day in days), 2)
    incomplete = bool(invalid_count or unknown_status_ids or "agenda_bloqueios" not in tables)
    by_region = []
    for name in sorted({row["regiao"] for row in selected}):
        intervals = [(row["inicio"], row["fim"]) for row in selected if (
            row["regiao"] == name and row["status"] in OCCUPIED_STATUSES and row["inicio"] and row["fim"]
        )]
        realized_intervals = [(row["inicio"], row["fim"]) for row in selected if (
            row["regiao"] == name and row["status"] == "Realizado" and row["inicio"] and row["fim"]
        )]
        by_region.append({
            "regiao": name, "agendados_minutos": _minutes(_intersect(intervals, capacity_windows)),
            "realizados_minutos": _minutes(_intersect(realized_intervals, capacity_windows)),
        })

    reactivated, rescheduled, reinstated = _history_flags(
        db, sorted(row["agendamento_id"] for row in population), "auditoria_eventos" in tables,
    )
    cancelled = sum(row["status"] == "Cancelado" for row in population)
    # Flags históricos não se tornam um segundo agendamento. Uma reativação
    # seguida de novo cancelamento permanece cancelada na população atual.
    currently_active_ids = {row["agendamento_id"] for row in population if row["status"] in OCCUPIED_STATUSES}
    records = [{
        **row,
        "inicio": row["inicio"].isoformat() if row["inicio"] else None,
        "fim": row["fim"].isoformat() if row["fim"] else None,
        "reativado_identificado": row["agendamento_id"] in reactivated,
        "reagendado_identificado": row["agendamento_id"] in rescheduled,
    } for row in selected]
    cancellation_gaps = [
        "Motivos de cancelamento não possuem campo estruturado nesta fonte; observações e texto livre de auditoria não são classificados.",
        "Exclusões físicas e agendamentos movidos para fora do período não compõem esta população de registros atuais.",
        "Reativações e mudanças de horário identificadas são evidências da auditoria estruturada; não são um histórico completo. Reagendado exige mudança registrada em início, sem inferência de texto livre ou de dados legados não auditados.",
    ]
    if "auditoria_eventos" not in tables:
        cancellation_gaps.append("Histórico de auditoria indisponível; reativações e mudanças de horário não puderam ser identificadas.")

    return {
        "ocupacao": {
            "capacidade_minutos": capacity,
            "agendados_minutos": scheduled,
            "agendados_totais_minutos": round(sum(day["agendados_totais_minutos"] for day in days), 2),
            "realizados_minutos": realized,
            "livres_minutos": None if incomplete else round(sum(day["livres_minutos"] for day in days), 2),
            "taxa_agendada_pct": None if incomplete else _percent(scheduled, capacity),
            "taxa_realizada_pct": None if incomplete else _percent(realized, capacity),
            "base": "Agenda atual, por interseção dos intervalos com cada data local do período. Agendado inclui Reservado não vencido, Agendado, Confirmado, Em atendimento e Realizado. Realizado usa a duração reservada dos registros nesse estado, sem medir tempo real de trabalho.",
            "formula": "Ocupação do recorte = união dos intervalos do recorte dentro da jornada disponível ÷ capacidade global × 100. Capacidade = jornada semanal/exceção, menos feriados e união dos bloqueios ativos. Livre = capacidade menos toda a agenda, inclusive parceiros fora do filtro.",
            "parcial": bool(gaps), "lacunas": gaps, "dias": days, "por_regiao": by_region,
            "registros": records,
            "limites": [
                "Capacidade e tempo livre pertencem à rede inteira; não são somados por clínica ou atribuídos a uma região. Com filtro, a taxa mede a parcela da capacidade global ocupada pelo recorte.",
                "Janelas livres são tempo de calendário. Deslocamentos, primeira saída, margens e viabilidade entre regiões precisam ser validados na Agenda antes de marcar; não são vagas garantidas.",
                "Jornada, feriados, exceções e bloqueios refletem a configuração atual, sem reconstrução histórica. Ausências só são descontadas quando cadastradas como bloqueio ativo ou fechamento.",
                "Intervalos sobrepostos são unidos. Totais por região podem se sobrepor e não devem ser somados para reconstruir a ocupação global.",
            ],
        },
        "cancelamentos": {
            "total_agendamentos": len(population), "total_cancelados": cancelled,
            "taxa_pct": _percent(cancelled, len(population)),
            "por_status": [{"status": status, "quantidade": count} for status, count in sorted(Counter(row["status"] for row in population).items())],
            "por_clinica": _group_cancel(population, ("clinica_id", "clinica_nome")),
            "por_regiao": _group_cancel(population, ("regiao",)),
            "motivos": [],
            "reativados_identificados": len(reactivated & currently_active_ids),
            "reagendados_identificados": len(rescheduled),
            "reservas_reabilitadas_identificadas": len(reinstated & currently_active_ids),
            "base": "Registros únicos pela data local atual do agendamento no período, no estado efetivo atual da consulta. Inclui reservas expiradas e Faltou no denominador, apresentados separadamente. Não é uma contagem de eventos por data de cancelamento.",
            "formula": "Registros atualmente Cancelado ÷ todos os registros únicos do recorte × 100. Expirado, Faltou, alteração de horário e reativação não são cancelamentos.",
            "parcial": True, "lacunas": cancellation_gaps,
        },
    }
