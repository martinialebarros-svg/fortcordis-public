"""No live Google calls. Same invariants run on SQLite and isolated PostgreSQL.

MAPS_COST_TEST_POSTGRES_URL opts into a disposable DB; each test gets a unique
schema. Multiprocess tests use independent engines and DB connections.
"""
import copy
import importlib.util
import json
import multiprocessing
import os
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./maps-cost-unused.db")
os.environ.setdefault("SECRET_KEY", "google-maps-cost-control-test-secret-1234567890")

from app.api.v1.endpoints import google_maps_cost_control as endpoints
from app.core.security import get_current_user
from app.models.google_maps_cost_control import COST_TABLES
from app.services import google_maps_cost_control as guard
from app.services import google_maps_cost_middleware as middleware


def _engine(url, schema=None):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if schema:
        @event.listens_for(engine, "connect")
        def search_path(connection, _):
            cursor = connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()
    return engine


def _reserve_process(url, schema, execution_id, barrier, queue):
    guard.database.engine = _engine(url, schema)
    guard.bind_execution(guard.Execution(execution_id))
    barrier.wait(timeout=20)
    try:
        guard.authorize_google_call("routes_essentials")
        queue.put("reserved")
    except guard.GoogleMapsCostBlocked as exc:
        queue.put(exc.reason)
    finally:
        guard.database.engine.dispose()


class GoogleMapsCostControlTest(unittest.TestCase):
    postgres = False

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.schema = None
        if self.postgres:
            self.url = os.environ["MAPS_COST_TEST_POSTGRES_URL"]
            parsed = make_url(self.url)
            if parsed.get_backend_name() != "postgresql" or parsed.host not in {"localhost", "127.0.0.1", "::1"} or parsed.database != "maps_cost_test":
                raise RuntimeError("PostgreSQL proof only accepts disposable localhost/maps_cost_test")
            self.schema = "maps_cost_" + uuid.uuid4().hex
            self.admin_engine = create_engine(self.url)
            with self.admin_engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        else:
            self.url = f"sqlite:///{self.tmpdir.name}/ledger.db"
        self.engine = _engine(self.url, self.schema)
        self.engine_patch = patch.object(guard.database, "engine", self.engine)
        self.engine_patch.start()
        self.key_patch = patch.object(guard.settings, "SECRET_KEY", "google-maps-cost-control-test-secret-1234567890")
        self.key_patch.start()
        for table in COST_TABLES:
            table.create(self.engine)
        self.config = {
            "enabled": True,
            "limits": {key: {"calls": 50, "estimated_brl": 100} for key in ("action", "day", "month")},
            "prices_usd": {key: "0.01" for key in guard.SKUS},
            "fx_brl_per_usd_upper": "5", "price_multiplier": "1.2",
            "pricing_valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "opening_usage": {key: {"calls": 0, "estimated_brl": 0} for key in ("day", "month")},
            "opening_usage_as_of": guard._periods(guard._now())[0],
            "opening_usage_basis": "verified_telemetry",
            "automatic_policies": {},
        }

    def tearDown(self):
        guard._execution.set(None)
        self.key_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        if self.schema:
            with self.admin_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            self.admin_engine.dispose()
        self.tmpdir.cleanup()

    def configure(self, revision=0):
        return guard.update_configuration(7, guard.CostConfiguration.model_validate(self.config), revision)

    def grant(self, *, path="/api/v1/agenda/sugestoes-horario", body=None, query=None, user_id=7):
        quote = guard.create_preview(user_id, "POST", path, query, body)
        self.assertFalse(quote["blocked"], quote)
        token = guard.confirm_preview(user_id, quote["quote_id"])["token"]
        return quote, token

    def claim(self, token, *, path="/api/v1/agenda/sugestoes-horario", body=None, query=None, user_id=7):
        return guard.claim_execution(user_id, token, "POST", path, query, body)

    def reserve(self, execution, sku="routes_essentials"):
        token = guard.bind_execution(execution)
        try:
            guard.authorize_google_call(sku)
        finally:
            guard.reset_execution(token)

    def test_unconfigured_and_unscoped_fail_closed(self):
        quote = guard.create_preview(7, "POST", "/api/v1/agenda/sugestoes-horario")
        self.assertTrue(quote["blocked"])
        self.assertEqual(quote["reason"], "unconfigured")
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            guard.authorize_google_call("routes_essentials")
        self.assertEqual(guard.get_status()["consumption"]["month"]["calls"], 0)

    def test_cancel_preview_makes_no_reservation_or_confirmed_grant(self):
        self.configure()
        quote = guard.create_preview(7, "POST", "/api/v1/agenda/sugestoes-horario")
        self.assertEqual(quote["max_calls"], 50)
        self.assertEqual(quote["estimated_cost_max_brl"], 3.0)
        with self.engine.connect() as conn:
            states = conn.execute(select(guard.ACTIONS.c.state)).scalars().all()
        self.assertEqual(states, ["quoted"])
        self.assertEqual(guard.get_status()["consumption"]["month"]["calls"], 0)

    def test_one_grant_is_bound_to_user_full_payload_and_one_execution(self):
        self.configure()
        _, token = self.grant(body={"date": "2026-10-18", "address": "PRIVATE ADDRESS"}, query="id=1&id=2")
        for kwargs in (
            {"user_id": 8, "body": {"date": "2026-10-18", "address": "PRIVATE ADDRESS"}, "query": "id=1&id=2"},
            {"body": {"date": "2026-10-19", "address": "PRIVATE ADDRESS"}, "query": "id=1&id=2"},
            {"body": {"date": "2026-10-18", "address": "PRIVATE ADDRESS"}, "query": "id=1"},
        ):
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                self.claim(token, **kwargs)
        execution = self.claim(token, body={"address": "PRIVATE ADDRESS", "date": "2026-10-18"}, query="id=1&id=2")
        self.reserve(execution)
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            self.claim(token, body={"address": "PRIVATE ADDRESS", "date": "2026-10-18"}, query="id=1&id=2")
        with self.engine.connect() as conn:
            serialized = str(conn.execute(select(guard.ACTIONS)).all()) + str(conn.execute(select(guard.EVENTS)).all())
        self.assertNotIn("PRIVATE ADDRESS", serialized)
        self.assertNotIn(token, serialized)

    def test_action_cap_and_sku_are_enforced_before_extra_attempt(self):
        self.config["limits"]["action"]["calls"] = 1
        self.configure()
        _, token = self.grant(path="/api/v1/clinicas/geocode-endereco")
        execution = self.claim(token, path="/api/v1/clinicas/geocode-endereco")
        with self.assertRaises(guard.GoogleMapsCostBlocked) as wrong_sku:
            self.reserve(execution)
        self.assertEqual(wrong_sku.exception.reason, "sku_not_authorized")
        self.reserve(execution, "geocoding")
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exceeded:
            self.reserve(execution, "geocoding")
        self.assertEqual(exceeded.exception.reason, "action_limit")
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 1)

    def test_cost_is_reserved_even_if_business_transaction_rolls_back(self):
        self.configure()
        _, token = self.grant()
        execution = self.claim(token)
        with self.engine.connect() as business:
            transaction = business.begin()
            business.execute(text("SELECT 1"))
            self.reserve(execution)
            transaction.rollback()
        guard.finish_execution(execution)
        self.assertEqual(guard.get_status()["consumption"]["day"], {"calls": 1, "estimated_brl": 0.06})
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            self.reserve(execution)

    def test_ledger_failure_prevents_sending(self):
        self.configure()
        _, token = self.grant()
        execution = self.claim(token)
        with patch.object(self.engine, "connect", side_effect=RuntimeError("private database password")):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as caught:
                self.reserve(execution)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("password", str(caught.exception.detail))

    def test_confirmation_expires_and_config_change_revokes(self):
        self.configure()
        quote, token = self.grant()
        with patch.object(guard, "_now", return_value=guard._now() + guard.QUOTE_TTL_SECONDS + 1):
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                self.claim(token)
        _, fresh_token = self.grant()
        self.configure(revision=1)
        with self.assertRaises(guard.GoogleMapsCostBlocked) as changed:
            self.claim(fresh_token)
        self.assertEqual(changed.exception.reason, "configuration_changed")

    def test_expired_pricing_and_invalid_numeric_inputs_fail_closed(self):
        self.config["pricing_valid_until"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        self.configure()
        self.assertEqual(guard.create_preview(7, "POST", "/api/v1/agenda")["reason"], "pricing_expired")
        for value in ("NaN", "Infinity", "0", "-1", "1e-300", "0.00499"):
            broken = copy.deepcopy(self.config)
            broken["prices_usd"]["routes_essentials"] = value
            with self.assertRaises(ValidationError):
                guard.CostConfiguration.model_validate(broken)

    def test_daily_monthly_and_cost_limits_hold_across_engines(self):
        self.config["limits"]["day"] = {"calls": 3, "estimated_brl": "0.12"}
        self.configure()
        executions = [self.claim(self.grant()[1]) for _ in range(5)]
        results = []
        for execution in executions:
            # Simulate a process restart with a new pool, not an in-memory count.
            fresh = _engine(self.url, self.schema)
            try:
                with patch.object(guard.database, "engine", fresh):
                    try:
                        self.reserve(execution)
                        results.append("sent")
                    except guard.GoogleMapsCostBlocked as exc:
                        results.append(exc.reason)
            finally:
                fresh.dispose()
        self.assertEqual(results.count("sent"), 2)
        self.assertEqual(guard.get_status()["consumption"]["day"]["estimated_brl"], 0.12)

    def test_monthly_limit_binds_even_when_daily_limit_has_capacity(self):
        self.config["limits"]["month"]["calls"] = 2
        self.configure()
        executions = [self.claim(self.grant()[1]) for _ in range(3)]
        self.reserve(executions[0])
        self.reserve(executions[1])
        with self.assertRaises(guard.GoogleMapsCostBlocked) as exceeded:
            self.reserve(executions[2])
        self.assertEqual(exceeded.exception.reason, "month_limit")
        self.assertEqual(guard.get_status()["remaining"]["day"]["calls"], 48)

    def test_synthetic_baseline_is_rejected_in_production(self):
        self.config["opening_usage_basis"] = "synthetic_stage"
        with patch.object(guard.settings, "APP_ENV", "production"):
            with self.assertRaises(ValidationError):
                guard.CostConfiguration.model_validate(self.config)

    def test_simultaneous_processes_cannot_exceed_shared_cap(self):
        self.config["limits"]["day"]["calls"] = 2
        self.configure()
        executions = [self.claim(self.grant()[1]) for _ in range(6)]
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(len(executions)), ctx.Queue()
        workers = [ctx.Process(target=_reserve_process, args=(self.url, self.schema, execution.action_id, barrier, queue)) for execution in executions]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=40) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(results.count("reserved"), 2, results)
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 2)

    def test_simultaneous_claims_cannot_reuse_confirmation(self):
        self.configure()
        _, token = self.grant()
        def claim_once(_):
            try:
                self.claim(token)
                return "claimed"
            except guard.GoogleMapsCostBlocked as exc:
                return exc.reason
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(claim_once, range(8)))
        self.assertEqual(results.count("claimed"), 1)
        self.assertEqual(results.count("invalid_grant"), 7)

    def test_automatic_default_denied_and_no_map_job_needs_no_policy(self):
        # Lazy wrapper does not acquire a ledger connection for a free job.
        with patch.object(self.engine, "connect", side_effect=AssertionError("must not access ledger")):
            with guard.automatic_action("whatsapp_agenda", "free-job"):
                pass
        self.configure()
        with guard.automatic_action("whatsapp_agenda", "paid-job"):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as caught:
                guard.authorize_google_call("routes_essentials")
        self.assertEqual(caught.exception.reason, "automatic_policy_required")

    def test_automatic_has_own_limits_and_restarts_do_not_repeat_run(self):
        self.config["automatic_policies"] = {"whatsapp_agenda": {
            "enabled": True, "skus": ["routes_essentials"],
            "limits": {key: {"calls": 1, "estimated_brl": 5} for key in ("action", "day", "month")},
        }}
        self.configure()
        with guard.automatic_action("whatsapp_agenda", "job-1"):
            guard.authorize_google_call("routes_essentials")
            with self.assertRaises(guard.GoogleMapsCostBlocked):
                guard.authorize_google_call("routes_essentials")
        with guard.automatic_action("whatsapp_agenda", "job-1"):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as replay:
                guard.authorize_google_call("routes_essentials")
        self.assertEqual(replay.exception.reason, "automatic_replay")
        with guard.automatic_action("whatsapp_agenda", "job-2"):
            with self.assertRaises(guard.GoogleMapsCostBlocked) as cap:
                guard.authorize_google_call("routes_essentials")
        self.assertEqual(cap.exception.reason, "day_limit")
        # Interactive action still has global capacity, proving separate policy.
        self.reserve(self.claim(self.grant()[1]))
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 2)

    def test_opening_usage_is_required_applied_once_and_never_reset_by_config(self):
        no_baseline = copy.deepcopy(self.config)
        del no_baseline["opening_usage"]
        with self.assertRaises(ValidationError):
            guard.CostConfiguration.model_validate(no_baseline)
        self.config["opening_usage"] = {"day": {"calls": 2, "estimated_brl": 1}, "month": {"calls": 10, "estimated_brl": 4}}
        self.configure()
        self.assertEqual(guard.get_status()["consumption"], {"day": {"calls": 2, "estimated_brl": 1}, "month": {"calls": 10, "estimated_brl": 4}})
        self.config["limits"]["month"]["calls"] = 99
        self.configure(revision=1)
        self.assertEqual(guard.get_status()["consumption"]["month"]["calls"], 10)
        self.config["opening_usage"]["month"]["calls"] = 0
        self.config["opening_usage"]["day"]["calls"] = 0
        with self.assertRaises(guard.GoogleMapsCostBlocked):
            self.configure(revision=2)

    def test_day_and_month_rollover_use_declared_timezone(self):
        fixed = int(datetime(2026, 10, 31, 23, 59, 0, tzinfo=guard.LEDGER_TIMEZONE).timestamp())
        self.config["opening_usage_as_of"] = "2026-10-31"
        self.config["pricing_valid_until"] = "2026-12-01T00:00:00+00:00"
        with patch.object(guard, "_now", return_value=fixed):
            self.configure()
            self.reserve(self.claim(self.grant()[1]))
            self.assertEqual(guard.get_status()["consumption"]["month"]["calls"], 1)
        with patch.object(guard, "_now", return_value=fixed + 120):
            self.assertEqual(guard.get_status()["consumption"]["month"]["calls"], 0)

    def test_middleware_direct_cancel_confirm_replay_and_admin_authorization(self):
        self.configure()
        app, calls = FastAPI(), []
        app.include_router(endpoints.router, prefix="/api/v1/google-maps-control")
        app.add_middleware(middleware.GoogleMapsCostMiddleware)
        @app.post("/api/v1/agenda/sugestoes-horario")
        def paid_endpoint():
            guard.authorize_google_call("routes_essentials")
            calls.append("sent")
            return {"ok": True}
        user = SimpleNamespace(id=7, tem_papel=lambda role: role == "admin")
        app.dependency_overrides[get_current_user] = lambda: user
        with patch.object(middleware, "_authenticate", return_value=7), TestClient(app) as client:
            args = {"method": "POST", "path": "/api/v1/agenda/sugestoes-horario", "body": {"date": "2026-10-18"}}
            direct = client.post(args["path"], json=args["body"])
            self.assertEqual(direct.status_code, 409)
            quote = client.post("/api/v1/google-maps-control/preview", json=args).json()
            self.assertEqual(calls, [])  # Cancel is no confirm and no execution.
            confirmed = client.post("/api/v1/google-maps-control/confirm", json={"quote_id": quote["quote_id"]}).json()
            response = client.post(args["path"], json=args["body"], headers={"X-Google-Maps-Action": confirmed["token"]})
            self.assertEqual(response.status_code, 200, response.text)
            replay = client.post(args["path"], json=args["body"], headers={"X-Google-Maps-Action": confirmed["token"]})
            self.assertEqual(replay.status_code, 409)
            self.assertEqual(calls, ["sent"])
            user.tem_papel = lambda _: False
            self.assertEqual(client.get("/api/v1/google-maps-control/status").status_code, 403)
            self.assertEqual(client.put("/api/v1/google-maps-control/config", json={**self.config, "expected_revision": 1}).status_code, 403)

    def test_cost_free_status_remains_available_without_config_or_consent(self):
        app = FastAPI()
        app.add_middleware(middleware.GoogleMapsCostMiddleware)
        @app.patch("/api/v1/agenda/{appointment_id}/status")
        def change_status(appointment_id: int, status: str):
            return {"status": status}
        preview = guard.create_preview(7, "PATCH", "/api/v1/agenda/42/status", "status=Cancelado")
        self.assertFalse(preview["required"])
        with patch.object(middleware, "_authenticate", return_value=7), TestClient(app) as client:
            self.assertEqual(client.patch("/api/v1/agenda/42/status?status=Cancelado").status_code, 200)
            self.assertEqual(client.patch("/api/v1/agenda/42/status?status=Confirmado").status_code, 409)
            # Body cannot disguise the actual query status.
            self.assertEqual(client.patch("/api/v1/agenda/42/status?status=Confirmado", json={"status": "Cancelado"}).status_code, 409)

    def test_migration_is_additive_idempotent_and_protects_postgres_tables(self):
        path = BACKEND_DIR / "migrations/versions/20261018_99_google_maps_cost_control.py"
        spec = importlib.util.spec_from_file_location("maps_cost_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE unrelated_preserved (id INTEGER PRIMARY KEY, value TEXT)"))
            conn.execute(text("INSERT INTO unrelated_preserved VALUES (1, 'preserve')"))
            module.upgrade(conn, conn.dialect.name)
            module.upgrade(conn, conn.dialect.name)
            self.assertEqual(conn.execute(text("SELECT value FROM unrelated_preserved")).scalar(), "preserve")
            if self.postgres:
                rows = conn.execute(text("SELECT relrowsecurity FROM pg_class JOIN pg_namespace ON pg_class.relnamespace=pg_namespace.oid WHERE nspname=:schema AND relname IN ('google_maps_cost_config', 'google_maps_cost_actions', 'google_maps_cost_events')"), {"schema": self.schema}).scalars().all()
                self.assertEqual(rows, [True, True, True])

    def test_stage_cache_only_canary_keeps_previous_usage_and_blocks_new_transports(self):
        from app.services import logistica_service, geocoding_service
        self.configure()
        _, token = self.grant()
        self.reserve(self.claim(token))
        path = BACKEND_DIR.parent / "scripts/google_maps_stage_canary.py"
        spec = importlib.util.spec_from_file_location("maps_cache_stage_canary", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with (
            patch.object(logistica_service, "_http_post_json", side_effect=AssertionError("Cache-only sent a route")) as route_transport,
            patch.object(logistica_service, "_http_get_json", side_effect=AssertionError("Cache-only sent a matrix")) as matrix_transport,
            patch.object(geocoding_service, "_http_get_json", side_effect=AssertionError("Cache-only sent a geocode")) as geocode_transport,
        ):
            proof = module.probe_cache_only(guard, self.engine)
            self.assertTrue(all(proof.values()))
            route_transport.assert_not_called()
            matrix_transport.assert_not_called()
            geocode_transport.assert_not_called()
        self.assertEqual(guard.get_status()["consumption"]["day"]["calls"], 1)


@unittest.skipUnless(os.environ.get("MAPS_COST_TEST_POSTGRES_URL"), "Set disposable MAPS_COST_TEST_POSTGRES_URL for real PostgreSQL proof")
class GoogleMapsCostControlPostgresTest(GoogleMapsCostControlTest):
    postgres = True


if __name__ == "__main__":
    unittest.main()
