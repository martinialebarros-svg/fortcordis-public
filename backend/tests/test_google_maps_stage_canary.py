"""Canary orchestration tests; no database, network, credentials or live data."""
import importlib.util
import json
import threading
import unittest
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/google_maps_stage_canary.py"
SPEC = importlib.util.spec_from_file_location("google_maps_stage_canary_under_test", SCRIPT)
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


class FakeBlocked(Exception):
    def __init__(self, reason):
        self.reason = reason


class GuardFixture:
    """Deterministic transport boundary to simulate capacity failures in a race."""
    GoogleMapsCostBlocked = FakeBlocked

    def __init__(self, unavailable=0, unexpected_reason=None):
        self.states = {}
        self.used = 0
        self.claims = 0
        self.unavailable = unavailable
        self.unexpected_reason = unexpected_reason
        self.outbound = []
        self.lock = threading.Lock()
        self.context = ContextVar("canary_test_execution", default=None)

    def create_preview(self, *_args):
        identity = str(len(self.states) + 1)
        self.states[identity] = "quoted"
        return {"required": True, "blocked": self.used >= 4, "quote_id": identity}

    def confirm_preview(self, _user, identity):
        self.states[identity] = "confirmed"
        return {"token": identity}

    def claim_execution(self, _user, identity, *_args):
        if self.states[identity] != "confirmed":
            raise FakeBlocked("invalid_grant")
        self.states[identity] = "claimed"
        self.claims += 1
        return identity

    def bind_execution(self, execution):
        return self.context.set(execution)

    def reset_execution(self, token):
        self.context.reset(token)

    def finish_execution(self, execution):
        self.states[execution] = "finished"

    @contextmanager
    def automatic_action(self, *_args):
        token = self.context.set("automatic")
        try:
            yield
        finally:
            self.context.reset(token)

    def provider(self):
        with self.lock:
            if self.context.get() == "automatic":
                raise FakeBlocked("automatic_policy_required")
            assert self.claims >= 9, "All action claims should precede the reservation race"
            if self.unexpected_reason:
                raise FakeBlocked(self.unexpected_reason)
            if self.unavailable:
                self.unavailable -= 1
                raise FakeBlocked("ledger_unavailable")
            if self.used >= 4:
                raise FakeBlocked("day_limit")
            self.used += 1
            self.outbound.append("synthetic")
            return {"synthetic_route": True}

    def get_status(self):
        return {"consumption": {period: {"calls": self.used} for period in ("day", "month")}}


class GoogleMapsStageCanaryTest(unittest.TestCase):
    def test_capacity_denials_are_visible_and_remaining_cap_is_filled_sequentially(self):
        fixture = GuardFixture(unavailable=6)
        proof, usage = canary.probe_reservation_race(fixture, fixture.provider, fixture.outbound)
        self.assertEqual(proof["concurrent_successful_reservations"], 2)
        self.assertEqual(proof["concurrent_denials"], {"ledger_unavailable": 6})
        self.assertEqual(proof["sequential_completion_calls"], 2)
        self.assertEqual(proof["synthetic_outbound_calls"], 4)
        self.assertEqual(usage["day"]["calls"], 4)
        self.assertEqual(proof["next_call_blocked_reason"], "day_limit")
        self.assertTrue(proof["replay_blocked"] and proof["automatic_without_policy_blocked"])

    def test_healthy_race_needs_no_sequential_completion(self):
        fixture = GuardFixture()
        proof, _ = canary.probe_reservation_race(fixture, fixture.provider, fixture.outbound)
        self.assertEqual(proof["concurrent_successful_reservations"], 4)
        self.assertEqual(proof["concurrent_denials"], {"day_limit": 4})
        self.assertEqual(proof["sequential_completion_calls"], 0)

    def test_unexpected_denial_is_not_misreported_as_successful_budget_proof(self):
        fixture = GuardFixture(unexpected_reason="configuration_changed")
        with self.assertRaisesRegex(AssertionError, "Unexpected concurrent denial"):
            canary.probe_reservation_race(fixture, fixture.provider, fixture.outbound)
        self.assertEqual(fixture.outbound, [])

    def test_actual_overspend_still_fails_the_canary(self):
        fixture = GuardFixture()
        def broken_boundary():
            with fixture.lock:
                fixture.used += 1
                fixture.outbound.append("synthetic")
                return {"synthetic_route": True}
        with self.assertRaisesRegex(AssertionError, "overspend"):
            canary.probe_reservation_race(fixture, broken_boundary, fixture.outbound)

    def test_database_diagnostic_exposes_only_allowlisted_categories(self):
        error = Exception("FATAL MaxClientsInSessionMode: max clients reached PRIVATE_URL PRIVATE_PASSWORD")
        context = SimpleNamespace(original_exception=error, statement=None, parameters={"secret": "PRIVATE"})
        diagnostic = canary.sanitized_database_diagnostic(context)
        self.assertEqual(diagnostic["category"], "connection_capacity")
        self.assertEqual(diagnostic["operation"], "connect")
        self.assertNotIn("PRIVATE", json.dumps(diagnostic))
        error.pgcode = "55P03"
        context.statement = "SELECT pg_advisory_xact_lock(:PRIVATE)"
        diagnostic = canary.sanitized_database_diagnostic(context)
        self.assertEqual(diagnostic["category"], "lock_timeout")
        self.assertEqual(diagnostic["operation"], "advisory_lock")
        self.assertNotIn("PRIVATE", json.dumps(diagnostic))


if __name__ == "__main__":
    unittest.main()
