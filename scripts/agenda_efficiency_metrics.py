#!/usr/bin/env python3
"""Aggregate Agenda measurements. PostgreSQL snapshot is read-only; no app imports.

Run on the authorized host via stdin to avoid deploying or saving raw records.
The .env is read in memory, the database identity is checked, and only aggregate
JSON is printed. This describes the current schedule, not clinical productivity.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import unquote, urlsplit

LOCAL_TZ = timezone(timedelta(hours=-3))
RELEASE_SHA = "fa9781901ab7fa9f2939551a01d06bec6def38c4"
RELEASE_FINISHED = "2026-10-04T17:27:00+00:00"
ACTIVE_STATUSES = {"Agendado", "Confirmado", "Em atendimento", "Realizado", "Reservado"}
KNOWN_STATUSES = ACTIVE_STATUSES | {"Cancelado", "Expirado", "Faltou"}


def dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def local(value: Any) -> datetime | None:
    parsed = dt(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed.astimezone(LOCAL_TZ)


def minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


@dataclass(frozen=True)
class Event:
    # Identifiers are used only in memory for grouping; never serialized.
    start: datetime
    duration: float | None
    catalog_duration: float | None
    clinic: Any
    origin: str
    status: str
    created: datetime | None
    expires: datetime | None
    displayed_time_differs: bool

    def end(self, conservative: bool = False) -> datetime | None:
        if self.duration is None:
            return None
        duration = max(self.duration, self.catalog_duration or 0) if conservative else self.duration
        return self.start + timedelta(minutes=duration)


def normalize(row: dict[str, Any]) -> Event | None:
    start, end = local(row.get("inicio")), local(row.get("fim"))
    duration = minutes(end - start) if start and end and end > start else None
    if duration is not None and not 0 < duration <= 720:
        duration = None
    shown = None
    try:
        shown = datetime.strptime(f"{row.get('data')} {str(row.get('hora') or '')[:5]}", "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        pass
    if shown is None and start is None:
        return None
    catalog = row.get("catalogo_min")
    catalog = float(catalog) if isinstance(catalog, (int, float)) and 0 < catalog <= 720 else None
    status = row.get("status")
    return Event(
        start=shown or start, duration=duration, catalog_duration=catalog,
        clinic=row.get("clinica_id"), origin=str(row.get("origem_atendimento") or ""),
        status=status if status in KNOWN_STATUSES else "Outro",
        created=dt(row.get("created_at") or row.get("criado_em")),
        expires=local(row.get("reserva_expira_em")),
        displayed_time_differs=bool(shown and start and shown != start),
    )


def same_location(a: Event, b: Event) -> bool:
    return bool(a.clinic and a.clinic == b.clinic and a.origin != "domiciliar" and b.origin != "domiciliar")


def overlaps(events: list[Event], conservative: bool) -> set[int]:
    """Mark all members of overlapping components, including nested intervals."""
    involved: set[int] = set()
    furthest_end, furthest_index = None, None
    for index, event in enumerate(events):
        end = event.end(conservative)
        if end is None:
            continue
        if furthest_end is not None and event.start < furthest_end:
            involved.update((index, furthest_index))
        if furthest_end is None or end > furthest_end:
            furthest_end, furthest_index = end, index
    return involved


def union_minutes(events: list[Event]) -> float:
    total = 0.0
    current_start = current_end = None
    for event in events:
        end = event.end()
        if end is None:
            continue
        if current_end is not None and event.start <= current_end:
            current_end = max(current_end, end)
        else:
            if current_end is not None:
                total += minutes(current_end - current_start)
            current_start, current_end = event.start, end
    return total + (minutes(current_end - current_start) if current_end is not None else 0)


def pair_metrics(days: dict[date, list[Event]], transition: int, conservative: bool, release: datetime) -> dict[str, Any]:
    gaps: list[float] = []
    eligible_gaps: list[float] = []
    total_pairs = same_pairs = invalid_pairs = overlap_events = eligible_blocks = 0
    block_slack = 0.0
    post_created_pairs = 0
    for events in days.values():
        excluded = overlaps(events, conservative)
        overlap_events += len(excluded)
        block: list[float] = []

        def finish_block() -> None:
            nonlocal block_slack, eligible_blocks
            if block:
                eligible_blocks += 1
                # Deficits (e.g. 0-min gaps) consume apparent slack in the block.
                block_slack += max(0.0, sum(block) - transition * len(block))
                block.clear()

        for index, (a, b) in enumerate(zip(events, events[1:])):
            total_pairs += 1
            if not same_location(a, b):
                finish_block()
                continue
            same_pairs += 1
            a_end = a.end(conservative)
            if a_end is None or b.end(conservative) is None:
                invalid_pairs += 1
                finish_block()
                continue
            gap = minutes(b.start - a_end)
            gaps.append(gap)
            if (index in excluded or index + 1 in excluded or gap < 0
                    or a.origin != "clinica_parceira" or b.origin != "clinica_parceira"):
                finish_block()
                continue
            eligible_gaps.append(gap)
            if all(e.created is not None and e.created.tzinfo is not None and e.created >= release for e in (a, b)):
                post_created_pairs += 1
            block.append(gap)
        finish_block()
    nonnegative = [g for g in gaps if g >= 0]
    return {
        "consecutive_pairs": total_pairs,
        "same_clinic_pairs": same_pairs,
        "same_clinic_pairs_missing_duration": invalid_pairs,
        "same_clinic_negative_gap_pairs": sum(g < 0 for g in gaps),
        "events_in_any_overlap": overlap_events,
        "nonnegative_gap_distribution_minutes": dict(sorted(collections.Counter(str(rounded(g)) for g in nonnegative).items())),
        "positive_gap_pairs": sum(g > 0 for g in nonnegative),
        "nonnegative_gap_minutes": rounded(sum(nonnegative)),
        "fragmented_excess_above_transition_minutes": rounded(sum(max(0, g - transition) for g in nonnegative)),
        "eligible_pairs_excluding_overlap_events": len(eligible_gaps),
        "eligible_pairs_both_created_at_or_after_release": post_created_pairs,
        "eligible_gap_median_minutes": rounded(median(eligible_gaps)) if eligible_gaps else None,
        "eligible_gap_mean_minutes": rounded(sum(eligible_gaps) / len(eligible_gaps)) if eligible_gaps else None,
        "eligible_excess_mean_minutes": rounded(sum(max(0, g - transition) for g in eligible_gaps) / len(eligible_gaps)) if eligible_gaps else None,
        "eligible_blocks": eligible_blocks,
        "theoretical_slack_in_blocks_minutes": rounded(block_slack),
    }


def summarize(events: list[Event], start: date, end: date, as_of: datetime,
              release: datetime, transition: int) -> dict[str, Any]:
    """Half-open date interval, with every day in the rate denominator."""
    selected = [e for e in events if start <= e.start.date() < end]
    active = [e for e in selected if e.status in ACTIVE_STATUSES and not (
        e.status == "Reservado" and e.expires and e.expires <= as_of)]
    by_day: dict[date, list[Event]] = collections.defaultdict(list)
    for event in active:
        by_day[event.start.date()].append(event)
    # SQL uses id as stable tie-breaker; Python's sort preserves it.
    for rows in by_day.values():
        rows.sort(key=lambda e: e.start)
    days = max(0, (end - start).days)
    span = occupied = 0.0
    valid_duration_days = 0
    for rows in by_day.values():
        if any(e.end() is None for e in rows):
            continue  # Incomplete intervals cannot define a trustworthy density.
        span += minutes(max(e.end() for e in rows) - rows[0].start)
        occupied += union_minutes(rows)
        valid_duration_days += 1
    created_known = [e for e in selected if e.created is not None and e.created.tzinfo is not None]
    performed = [e for e in selected if e.status == "Realizado" and e.start < as_of]
    return {
        "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
        "calendar_days": days, "records": len(selected),
        "status_counts": dict(sorted(collections.Counter(e.status for e in selected).items())),
        "active_records_at_snapshot": len(active), "days_with_active_records": len(by_day),
        "performed_status_records_started_before_snapshot": len(performed),
        "future_records_marked_performed_excluded": sum(e.status == "Realizado" and e.start >= as_of for e in selected),
        "performed_status_per_calendar_day": rounded(len(performed) / days) if days else None,
        "active_records_per_calendar_day": rounded(len(active) / days) if days else None,
        "active_records_per_active_day": rounded(len(active) / len(by_day)) if by_day else None,
        "expired_reservations_excluded": sum(e.status == "Reservado" and bool(e.expires and e.expires <= as_of) for e in selected),
        "reserves_without_expiry": sum(e.status == "Reservado" and e.expires is None for e in selected),
        "duration_missing_active_records": sum(e.duration is None for e in active),
        "unknown_origin_active_records": sum(e.origin not in {"clinica_parceira", "domiciliar"} for e in active),
        "display_vs_timestamp_mismatch_records": sum(e.displayed_time_differs for e in selected),
        "catalog_vs_stored_duration_mismatch_active_records": sum(e.duration is not None and e.catalog_duration is not None and e.duration != e.catalog_duration for e in active),
        "stored_duration_distribution_minutes": dict(sorted(collections.Counter(str(rounded(e.duration)) for e in active if e.duration is not None).items())),
        "created_at_or_after_release_records": sum(e.created >= release for e in created_known),
        "active_records_created_at_or_after_release": sum(e.created is not None and e.created.tzinfo is not None and e.created >= release for e in active),
        "creation_timestamp_missing_or_naive_records": len(selected) - len(created_known),
        "valid_duration_days_for_density": valid_duration_days,
        "occupied_union_minutes": rounded(occupied), "first_to_last_span_minutes": rounded(span),
        "density_within_first_to_last_span_percent": rounded(100 * occupied / span) if span else None,
        "stored_duration_pairs": pair_metrics(by_day, transition, False, release),
        "conservative_current_catalog_sensitivity": pair_metrics(by_day, transition, True, release),
    }


def windows(release: datetime, weeks: int) -> tuple[date, date, date, date]:
    release_day = release.astimezone(LOCAL_TZ).date()
    release_monday = release_day - timedelta(days=release_day.weekday())
    # The entire release week is excluded. Both intervals start on Monday.
    return (release_monday - timedelta(weeks=weeks), release_monday,
            release_monday + timedelta(weeks=1), release_monday + timedelta(weeks=weeks + 1))


def make_report(rows: list[dict[str, Any]], *, as_of: datetime, release: datetime,
                weeks: int = 4, transition: int = 5, minimum_pairs: int = 20,
                baseline_start: date = date(2026, 9, 1), baseline_end: date = date(2026, 10, 1)) -> dict[str, Any]:
    normalized = [normalize(row) for row in rows]
    events = [e for e in normalized if e is not None]
    pre_start, pre_end, post_start, post_end = windows(release, weeks)
    today = as_of.astimezone(LOCAL_TZ).date()
    complete_post_weeks = min(weeks, max(0, (today - post_start).days // 7))
    observed_end = post_start + timedelta(weeks=complete_post_weeks)
    summary = lambda a, b: summarize(events, a, b, as_of, release, transition)
    pre = summary(pre_start, pre_end)
    post = summary(post_start, observed_end)
    reasons = []
    if complete_post_weeks < weeks:
        reasons.append("POST_WINDOW_INCOMPLETE")
    metric = "stored_duration_pairs"
    for name, sample in (("PRE", pre), ("POST", post)):
        if sample[metric]["eligible_pairs_excluding_overlap_events"] < minimum_pairs:
            reasons.append(name + "_TOO_FEW_ELIGIBLE_PAIRS")
    if not post["active_records_created_at_or_after_release"]:
        reasons.append("NO_POST_CREATED_ACTIVE_RECORDS_IN_COMPLETE_POST_WEEKS")
    differences = None
    defined_means = all(sample[metric]["eligible_gap_mean_minutes"] is not None for sample in (pre, post))
    if complete_post_weeks == weeks and defined_means:
        def pair_deltas(key: str) -> dict[str, Any] | None:
            if any(sample[key]["eligible_gap_mean_minutes"] is None for sample in (pre, post)):
                return None
            return {name: rounded(post[key][name] - pre[key][name]) for name in (
                "eligible_gap_mean_minutes", "eligible_excess_mean_minutes")}

        differences = {
            "performed_status_per_calendar_day": rounded(post["performed_status_per_calendar_day"] - pre["performed_status_per_calendar_day"]),
            "stored_duration_primary": pair_deltas("stored_duration_pairs"),
            "current_catalog_sensitivity": pair_deltas("conservative_current_catalog_sensitivity"),
        }
    comparison_status = "INSUFFICIENT_SAMPLE"
    if differences is not None:
        comparison_status = "DESCRIPTIVE_SMALL_SAMPLE" if any("TOO_FEW" in r for r in reasons) else "DESCRIPTIVE_COMPARISON_ONLY"
    return {
        "schema_version": 1, "release_sha": RELEASE_SHA, "release_finished_at": release.isoformat(),
        "snapshot_at": as_of.isoformat(), "timezone": "America/Fortaleza",
        "privacy": "aggregate_only_no_names_contacts_notes_or_identifiers",
        "method": {"transition_minutes": transition, "comparison_weeks": weeks,
                   "minimum_eligible_pairs_per_window": minimum_pairs,
                   "intervals": "start_inclusive_end_exclusive",
                   "post_start": post_start.isoformat(), "post_end": post_end.isoformat(),
                   "complete_post_weeks": complete_post_weeks,
                   "occupation_denominator": "first_to_last_schedule_span_not_opening_hours",
                   "duration": "persisted_interval_primary_current_catalog_only_sensitivity"},
        "unusable_start_records_excluded": sum(e is None for e in normalized),
        "reference_month": summary(baseline_start, baseline_end),
        "pre_comparison": pre, "post_complete_weeks": post,
        "post_window_current_schedule": summary(post_start, post_end),
        "comparison": {"status": comparison_status,
                       "reasons": reasons, "differences_post_minus_pre": differences,
                       "causal_gain": None, "additional_appointments_claimed": None},
        "limitations": [
            "Current mutable snapshot, not original bookings or actual clinical timestamps.",
            "Future post-window bookings may predate deployment; creation does not prove use of the new engine.",
            "No historical opening hours, staff/resources, pauses, travel, demand or preference acceptance measured.",
            "Block slack is theoretical; no rebooking, capacity, revenue or causal productivity claim.",
            "Current catalog sensitivity cannot establish historical service duration.",
        ],
    }


def database_identity_matches(url: str, expected_ref: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return parsed.scheme in {"postgres", "postgresql"} and (
        host == f"db.{expected_ref}.supabase.co" or (
            host.endswith(".pooler.supabase.com") and unquote(parsed.username or "") == f"postgres.{expected_ref}"))


def read_postgres(env_file: Path, expected_database_ref: str, start: date, end: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Only minimal columns, repeatable-read snapshot, rollback on every path."""
    from dotenv import dotenv_values
    import psycopg2
    from psycopg2.extras import RealDictCursor
    url = dotenv_values(env_file).get("DATABASE_URL", "")
    if not url or not database_identity_matches(url, expected_database_ref):
        raise ValueError("DATABASE_IDENTITY_MISMATCH")
    conn = psycopg2.connect(url, connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=15000")
    try:
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT current_setting('transaction_read_only') AS read_only, current_setting('transaction_isolation') AS isolation, transaction_timestamp() AS snapshot_at")
            snapshot = dict(cur.fetchone())
            if snapshot["read_only"] != "on":
                raise ValueError("READ_ONLY_REQUIRED")
            cur.execute("""
                SELECT a.inicio, a.fim, a.data, a.hora, a.status, a.clinica_id,
                       a.origem_atendimento, a.reserva_expira_em, a.created_at,
                       a.criado_em, s.duracao_minutos AS catalogo_min
                  FROM agendamentos a LEFT JOIN servicos s ON s.id = a.servico_id
                 WHERE (a.data >= %(start_date)s AND a.data < %(end_date)s)
                    OR (a.inicio >= %(start_time)s AND a.inicio < %(end_time)s)
                 ORDER BY a.inicio, a.id
                 LIMIT 100001
            """, {"start_date": start.isoformat(), "end_date": end.isoformat(),
                  "start_time": datetime.combine(start, time.min, LOCAL_TZ),
                  "end_time": datetime.combine(end, time.min, LOCAL_TZ)})
            rows = [dict(row) for row in cur.fetchall()]
            if len(rows) > 100000:
                raise ValueError("ROW_LIMIT_EXCEEDED")
            return rows, snapshot
    finally:
        conn.rollback()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--expected-database-ref", required=True)
    parser.add_argument("--release-finished-at", default=RELEASE_FINISHED)
    parser.add_argument("--weeks", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--transition-minutes", type=int, default=5, choices=range(0, 61))
    parser.add_argument("--minimum-pairs", type=int, default=20, choices=range(1, 1001))
    args = parser.parse_args()
    release = dt(args.release_finished_at)
    if release is None or release.tzinfo is None:
        parser.error("release-finished-at requires an explicit timezone")
    if len(args.expected_database_ref) < 8:
        parser.error("expected-database-ref is required and must be specific")
    pre_start, _, _, post_end = windows(release, args.weeks)
    try:
        rows, snapshot = read_postgres(args.env_file, args.expected_database_ref, min(date(2026, 9, 1), pre_start), post_end)
        report = make_report(rows, as_of=snapshot.pop("snapshot_at"), release=release,
                             weeks=args.weeks, transition=args.transition_minutes,
                             minimum_pairs=args.minimum_pairs)
        report["database_transaction"] = snapshot
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0  # Insufficient sample is a valid measurement, not a failed collection.
    except Exception as error:
        # SQL/connection exceptions may contain credentials or raw fields.
        print(json.dumps({"status": "COLLECTION_FAILED", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
