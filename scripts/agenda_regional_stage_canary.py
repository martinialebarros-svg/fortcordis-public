#!/usr/bin/env python3
"""Replay Friday's minimal Agenda scenario in a disposable stage schema.

The installed CLI refuses any checkout, database project or Git snapshot other
than the explicitly supplied stage target. Fixture names, route durations and
aggregate history are operational examples; no patient/contact data is copied.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


def run_checks(engine) -> dict:
    """Run installed Agenda source against an already isolated test engine."""
    if engine.dialect.name == "postgresql":
        schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
        if not isinstance(schema, str) or not re.fullmatch(r"agenda_regional_canary_[a-f0-9]{32}", schema):
            raise RuntimeError("Regional replay requires its own disposable schema")
    elif engine.dialect.name != "sqlite":
        raise RuntimeError("Regional replay database dialect is not allowed")
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.api.v1.endpoints import agenda
    from app.models.agendamento import Agendamento
    from app.models.agenda_bloqueio import AgendaBloqueio
    from app.models.clinica import Clinica
    from app.models.clinica_deslocamento import ClinicaDeslocamento
    from app.models.configuracao import Configuracao
    from app.models.google_maps_cost_control import COST_TABLES
    from app.models.paciente import Paciente
    from app.models.servico import Servico
    from app.models.tutor import Tutor
    from app.services import geocoding_service, logistica_service, google_maps_cost_control

    for model in (Agendamento, AgendaBloqueio, Clinica, ClinicaDeslocamento,
                  Configuracao, Paciente, Servico, Tutor):
        model.__table__.create(engine)
    for table in COST_TABLES:
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    actor = SimpleNamespace(id=1, nome="Stage QA", tem_papel=lambda _: True)
    checks: dict[str, bool] = {}
    local = agenda.LOCAL_TZ
    friday = "2026-10-23"
    fixed_now = datetime(2026, 10, 22, 12, tzinfo=local)

    class FrozenMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class FrozenDateTime(datetime, metaclass=FrozenMeta):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz is not None else fixed_now.replace(tzinfo=None)

    names = ("Zoomare", "Celeiro", "Uninassau", "Animal Care", "Vet World",
             "Pet Sus", "Boundary 50", "Boundary 51", "Volume fixture")
    rules = {
        "base": {"address": "Base sintética Fortaleza", "lat": -3.7, "lng": -38.5},
        "thresholds": {"max_neighbor_travel_min": 30, "safe_margin_min": 5,
                       "same_location_transition_min": 5, "max_insertion_detour_min": 25},
        "route_policy": {
            "regional_transition_enabled": False,
            "regional_transition_max_travel_min": 50,
            "regional_transition_margin_min": 15,
            "regional_transition_max_legs_per_day": 1,
            "recurrent_clinic_history_days": 60,
            "reject_clear_inefficiency": True,
            "prefer_near_base_at_end_of_route": False,
            "first_appointment_city_floors": {},
        },
    }
    with sessions() as db:
        cfg = Configuracao(agenda_semanal=json.dumps({str(day): {
            "ativo": day == 5, "inicio": "08:00", "fim": "16:30"}
            for day in range(1, 8)}), agenda_feriados="[]", agenda_excecoes="[]",
            agenda_rota_regras=json.dumps(rules))
        clinics = {name: Clinica(nome=name, ativo=True, latitude=-3.7 - i / 100,
                   longitude=-38.5 - i / 100, place_id=f"stage-regional-{i}",
                   cidade="Eusebio" if name in names[:2] else "Fortaleza", estado="CE")
                   for i, name in enumerate(names)}
        db.add_all([cfg, *clinics.values()])
        db.flush()
        ids = {name: row.id for name, row in clinics.items()}

        def appointment(name, time, status="Agendado", day=friday):
            start = datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=local)
            return Agendamento(clinica_id=ids[name], inicio=start,
                fim=start + timedelta(minutes=30), data=day, hora=time,
                status=status, origem_atendimento="clinica_parceira")

        zoomare = appointment("Zoomare", "09:00")
        db.add_all([zoomare, appointment("Celeiro", "09:45", "Cancelado")])
        # Minimal aggregate history reproduced synthetically, without PII.
        for name, total, days in (("Vet World", 36, 19), ("Animal Care", 22, 12),
                                  ("Uninassau", 14, 8), ("Volume fixture", 40, 2)):
            for i in range(total):
                day = (datetime(2026, 10, 21) - timedelta(days=i % days)).date().isoformat()
                db.add(appointment(name, f"{8 + (i // days) % 8:02}:00", "Realizado", day))
        # Outside the complete sixty-day window, today and non-realized rows
        # cannot inflate recurrence used to prioritize the opportunities.
        for day, status in (("2026-08-22", "Realizado"), ("2026-10-22", "Realizado"),
                            ("2026-10-20", "Cancelado"), ("2026-10-19", "Agendado")):
            db.add(appointment("Volume fixture", "15:00", status, day))
        for name, duration in (("Celeiro", 10), ("Uninassau", 33), ("Animal Care", 41),
                               ("Vet World", 42), ("Pet Sus", 54), ("Boundary 50", 50),
                               ("Boundary 51", 51), ("Volume fixture", 42)):
            for origin, destination in (("Zoomare", name), (name, "Zoomare")):
                db.add(ClinicaDeslocamento(origem_clinica_id=ids[origin],
                    destino_clinica_id=ids[destination], perfil="comercial", distancia_km=10,
                    duracao_min=duration, fonte="manual", manual_override=True))
        for origin, destination, duration in (("Uninassau", "Animal Care", 14),
                                              ("Uninassau", "Vet World", 38),
                                              ("Animal Care", "Vet World", 20)):
            for a, b in ((origin, destination), (destination, origin)):
                db.add(ClinicaDeslocamento(origem_clinica_id=ids[a],
                    destino_clinica_id=ids[b], perfil="comercial", distancia_km=10,
                    duracao_min=duration, fonte="manual", manual_override=True))
        db.commit()
        zoomare_id = zoomare.id

    forbidden = AssertionError("External network forbidden in regional stage canary")
    with ExitStack() as stack:
        # Cost policy reads must use the same disposable database too.
        stack.enter_context(patch.object(google_maps_cost_control.database, "engine", engine))
        stack.enter_context(patch.object(agenda, "datetime", FrozenDateTime))
        for module, name in ((logistica_service, "urlopen"), (logistica_service, "_http_get_json"),
                             (logistica_service, "_http_post_json"), (geocoding_service, "urlopen"),
                             (agenda, "geocodificar_endereco_google")):
            stack.enter_context(patch.object(module, name, side_effect=forbidden))
        # First departure has its own independent rule; its synthetic 50 min
        # is never inserted in the list of appointment-to-appointment legs.
        departure = stack.enter_context(patch.object(agenda, "_obter_deslocamento_primeira_saida",
                                           return_value=(50, "google_routes_api_cache")))

        def suggestions(db, name):
            return agenda.sugerir_horarios_agenda(agenda.SugestaoHorarioPayload(
                data=friday, clinica_id=ids[name], duracao_minutos=30,
                intervalo_minutos=5, limite=50, preferencia={"hora_inicio": "09:30"}),
                db=db, current_user=actor)

        def validate(db, name, time):
            return agenda.validar_oferta_assistente_agenda(agenda.ValidarOfertaAssistentePayload(
                inicio=f"{friday} {time}", clinica_id=ids[name], duracao_minutos=30),
                db=db, current_user=actor)

        def assert_writer(db, name, time, expected):
            candidate = appointment(name, time)
            try:
                agenda._validar_deslocamento_agendamento(db, candidate)
                passed = True
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                passed = False
            assert passed == expected, f"Writer route validation: {name} {time}"

        with sessions() as db:
            assert not suggestions(db, "Uninassau")["items"]
            checks["flag_off_preserves_normal_30_min_limit"] = True
            cfg = db.query(Configuracao).one()
            rules["route_policy"]["regional_transition_enabled"] = True
            cfg.agenda_rota_regras = json.dumps(rules)
            db.commit()
            active = agenda._listar_agendamentos_ativos_do_dia(db, friday)
            assert len(active) == 1 and active[0]["clinica_id"] == ids["Zoomare"]
            checks["cancelled_celeiro_is_not_a_neighbour_or_a_quota_leg"] = True

            summary = {}
            for name in ("Uninassau", "Animal Care", "Vet World", "Pet Sus", "Boundary 50", "Boundary 51"):
                response = suggestions(db, name)
                starts = sorted(item["inicio"] for item in response["items"])
                summary[name] = {"slots": response["total_encontrados"],
                                 "earliest_offered": starts[0] if starts else None}
            assert summary["Uninassau"]["slots"] > 0
            assert summary["Animal Care"]["slots"] > 0
            assert summary["Vet World"]["slots"] > 0
            assert summary["Pet Sus"]["slots"] == 0
            assert summary["Boundary 51"]["slots"] == 0
            assert summary["Boundary 50"]["earliest_offered"] == f"{friday} 10:35"
            checks["friday_opens_other_clinics_but_refuses_51_and_54_minutes"] = True
            assert validate(db, "Boundary 50", "10:35")["valido"]
            assert not validate(db, "Boundary 50", "10:30")["valido"]
            assert not validate(db, "Boundary 51", "12:00")["valido"]
            assert_writer(db, "Boundary 50", "10:35", True)
            assert_writer(db, "Boundary 50", "10:30", False)
            assert_writer(db, "Boundary 51", "12:00", False)
            checks["offer_and_writer_enforce_50_minutes_plus_15_total_margin"] = True

            agenda._validar_deslocamento_agendamento(db, db.get(Agendamento, zoomare_id),
                                                    agendamento_id_excluir=zoomare_id)
            assert departure.called
            assert_writer(db, "Uninassau", "10:30", True)
            checks["first_departure_has_separate_validation_and_does_not_consume_quota"] = True

            db.add(appointment("Uninassau", "10:30"))
            db.commit()
            assert not validate(db, "Vet World", "12:00")["valido"]
            assert_writer(db, "Vet World", "12:00", False)
            assert validate(db, "Animal Care", "12:00")["valido"]
            assert_writer(db, "Animal Care", "12:00", True)
            checks["second_long_leg_refused_but_existing_block_can_be_filled"] = True
            db.query(Agendamento).filter(Agendamento.data == friday,
                                        Agendamento.clinica_id == ids["Uninassau"]).delete()
            db.commit()

            from app.services import agenda_day_opportunities
            with (patch.object(agenda_day_opportunities, "datetime", FrozenDateTime),
                  patch.object(agenda, "_avaliar_primeira_saida", side_effect=forbidden)):
                opportunities = agenda.listar_oportunidades_dia(agenda.OportunidadesDiaPayload(
                    data=friday, limite=20), db=db, current_user=actor)
            recurrent = [item for item in opportunities["items"]
                         if item.get("clinica_id") in {ids["Vet World"], ids["Animal Care"],
                                                      ids["Uninassau"], ids["Volume fixture"]}]
            ordered_ids = [item["clinica_id"] for item in recurrent]
            assert ids["Vet World"] in ordered_ids and ids["Volume fixture"] in ordered_ids
            assert ordered_ids[0] == ids["Uninassau"]  # Lower travel band remains primary.
            assert ordered_ids.index(ids["Vet World"]) < ordered_ids.index(ids["Animal Care"])
            assert ordered_ids.index(ids["Vet World"]) < ordered_ids.index(ids["Volume fixture"])
            by_id = {item["clinica_id"]: item for item in recurrent}
            assert opportunities["historico"] == {"inicio": "2026-08-23", "fim": "2026-10-21", "dias": 60}
            for name, total, days in (("Vet World", 36, 19), ("Animal Care", 22, 12),
                                      ("Uninassau", 14, 8), ("Volume fixture", 40, 2)):
                assert by_id[ids[name]]["dias_realizados_60d"] == days
                assert by_id[ids[name]]["atendimentos_realizados_60d"] == total
            for name, duration in (("Uninassau", 33), ("Animal Care", 41), ("Vet World", 42)):
                assert by_id[ids[name]]["tempo_deslocamento_total_min"] == duration
            checks["recurrence_uses_distinct_realized_days_before_volume"] = True

            # A legacy appointment crossing midnight must never turn its end
            # into only HH:MM and accidentally initiate a base lookup. Verify
            # the authenticated HTTP route against the same isolated schema.
            row = db.get(Agendamento, zoomare_id)
            row.inicio = datetime(2026, 10, 23, 23, 30, tzinfo=local)
            row.fim = datetime(2026, 10, 24, 0, 0, tzinfo=local)
            row.hora = "23:30"
            db.commit()
            app = FastAPI()
            app.include_router(agenda.router, prefix="/api/v1/agenda")

            def isolated_request_db():
                with sessions() as request_db:
                    yield request_db

            app.dependency_overrides[agenda.get_db] = isolated_request_db
            app.dependency_overrides[agenda.get_current_user] = lambda: actor
            with (patch.object(agenda_day_opportunities, "datetime", FrozenDateTime),
                  patch.object(agenda, "_avaliar_primeira_saida", side_effect=forbidden),
                  TestClient(app) as client):
                response = client.post("/api/v1/agenda/oportunidades-dia", json={"data": friday})
            assert response.status_code == 200
            overnight = response.json()
            assert overnight["items"] == [] and overnight["consultas_google"] == 0
            assert "termina fora desta data" in overnight["motivo"]
            checks["overnight_anchor_returns_no_http_offers_without_base_or_google"] = True

            # Missing one direction must discard only the affected candidates.
            # A09 -> B13 is already committed in this synthetic schema. C -> B
            # is absent, while B -> C40 permits C after B with its full margin.
            row.inicio = datetime(2026, 10, 23, 9, 0, tzinfo=local)
            row.fim = datetime(2026, 10, 23, 9, 30, tzinfo=local)
            row.hora = "09:00"
            later = db.query(Agendamento).filter(
                Agendamento.data == friday, Agendamento.clinica_id == ids["Celeiro"],
            ).one()
            later.inicio = datetime(2026, 10, 23, 13, 0, tzinfo=local)
            later.fim = datetime(2026, 10, 23, 13, 30, tzinfo=local)
            later.hora = "13:00"
            later.status = "Agendado"
            db.query(ClinicaDeslocamento).filter(
                ClinicaDeslocamento.origem_clinica_id == ids["Uninassau"],
                ClinicaDeslocamento.destino_clinica_id == ids["Celeiro"],
                ClinicaDeslocamento.perfil == "comercial",
            ).delete()
            directed = ClinicaDeslocamento(origem_clinica_id=ids["Celeiro"],
                destino_clinica_id=ids["Uninassau"], perfil="comercial", distancia_km=10,
                duracao_min=40, fonte="manual", manual_override=True)
            db.add(directed)
            db.commit()

            def cached_opportunities():
                with (patch.object(agenda_day_opportunities, "datetime", FrozenDateTime),
                      patch.object(agenda, "_avaliar_primeira_saida", side_effect=forbidden)):
                    response = agenda.listar_oportunidades_dia(agenda.OportunidadesDiaPayload(
                        data=friday, limite=20), db=db, current_user=actor)
                assert response["consultas_google"] == 0
                return {item["clinica_id"]: item for item in response["items"]}

            directed_items = cached_opportunities()
            assert ids["Uninassau"] in directed_items, "A missing C-to-B route must not discard C's later slots"
            assert directed_items[ids["Uninassau"]]["inicio"] == f"{friday} 14:30"
            assert directed_items[ids["Uninassau"]]["tempo_deslocamento_total_min"] == 40
            checks["missing_directed_route_preserves_clinic_and_later_1430_slot"] = True

            # An unknown fixed A -> B baseline may not authorize an additional
            # long leg; known normal legs can still complete that existing day.
            db.query(ClinicaDeslocamento).filter(
                ClinicaDeslocamento.origem_clinica_id == ids["Zoomare"],
                ClinicaDeslocamento.destino_clinica_id == ids["Celeiro"],
                ClinicaDeslocamento.perfil == "comercial",
            ).delete()
            directed.duracao_min = 20
            db.commit()
            normal_items = cached_opportunities()
            assert ids["Uninassau"] in normal_items
            assert normal_items[ids["Uninassau"]]["inicio"] == f"{friday} 14:00"
            assert normal_items[ids["Uninassau"]]["tempo_deslocamento_total_min"] == 20
            directed.duracao_min = 40
            db.commit()
            assert ids["Uninassau"] not in cached_opportunities()
            checks["unknown_fixed_baseline_allows_normal_leg_but_not_new_long_leg"] = True
            db.rollback()

    return {"checks": checks, "passed": all(checks.values()),
            "fixture_date": friday, "clock_reference_local": fixed_now.isoformat(),
            "fixture_operating_hours": {"inicio": "08:00", "fim": "16:30"},
            "history_window": opportunities["historico"],
            "recurrence_priority": [{key: item[key] for key in (
                "clinica", "dias_realizados_60d", "atendimentos_realizados_60d",
                "tempo_deslocamento_total_min", "inicio")} for item in recurrent],
            "friday_clinics": summary, "real_google_calls": 0,
            "copied_patient_or_contact_records": 0, "existing_operational_records_modified": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if root != Path("/var/www/fortcordis-stage") or not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
        raise RuntimeError("Only exact stage checkout and explicit SHA are allowed")
    installed = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if installed != args.expected_sha:
        raise RuntimeError("Unexpected stage Git snapshot")
    backend = root / "backend"
    os.chdir(backend)
    sys.path[:0] = [str(backend), str(root / "scripts")]
    from app.core.config import settings
    from fiscal_rotina_stage_canary import _validar_destino
    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.pool import NullPool
    admin = create_engine(settings.DATABASE_URL, poolclass=NullPool)
    schema = "agenda_regional_canary_" + uuid4().hex
    engine = None
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0,
            pool_pre_ping=True, execution_options={"schema_translate_map": {None: schema}})

        @event.listens_for(engine, "begin")
        def isolate_transaction(conn):
            # Do not include public in search_path, even for raw SQL or introspection.
            conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')

        proof = run_checks(engine)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
    proof.update(expected_sha=installed, isolated_postgresql=True,
                 temporary_schema_removed=True, checked_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps(proof, ensure_ascii=False))
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
