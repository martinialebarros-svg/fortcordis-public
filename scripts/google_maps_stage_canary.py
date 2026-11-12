#!/usr/bin/env python3
"""Stage-only proof with an isolated PostgreSQL schema and zero Google traffic.

The live API is probed only for default denial. Successful execution/concurrency
use the deployed code in this process with a synthetic transport and schema.
No existing policy, clinic, appointment or message is modified.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo


def sanitized_database_diagnostic(context):
    """Classify locally; never emit exception text, DSN, SQL or parameters."""
    original = context.original_exception
    code = getattr(original, "pgcode", None)
    if code is not None and (len(str(code)) != 5 or not str(code).isalnum()):
        code = None
    statement = (context.statement or "").upper()
    operation = "connect" if not statement else ("advisory_lock" if "PG_ADVISORY_XACT_LOCK" in statement else "database_operation")
    message = str(original).lower()
    if code == "55P03":
        category = "lock_timeout"
    elif code == "57014":
        category = "statement_timeout_or_cancel"
    elif code == "53300" or any(fragment in message for fragment in (
        "maxclientsinsessionmode", "max clients reached", "max client connections",
        "remaining connection slots", "too many clients", "too many connections",
    )):
        category = "connection_capacity"
    elif "timeout" in message or "timed out" in message:
        category = "connection_timeout" if operation == "connect" else "database_timeout"
    elif "password authentication failed" in message:
        category = "authentication_failure"
    elif "tenant or user not found" in message:
        category = "tenant_routing_failure"
    elif "could not translate host name" in message:
        category = "dns_failure"
    elif "connection refused" in message:
        category = "connection_refused"
    elif "ssl" in message or "server closed the connection" in message:
        category = "connection_transport"
    else:
        category = "connection_establishment" if operation == "connect" else "database_error"
    return {"exception_class": type(original).__name__, "pgcode": code,
            "operation": operation, "category": category}


def probe_reservation_race(guard, provider, outbound, *, user_id=999999, attempts=8, daily_limit=4):
    """Race reservations, keep fail-closed errors visible, then test the exact cap.

    Grants are claimed sequentially so connection acquisition in a preliminary
    claim cannot abort the budget test before it reaches the paid boundary.
    Transient ledger failures count as denials, never as successful reservations.
    At most `daily_limit` sequential calls fill any capacity left by the race.
    An extra preclaimed action proves the next reservation is blocked by budget.
    """
    path = "/api/v1/logistica/deslocamento"
    query = {"origem_clinica_id": "1", "destino_clinica_id": "2"}
    cleanup_denials = []

    def quote():
        return guard.create_preview(user_id, "GET", path, query, None)

    def grant():
        preview = quote()
        assert not preview["blocked"], "Unexpected sequential preview denial"
        token = guard.confirm_preview(user_id, preview["quote_id"])["token"]
        return token, guard.claim_execution(user_id, token, "GET", path, query, None)

    def reserve(execution):
        context = guard.bind_execution(execution)
        try:
            assert provider() is not None, "Synthetic provider returned no route"
            return "sent"
        except guard.GoogleMapsCostBlocked as exc:
            return exc.reason
        finally:
            guard.reset_execution(context)

    def finish(execution):
        try:
            guard.finish_execution(execution)
        except guard.GoogleMapsCostBlocked as exc:
            assert exc.reason == "ledger_unavailable", "Unexpected finalization denial"
            cleanup_denials.append(exc.reason)

    abandoned = quote()
    assert abandoned["required"] and not outbound
    claimed = [grant() for _ in range(attempts + 1)]
    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(reserve, [execution for _, execution in claimed[:attempts]]))
    concurrent_sent = results.count("sent")
    denied = Counter(result for result in results if result != "sent")
    assert set(denied) <= {"day_limit", "ledger_unavailable"}, "Unexpected concurrent denial reason"
    assert concurrent_sent == len(outbound) <= daily_limit, "Reservation/transport mismatch or overspend"
    for _, execution in claimed[:attempts]:
        finish(execution)

    sequential_sent = 0
    for _ in range(daily_limit - concurrent_sent):
        _, execution = grant()
        try:
            outcome = reserve(execution)
            assert outcome == "sent", f"Sequential capacity probe denied: {outcome}"
            sequential_sent += 1
        finally:
            finish(execution)
    assert len(outbound) == daily_limit

    overflow_execution = claimed[-1][1]
    try:
        assert reserve(overflow_execution) == "day_limit", "Next call was not denied by daily budget"
    finally:
        finish(overflow_execution)
    assert len(outbound) == daily_limit
    try:
        guard.claim_execution(user_id, claimed[0][0], "GET", path, query, None)
        raise AssertionError("Replay accepted")
    except guard.GoogleMapsCostBlocked as exc:
        assert exc.reason == "invalid_grant", "Replay not verified: another failure occurred"
    try:
        with guard.automatic_action("whatsapp_agenda", "synthetic-one-job"):
            provider()
        raise AssertionError("Automatic operation without policy accepted")
    except guard.GoogleMapsCostBlocked as exc:
        assert exc.reason == "automatic_policy_required", "Automatic policy denial not verified"
    assert len(outbound) == daily_limit
    usage = guard.get_status()["consumption"]
    assert usage["day"]["calls"] == daily_limit and usage["month"]["calls"] == daily_limit
    return {
        "cancelled_preview_paid_calls": 0, "concurrent_attempts": attempts,
        "concurrent_successful_reservations": concurrent_sent,
        "concurrent_denials": dict(denied), "sequential_completion_calls": sequential_sent,
        "synthetic_outbound_calls": len(outbound), "daily_limit": daily_limit,
        "next_call_blocked_reason": "day_limit", "replay_blocked": True,
        "automatic_without_policy_blocked": True, "cleanup_denials": cleanup_denials,
    }, usage


def probe_cache_only(guard, engine, *, user_id=999999):
    """Real zero-call API proof in the caller's disposable schema only."""
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.core.security import get_current_user
    from app.models.clinica import Clinica
    from app.models.clinica_deslocamento import ClinicaDeslocamento
    from app.api.v1.endpoints import logistica, google_maps_cost_control as control_api
    from app.services import google_maps_cost_middleware as middleware

    before = guard.get_status()
    cache_config = guard.CostConfiguration.model_validate({
        "operation_mode": "cache_only", "enabled": True,
        "limits": {period: {"calls": 0, "estimated_brl": 0} for period in ("action", "day", "month")},
    })
    status = guard.update_configuration(user_id, cache_config, before["revision"])
    assert status["operation_mode"] == "cache_only" and not status["paid_calls_allowed"]
    assert "prices_usd" not in status["config"] and "fx_brl_per_usd_upper" not in status["config"]
    assert status["opening_usage"] == before["opening_usage"], "Existing baseline must not be erased or fabricated"
    for model in (Clinica, ClinicaDeslocamento):
        model.__table__.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add_all([Clinica(id=1, nome="Synthetic cache canary A", latitude=-3.7, longitude=-38.5),
                    Clinica(id=2, nome="Synthetic cache canary B", latitude=-3.8, longitude=-38.6),
                    ClinicaDeslocamento(origem_clinica_id=1, destino_clinica_id=2, perfil="comercial",
                        distancia_km=1, duracao_min=10, fonte="google_routes_api", updated_at=datetime.now(timezone.utc))])
        db.commit()
    app = FastAPI()
    app.include_router(logistica.router, prefix="/api/v1/logistica")
    app.include_router(control_api.router, prefix="/api/v1/google-maps-control")
    app.add_middleware(middleware.GoogleMapsCostMiddleware)
    def request_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[logistica.get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id, tem_papel=lambda _: True)
    path = "/api/v1/logistica/deslocamento"
    with patch.object(middleware, "_authenticate", return_value=user_id), TestClient(app) as client:
        quote = client.post("/api/v1/google-maps-control/preview", json={"method": "GET", "path": path})
        assert quote.status_code == 200
        assert not quote.json()["required"] and quote.json()["max_calls"] == 0 and quote.json()["quote_id"] is None
        hit = client.get(path, params={"origem_clinica_id": 1, "destino_clinica_id": 2})
        assert hit.status_code == 200 and hit.json()["item"]["duracao_min"] == 10
        cold = client.get(path, params={"origem_clinica_id": 2, "destino_clinica_id": 1})
        assert cold.status_code == 409 and cold.json()["detail"]["reason"] == "cache_only"
        with sessions() as db:
            row = db.query(ClinicaDeslocamento).one()
            row.fonte = "heuristica_haversine"
            db.commit()
        heuristic = client.get(path, params={"origem_clinica_id": 1, "destino_clinica_id": 2})
        assert heuristic.status_code == 409 and heuristic.json()["detail"]["reason"] == "cache_only"
    for automatic in (False, True):
        def attempt():
            try:
                guard.authorize_google_call("routes_essentials")
            except guard.GoogleMapsCostBlocked as exc:
                assert exc.reason == "cache_only", "A connection error is not proof of cache-only denial"
            else:
                raise AssertionError("Cache-only unexpectedly authorized a paid call")
        if automatic:
            with guard.automatic_action("whatsapp_agenda", "isolated-cache-canary"):
                attempt()
        else:
            attempt()
    engine.dispose()
    assert guard.get_status()["consumption"] == before["consumption"]
    assert guard.get_status()["operation_mode"] == "cache_only"
    return {"cache_only_real_api_hit_without_grant": True, "cache_only_cold_and_heuristic_blocked": True,
            "cache_only_direct_and_automatic_blocked": True, "cache_only_survives_reconnect": True,
            "cache_only_previous_usage_preserved": True}


def main():
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    if root != Path("/var/www/fortcordis-stage"):
        raise RuntimeError("Canário permitido somente no checkout de stage.")
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(root / "scripts"))
    from app.core.config import settings
    from fiscal_rotina_stage_canary import _validar_destino
    _validar_destino(root, settings.APP_ENV, settings.DATABASE_URL)

    from deploy_authenticated_canary import _token_from_internal_backend
    bearer = _token_from_internal_backend(str(backend))

    def live_request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request("http://127.0.0.1:8001/api/v1" + path, data=data,
                      headers={"Authorization": "Bearer " + bearer, "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=20) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    code, live_status = live_request("/google-maps-control/status")
    assert code == 200 and not live_status["enabled"], "Stage deve permanecer sem gasto habilitado"
    code, denial = live_request("/agenda/sugestoes-horario", {})
    assert code == 409 and denial["detail"]["code"] == "GOOGLE_MAPS_COST_BLOCKED"
    code, denied_preview = live_request("/google-maps-control/preview", {
        "method": "POST", "path": "/api/v1/agenda/sugestoes-horario", "body": {},
    })
    assert code == 200 and denied_preview["blocked"] and denied_preview["quote_id"] is None

    from sqlalchemy import create_engine, event, text
    from app.db import database
    from app.models.google_maps_cost_control import COST_TABLES
    from app.services import google_maps_cost_control as guard, logistica_service, geocoding_service
    schema = "maps_canary_" + uuid4().hex
    admin = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    synthetic = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=8,
                              execution_options={"schema_translate_map": {None: schema}})
    database_diagnostics = []
    def record_sanitized_database_error(context):
        diagnostic = sanitized_database_diagnostic(context)
        database_diagnostics.append(diagnostic)
        print(json.dumps({"sanitized_database_diagnostic": diagnostic}), file=sys.stderr, flush=True)
    event.listen(synthetic, "handle_error", record_sanitized_database_error)
    try:
        for table in COST_TABLES:
            table.create(synthetic)
        day = datetime.now(ZoneInfo("America/Fortaleza")).date().isoformat()
        config = guard.CostConfiguration.model_validate({
            "enabled": True,
            "limits": {"action": {"calls": 3, "estimated_brl": 1},
                       "day": {"calls": 4, "estimated_brl": 1},
                       "month": {"calls": 5, "estimated_brl": 1}},
            "prices_usd": {sku: "0.01" for sku in guard.SKUS},
            "fx_brl_per_usd_upper": 6, "price_multiplier": 1,
            "pricing_valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "opening_usage": {"day": {"calls": 0, "estimated_brl": 0},
                              "month": {"calls": 0, "estimated_brl": 0}},
            "opening_usage_as_of": day, "opening_usage_basis": "synthetic_stage",
        })
        outbound = []
        def fake_http(*args, **kwargs):
            outbound.append("synthetic")
            return {"routes": [{"distanceMeters": 1000, "duration": "600s"}]}
        with (patch.object(database, "engine", synthetic),
              patch.object(settings, "GOOGLE_MAPS_API_KEY", "synthetic-stage-only"),
              patch.object(logistica_service, "urlopen", side_effect=AssertionError("Unexpected real transport")),
              patch.object(logistica_service, "_http_get_json", side_effect=AssertionError("Unexpected fallback transport")),
              patch.object(geocoding_service, "urlopen", side_effect=AssertionError("Unexpected geocoding transport")),
              patch.object(logistica_service, "_http_post_json", side_effect=fake_http)):
            guard.update_configuration(999999, config, 0)
            proof, usage = probe_reservation_race(guard, lambda: logistica_service._consultar_google_routes_api_raw(
                {"address": "synthetic A"}, {"address": "synthetic B"}), outbound)
            # Reopen the pool: authorization/usage is durable, not process cache.
            synthetic.dispose()
            assert guard.get_status()["consumption"] == usage
            cache_proof = probe_cache_only(guard, synthetic)
            assert len(outbound) == proof["synthetic_outbound_calls"], "Cache-only must not call the provider transport"
        print(json.dumps({"stage_live_direct_request_blocked": True,
            "stage_live_preview_blocked": True, "isolated_postgresql": True,
            **proof, **cache_proof, "database_diagnostics": database_diagnostics,
            "usage_survives_reconnect": True, "actual_google_calls": 0,
            "existing_operational_records_modified": 0}))
    finally:
        synthetic.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
