"""History, read-only cache evidence, auth and bounded-query opportunities."""
from contextlib import ExitStack
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "agenda-opportunities-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.servico import Servico
from app.services import agenda_day_opportunities as opportunities
from app.services import geocoding_service, logistica_service
from tests import test_agenda_sugestao_janela_operacional as fixtures


_DEFAULT_LIMIT = object()


class _DateTimeMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class _FixedDateTime(datetime, metaclass=_DateTimeMeta):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 22, 12).replace(tzinfo=tz)


class AgendaDayOpportunitiesTest(unittest.TestCase):
    _build_session = fixtures.AgendaSugestaoJanelaOperacionalTest._build_session
    _seed_config = fixtures.AgendaSugestaoJanelaOperacionalTest._seed_config

    def setUp(self):
        self.tmpdir, self.db, self.engine = self._build_session()
        ClinicaDeslocamento.__table__.create(self.engine, checkfirst=True)
        self._seed_config(self.db, excecoes=[], regras_rota={
            "thresholds": {"max_neighbor_travel_min": 30, "safe_margin_min": 5,
                "max_insertion_detour_min": 30},
            "route_policy": {"regional_transition_enabled": True,
                "regional_transition_max_travel_min": 50, "regional_transition_margin_min": 15,
                "regional_transition_max_legs_per_day": 1, "recurrent_clinic_history_days": 60},
        })
        self.anchor = self.clinic("Synthetic anchor")
        self.service = Servico(nome="Synthetic 30-minute service", duracao_minutos=30, ativo=True)
        self.db.add(self.service)
        self.db.commit()
        self.book(self.anchor, "2026-10-23 09:00", "Agendado")
        self.user = SimpleNamespace(id=1, nome="Synthetic staff", tem_papel=lambda role: role == "recepcao")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def clinic(self, name, **kwargs):
        clinic = Clinica(nome=name, latitude=-3.73, longitude=-38.52,
            cidade="Fortaleza", estado="CE", bairro="Synthetic district", ativo=True, **kwargs)
        self.db.add(clinic)
        self.db.commit()
        return clinic

    def book(self, clinic, instant, status="Realizado", origin="clinica_parceira"):
        start = datetime.fromisoformat(instant)
        booking = Agendamento(clinica_id=clinic.id, inicio=start, fim=start + timedelta(minutes=30),
            data=start.date().isoformat(), hora=start.strftime("%H:%M"), status=status,
            origem_atendimento=origin, paciente="Synthetic patient PRIVATE",
            tutor="Synthetic tutor PRIVATE", telefone="PRIVATE-phone")
        self.db.add(booking)
        self.db.commit()
        return booking

    def route(self, origin, destination, duration=40, *, trusted=True):
        row = ClinicaDeslocamento(origem_clinica_id=origin.id, destino_clinica_id=destination.id,
            perfil="comercial", duracao_min=duration, distancia_km=10,
            fonte="manual" if trusted else "heuristica_haversine", manual_override=trusted)
        self.db.add(row)
        self.db.commit()
        return row

    def call(self, *, limit=_DEFAULT_LIMIT, user=None, count_queries=False):
        statements = []
        def collect(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)
        if count_queries:
            event.listen(self.engine, "before_cursor_execute", collect)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(opportunities, "datetime", _FixedDateTime))
                stack.enter_context(patch.object(agenda, "datetime", _FixedDateTime))
                forbidden_calls = []
                for name in ("_obter_deslocamento_primeira_saida", "estimar_deslocamento",
                             "geocodificar_endereco_google", "_obter_duracao_deslocamento_operacional"):
                    forbidden_calls.append(stack.enter_context(patch.object(agenda, name,
                        side_effect=AssertionError(f"Opportunities must not call {name}"))))
                for module, name in ((logistica_service, "urlopen"),
                                     (logistica_service, "_http_get_json"),
                                     (logistica_service, "_http_post_json"),
                                     (geocoding_service, "urlopen")):
                    forbidden_calls.append(stack.enter_context(patch.object(module, name,
                        side_effect=AssertionError("Opportunities must not call external providers"))))
                options = {} if limit is _DEFAULT_LIMIT else {"limite": limit}
                result = opportunities.buscar_oportunidades_dia(
                    agenda.OportunidadesDiaPayload(data="2026-10-23", servico_id=self.service.id, **options),
                    self.db, user or self.user)
                for forbidden in forbidden_calls:
                    forbidden.assert_not_called()
            return (result, statements) if count_queries else result
        finally:
            if count_queries:
                event.remove(self.engine, "before_cursor_execute", collect)

    def test_history_counts_realized_days_and_volume_only_inside_60_days(self):
        clinic = self.clinic("Synthetic recurring")
        self.route(self.anchor, clinic)
        self.book(clinic, "2026-08-23 10:00")
        self.book(clinic, "2026-08-23 11:00")
        self.book(clinic, "2026-10-21 10:00")
        for date, status, origin in (
            ("2026-08-22 10:00", "Realizado", "clinica_parceira"),
            ("2026-10-22 10:00", "Realizado", "clinica_parceira"),
            ("2026-10-24 10:00", "Realizado", "clinica_parceira"),
            ("2026-10-20 10:00", "Agendado", "clinica_parceira"),
            ("2026-10-19 10:00", "Cancelado", "clinica_parceira"),
            ("2026-10-18 10:00", "Realizado", "domiciliar"),
        ):
            self.book(clinic, date, status, origin)
        result = self.call()
        item = next(item for item in result["items"] if item["clinica_id"] == clinic.id)
        self.assertEqual(result["historico"], {"inicio": "2026-08-23", "fim": "2026-10-21", "dias": 60})
        self.assertEqual(item["dias_realizados_60d"], 2)
        self.assertEqual(item["atendimentos_realizados_60d"], 3)
        self.assertEqual(item["ultimo_atendimento"], "2026-10-21")
        self.assertEqual(item["inicio"], "2026-10-23 10:30")
        self.assertEqual(result["consultas_google"], 0)
        serialized = str(result)
        for private in ("PRIVATE", "tutor_id", "paciente_id", "telefone", "address", "zip_code"):
            self.assertNotIn(private, serialized)

    def test_history_ignores_clinics_with_only_future_or_cancelled_bookings(self):
        future = self.clinic("Synthetic future only")
        cancelled = self.clinic("Synthetic cancelled only")
        self.book(future, "2026-10-24 10:00", "Agendado")
        self.book(cancelled, "2026-10-20 10:00", "Cancelado")
        result = self.call()
        self.assertEqual(result["total_clinicas_recorrentes"], 0)
        self.assertEqual(result["items"], [])

    def test_unknown_or_heuristic_route_cannot_appear_as_zero_minutes(self):
        unknown = self.clinic("Synthetic missing route")
        heuristic = self.clinic("Synthetic heuristic only")
        for clinic in (unknown, heuristic):
            self.book(clinic, "2026-10-20 10:00")
        self.route(self.anchor, heuristic, trusted=False)
        result = self.call()
        self.assertEqual(result["items"], [])
        self.assertEqual(result["sem_estimativa"], 2)
        self.assertEqual(result["consultas_google"], 0)

    def test_missing_reverse_in_early_candidate_preserves_later_known_direction_and_regional_margin(self):
        second = self.clinic("Synthetic second anchor")
        candidate = self.clinic("Synthetic later opportunity")
        self.book(second, "2026-10-23 11:00", "Agendado")
        self.book(candidate, "2026-10-20 10:00")
        self.route(self.anchor, second, 20)
        self.route(self.anchor, candidate, 20)
        self.route(second, candidate, 50)
        # Before the second anchor the missing candidate -> second direction
        # makes that slot unverifiable. After it, second -> candidate is known.
        self.assertIsNone(self.db.query(ClinicaDeslocamento).filter_by(
            origem_clinica_id=candidate.id, destino_clinica_id=second.id,
        ).first())

        result = self.call()

        self.assertEqual([item["clinica_id"] for item in result["items"]], [candidate.id])
        item = result["items"][0]
        # 11:30 + 50 travel + 15 total margin = 12:35, rounded to the 15m grid.
        self.assertEqual(item["inicio"], "2026-10-23 12:45")
        self.assertEqual(item["tempo_deslocamento_total_min"], 50)
        self.assertTrue(item["transicao_regional"])
        self.assertEqual(result["sem_estimativa"], 0)
        self.assertEqual(result["consultas_google"], 0)

    def test_missing_route_in_late_candidate_preserves_already_valid_earlier_slots(self):
        second = self.clinic("Synthetic noon anchor")
        candidate = self.clinic("Synthetic earlier opportunity")
        self.book(second, "2026-10-23 12:00", "Agendado")
        self.book(candidate, "2026-10-20 10:00")
        self.route(self.anchor, second, 40)
        self.route(self.anchor, candidate, 20)
        self.route(candidate, second, 20)
        # Known short legs replace the existing long leg. After noon the
        # missing second -> candidate direction must not erase this result.
        self.assertIsNone(self.db.query(ClinicaDeslocamento).filter_by(
            origem_clinica_id=second.id, destino_clinica_id=candidate.id,
        ).first())

        result = self.call()

        self.assertEqual([item["clinica_id"] for item in result["items"]], [candidate.id])
        item = result["items"][0]
        self.assertEqual(item["inicio"], "2026-10-23 10:00")
        self.assertEqual(item["tempo_deslocamento_total_min"], 40)
        self.assertEqual(item["acrescimo_deslocamento_min"], 0)
        self.assertFalse(item["transicao_regional"])
        self.assertEqual(result["sem_estimativa"], 0)
        self.assertEqual(result["consultas_google"], 0)

    def test_unknown_fixed_baseline_preserves_normal_known_opportunity_after_last_anchor(self):
        second = self.clinic("Synthetic unknown-baseline anchor")
        candidate = self.clinic("Synthetic normal known opportunity")
        self.book(second, "2026-10-23 11:00", "Agendado")
        self.book(candidate, "2026-10-20 10:00")
        self.route(self.anchor, candidate, 20)
        self.route(candidate, second, 20)
        self.route(second, candidate, 20)
        # The fixed anchor -> second leg has no estimate. The later normal
        # insertion needs only second -> candidate, which is explicitly known.
        self.assertIsNone(self.db.query(ClinicaDeslocamento).filter_by(
            origem_clinica_id=self.anchor.id, destino_clinica_id=second.id,
        ).first())

        result = self.call()

        self.assertEqual([item["clinica_id"] for item in result["items"]], [candidate.id])
        item = result["items"][0]
        self.assertEqual(item["inicio"], "2026-10-23 12:00")
        self.assertEqual(item["tempo_deslocamento_total_min"], 20)
        self.assertFalse(item["transicao_regional"])
        self.assertEqual(result["sem_estimativa"], 0)
        self.assertEqual(result["consultas_google"], 0)

    def test_unknown_fixed_baseline_cannot_authorize_new_long_opportunity(self):
        second = self.clinic("Synthetic unknown-baseline anchor")
        candidate = self.clinic("Synthetic long opportunity")
        self.book(second, "2026-10-23 11:00", "Agendado")
        self.book(candidate, "2026-10-20 10:00")
        self.route(self.anchor, candidate, 40)
        self.route(candidate, second, 40)
        self.route(second, candidate, 40)

        result = self.call()

        self.assertEqual(result["items"], [])
        self.assertEqual(result["total_clinicas_recorrentes"], 1)
        self.assertEqual(result["sem_estimativa"], 1)
        self.assertEqual(result["consultas_google"], 0)

    def test_cached_unknown_baseline_counts_each_long_clinic_without_leaking_flag_to_normal_clinic(self):
        anchor_booking = self.db.query(Agendamento).filter_by(
            clinica_id=self.anchor.id, data="2026-10-23",
        ).one()
        anchor_booking.fim = datetime.fromisoformat("2026-10-23 11:00")
        self.db.commit()
        second = self.clinic("Synthetic contiguous second anchor")
        self.book(second, "2026-10-23 11:00", "Agendado")
        first_long = self.clinic("Synthetic Alpha long route")
        second_long = self.clinic("Synthetic Beta long route")
        normal = self.clinic("Synthetic Zulu normal route")
        for clinic, duration in ((first_long, 40), (second_long, 40), (normal, 20)):
            self.book(clinic, "2026-10-20 10:00")
            self.route(second, clinic, duration)
        # There is no free slot between the fixed anchors. Every candidate
        # uses a known outgoing leg after 11:30, so only the regional evaluator
        # can reject the long routes because their fixed baseline is unknown.
        observations = []
        suggest = agenda._sugerir_horarios_agenda

        def observe(payload, *args, **kwargs):
            result = suggest(payload, *args, **kwargs)
            cache = kwargs["contexto_dia"]["cache_regional"]
            observations.append((payload.clinica_id, result["teve_rota_sem_estimativa"],
                any(getattr(estimate, "duracao_min", 0) is None for estimate in cache.values())))
            return result

        with patch.object(agenda, "_sugerir_horarios_agenda", side_effect=observe):
            result = self.call()

        self.assertEqual(observations, [
            (first_long.id, True, True), (second_long.id, True, True), (normal.id, False, True),
        ])
        self.assertEqual([item["clinica_id"] for item in result["items"]], [normal.id])
        self.assertEqual(result["items"][0]["inicio"], "2026-10-23 12:00")
        self.assertFalse(result["items"][0]["transicao_regional"])
        self.assertEqual(result["sem_estimativa"], 2)
        self.assertEqual(result["consultas_google"], 0)

    def test_missing_and_reverse_only_routes_are_not_inferred_while_known_clinic_remains_visible(self):
        missing = self.clinic("Synthetic no route in either direction")
        reverse_only = self.clinic("Synthetic reverse route only")
        known = self.clinic("Synthetic known directed route")
        for clinic in (missing, reverse_only, known):
            self.book(clinic, "2026-10-20 10:00")
        self.route(reverse_only, self.anchor, 20)
        self.route(self.anchor, known, 20)

        result = self.call()

        self.assertEqual([item["clinica_id"] for item in result["items"]], [known.id])
        self.assertEqual(result["items"][0]["tempo_deslocamento_total_min"], 20)
        self.assertFalse(result["items"][0]["transicao_regional"])
        self.assertEqual(result["sem_estimativa"], 2)
        self.assertEqual(result["consultas_google"], 0)

    def test_history_distinct_days_precedes_volume_in_equal_cost_band(self):
        volume = self.clinic("Synthetic concentrated volume")
        days = self.clinic("Synthetic repeated days")
        for clinic in (volume, days):
            self.route(self.anchor, clinic, 40)
        for hour in (9, 10, 11):
            self.book(volume, f"2026-10-20 {hour:02d}:00")
        self.book(days, "2026-10-19 10:00")
        self.book(days, "2026-10-20 10:00")
        result = self.call()
        self.assertEqual([item["clinica_id"] for item in result["items"]], [days.id, volume.id])

    def test_query_count_does_not_grow_per_recurring_clinic(self):
        first = self.clinic("Synthetic first")
        self.book(first, "2026-10-20 10:00")
        self.route(self.anchor, first)
        one, one_queries = self.call(count_queries=True)
        for number in range(6):
            clinic = self.clinic(f"Synthetic extra {number}")
            self.book(clinic, "2026-10-20 10:00")
            self.route(self.anchor, clinic)
        many, many_queries = self.call(count_queries=True)
        self.assertEqual(len(one["items"]), 1)
        self.assertEqual(len(many["items"]), 7)
        self.assertLessEqual(len(many_queries), len(one_queries) + 1,
            f"SELECT count grew from {len(one_queries)} to {len(many_queries)}")
        self.assertLessEqual(len(many_queries), 12)

    def seed_ranked_clinics(self, count):
        groups = {}
        # Insert outside ranking order, varying travel bands and recurrence.
        for number in reversed(range(count)):
            clinic = self.clinic(f"Synthetic unlimited clinic {number:02d}")
            travel = 10 + 10 * (number % 3)
            days = 1 + number % 4
            self.route(self.anchor, clinic, travel)
            for offset in range(days):
                self.book(clinic, f"2026-10-{20 - offset:02d} 10:00")
            groups.setdefault((travel, days), []).append(clinic.id)
        return [cid for travel in (10, 20, 30) for days in (4, 3, 2, 1)
                for cid in groups.get((travel, days), [])]

    def database_snapshot(self):
        tables = self.db.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()
        snapshot = {}
        for table in tables:
            rows = [tuple(row) for row in self.db.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))]
            serialized = json.dumps(rows, default=str, separators=(",", ":"))
            snapshot[table] = {"count": len(rows), "sha256": hashlib.sha256(serialized.encode()).hexdigest()}
        return snapshot

    def test_null_limit_returns_all_31_clinics_in_existing_rank_order(self):
        expected_ids = self.seed_ranked_clinics(31)
        before = self.database_snapshot()

        result = self.call(limit=None)

        self.assertEqual(result["total_encontrados"], 31)
        self.assertEqual([item["clinica_id"] for item in result["items"]], expected_ids)
        self.assertEqual(result["consultas_google"], 0)
        self.assertEqual(self.database_snapshot(), before)

    def test_null_limit_exceeds_50_and_legacy_limits_keep_the_same_prefix_without_writes(self):
        expected_ids = self.seed_ranked_clinics(61)
        before = self.database_snapshot()
        with ExitStack() as stack:
            writes = []
            for name in ("commit", "flush", "add", "add_all", "delete", "merge"):
                writes.append(stack.enter_context(patch.object(self.db, name,
                    side_effect=AssertionError(f"Opportunity lookup must not {name}"))))
            unlimited = self.call(limit=None)
            twenty = self.call(limit=20)
            fifty = self.call(limit=50)
            omitted = self.call()
            for write in writes:
                write.assert_not_called()

        self.assertEqual([item["clinica_id"] for item in unlimited["items"]], expected_ids)
        self.assertEqual(len(unlimited["items"]), 61)
        self.assertEqual(twenty["items"], unlimited["items"][:20])
        self.assertEqual(fifty["items"], unlimited["items"][:50])
        self.assertEqual(omitted["items"], twenty["items"])
        for result in (unlimited, twenty, fifty, omitted):
            self.assertEqual(result["total_encontrados"], 61)
            self.assertEqual(result["total_clinicas_recorrentes"], 61)
            self.assertEqual(result["sem_estimativa"], 0)
            self.assertEqual(result["consultas_google"], 0)
        self.assertEqual(self.database_snapshot(), before)

    def test_http_limit_accepts_null_preserves_default_and_rejects_numeric_bounds(self):
        app = FastAPI()
        app.include_router(agenda.router, prefix="/api/v1/agenda")
        app.dependency_overrides[agenda.get_db] = lambda: self.db
        app.dependency_overrides[agenda.get_current_user] = lambda: self.user
        with patch.object(opportunities, "buscar_oportunidades_dia", return_value={"items": []}) as search:
            with TestClient(app) as client:
                for options, expected in (({"limite": None}, None), ({}, 20),
                                          ({"limite": 1}, 1), ({"limite": 20}, 20), ({"limite": 50}, 50)):
                    with self.subTest(options=options):
                        response = client.post("/api/v1/agenda/oportunidades-dia",
                            json={"data": "2026-10-23", **options})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(search.call_args.args[0].limite, expected)
                count = search.call_count
                for invalid in (0, 51):
                    with self.subTest(invalid=invalid):
                        response = client.post("/api/v1/agenda/oportunidades-dia",
                            json={"data": "2026-10-23", "limite": invalid})
                        self.assertEqual(response.status_code, 422)
                self.assertEqual(search.call_count, count)

    def test_endpoint_requires_auth_and_rejects_non_team_role(self):
        app = FastAPI()
        app.include_router(agenda.router, prefix="/api/v1/agenda")
        app.dependency_overrides[agenda.get_db] = lambda: self.db
        with TestClient(app) as client:
            response = client.post("/api/v1/agenda/oportunidades-dia", json={"data": "2026-10-23"})
        self.assertEqual(response.status_code, 401)
        app.dependency_overrides[agenda.get_current_user] = lambda: SimpleNamespace(
            id=2, tem_papel=lambda _role: False)
        with TestClient(app) as client:
            response = client.post("/api/v1/agenda/oportunidades-dia", json={"data": "2026-10-23"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
