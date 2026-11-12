"""Synthetic data only. Run: python3 -m unittest discover -s scripts/tests -p 'test_agenda_efficiency_metrics.py'."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta, timezone


PATH = Path(__file__).parents[1] / "agenda_efficiency_metrics.py"
SPEC = importlib.util.spec_from_file_location("agenda_efficiency_metrics", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
RELEASE = datetime.fromisoformat(m.RELEASE_FINISHED)
AS_OF = datetime(2026, 10, 4, 23, tzinfo=timezone.utc)


def row(hour, duration=40, *, day="2026-09-01", clinic=1001, **kwargs):
    start = datetime.fromisoformat(f"{day}T{hour}:00-03:00")
    return {
        "inicio": start, "fim": start + timedelta(minutes=duration), "data": day,
        "hora": hour, "status": "Realizado", "clinica_id": clinic,
        "origem_atendimento": "clinica_parceira", "catalogo_min": duration,
        "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc), **kwargs,
    }


def summary(rows):
    return m.make_report(rows, as_of=AS_OF, release=RELEASE)["reference_month"]


class AgendaEfficiencyTests(unittest.TestCase):
    def test_four_forty_minute_exams_keep_durations_and_three_transitions(self):
        result = summary([row(h) for h in ["08:30", "09:30", "10:30", "11:30"]])
        gaps = result["stored_duration_pairs"]
        self.assertEqual(gaps["same_clinic_pairs"], 3)
        self.assertEqual(gaps["nonnegative_gap_minutes"], 60)
        self.assertEqual(gaps["theoretical_slack_in_blocks_minutes"], 45)
        self.assertEqual(result["occupied_union_minutes"], 160)
        self.assertEqual(result["first_to_last_span_minutes"], 220)
        self.assertEqual(result["density_within_first_to_last_span_percent"], 72.727)

    def test_nested_overlaps_exclude_all_affected_pairs_and_union_never_double_counts(self):
        result = summary([row("08:00", 120), row("09:00", 30), row("09:45", 30), row("10:30", 40)])
        gaps = result["stored_duration_pairs"]
        self.assertEqual(gaps["events_in_any_overlap"], 3)
        self.assertEqual(gaps["eligible_pairs_excluding_overlap_events"], 0)
        self.assertEqual(gaps["theoretical_slack_in_blocks_minutes"], 0)
        self.assertEqual(result["occupied_union_minutes"], 175)

    def test_another_clinic_between_events_prevents_false_same_clinic_pair(self):
        gaps = summary([row("08:00", clinic=1), row("09:00", clinic=2), row("10:00", clinic=1)])["stored_duration_pairs"]
        self.assertEqual(gaps["same_clinic_pairs"], 0)

    def test_block_accounts_for_missing_transitions_instead_of_summing_fragments(self):
        gaps = summary([row("08:00"), row("08:40"), row("09:40")])["stored_duration_pairs"]
        self.assertEqual(gaps["fragmented_excess_above_transition_minutes"], 15)
        self.assertEqual(gaps["theoretical_slack_in_blocks_minutes"], 10)

    def test_catalog_is_only_conservative_sensitivity_not_rewritten_history(self):
        result = summary([row("08:00", 20, catalogo_min=40), row("08:30", 20, catalogo_min=40)])
        self.assertEqual(result["occupied_union_minutes"], 40)
        self.assertEqual(result["stored_duration_pairs"]["nonnegative_gap_minutes"], 10)
        self.assertEqual(result["conservative_current_catalog_sensitivity"]["events_in_any_overlap"], 2)
        self.assertEqual(result["conservative_current_catalog_sensitivity"]["theoretical_slack_in_blocks_minutes"], 0)

    def test_cancelled_expired_and_absent_records_are_not_capacity_or_realized(self):
        rows = [row("08:00"), row("09:00", status="Cancelado"), row("10:00", status="Faltou"),
                row("11:00", status="Expirado"), row("12:00", status="Reservado", reserva_expira_em=AS_OF - timedelta(hours=1))]
        result = summary(rows)
        self.assertEqual(result["records"], 5)
        self.assertEqual(result["active_records_at_snapshot"], 1)
        self.assertEqual(result["performed_status_records_started_before_snapshot"], 1)
        self.assertEqual(result["expired_reservations_excluded"], 1)

    def test_missing_duration_does_not_get_a_fabricated_thirty_minute_end_or_bridge(self):
        result = summary([row("08:00"), row("09:00", fim=None), row("10:00")])
        self.assertEqual(result["duration_missing_active_records"], 1)
        self.assertEqual(result["stored_duration_pairs"]["same_clinic_pairs_missing_duration"], 2)
        self.assertEqual(result["stored_duration_pairs"]["eligible_pairs_excluding_overlap_events"], 0)
        self.assertEqual(result["valid_duration_days_for_density"], 0)
        self.assertIsNone(result["density_within_first_to_last_span_percent"])

    def test_display_time_is_used_but_persisted_duration_remains_authoritative(self):
        result = summary([row("08:00", hora="09:00"), row("10:00")])
        self.assertEqual(result["display_vs_timestamp_mismatch_records"], 1)
        self.assertEqual(result["stored_duration_pairs"]["nonnegative_gap_minutes"], 20)
        self.assertEqual(result["occupied_union_minutes"], 80)

    def test_home_visits_or_unknown_origin_do_not_create_eligible_clinic_blocks(self):
        home = summary([row("08:00", origem_atendimento="domiciliar"), row("09:00", origem_atendimento="domiciliar")])
        self.assertEqual(home["stored_duration_pairs"]["same_clinic_pairs"], 0)
        unknown = summary([row("08:00", origem_atendimento=None), row("09:00")])
        self.assertEqual(unknown["unknown_origin_active_records"], 1)
        self.assertEqual(unknown["stored_duration_pairs"]["eligible_pairs_excluding_overlap_events"], 0)

    def test_future_bookings_do_not_become_observed_post_release_gain(self):
        result = m.make_report([row("08:00", day="2026-10-05", created_at=RELEASE + timedelta(minutes=1))], as_of=AS_OF, release=RELEASE)
        self.assertEqual(result["pre_comparison"]["start_inclusive"], "2026-08-31")
        self.assertEqual(result["pre_comparison"]["end_exclusive"], "2026-09-28")
        self.assertEqual(result["post_complete_weeks"]["records"], 0)
        self.assertEqual(result["post_complete_weeks"]["calendar_days"], 0)
        self.assertEqual(result["post_window_current_schedule"]["records"], 1)
        self.assertEqual(result["post_window_current_schedule"]["future_records_marked_performed_excluded"], 1)
        self.assertEqual(result["post_window_current_schedule"]["performed_status_records_started_before_snapshot"], 0)
        self.assertEqual(result["comparison"]["status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(result["comparison"]["differences_post_minus_pre"])
        self.assertIsNone(result["comparison"]["causal_gain"])

    def test_partial_week_is_excluded_and_four_complete_weeks_are_required(self):
        result = m.make_report([], as_of=datetime(2026, 10, 18, 23, tzinfo=m.LOCAL_TZ), release=RELEASE)
        self.assertEqual(result["method"]["complete_post_weeks"], 1)
        self.assertEqual(result["post_complete_weeks"]["end_exclusive"], "2026-10-12")
        self.assertIn("POST_WINDOW_INCOMPLETE", result["comparison"]["reasons"])

    def test_creation_time_requires_timezone_and_does_not_prove_engine_use(self):
        result = summary([row("08:00", created_at=datetime(2026, 10, 4, 20)), row("09:00", created_at=None, criado_em=None)])
        self.assertEqual(result["creation_timestamp_missing_or_naive_records"], 2)
        self.assertEqual(result["created_at_or_after_release_records"], 0)

    def test_report_does_not_serialize_identifiers_or_arbitrary_strings(self):
        result = m.make_report([row("08:00", clinic=987654321, paciente="PRIVATE_PET", tutor="PRIVATE_TUTOR", observacoes="PRIVATE_NOTES", status="PRIVATE_STATUS")], as_of=AS_OF, release=RELEASE)
        rendered = json.dumps(result)
        for private in ["987654321", "PRIVATE_PET", "PRIVATE_TUTOR", "PRIVATE_NOTES", "PRIVATE_STATUS", '"clinica_id"']:
            self.assertNotIn(private, rendered)

    def test_zero_transition_is_preserved(self):
        result = m.make_report([row("08:00"), row("09:00")], as_of=AS_OF, release=RELEASE, transition=0)
        self.assertEqual(result["reference_month"]["stored_duration_pairs"]["theoretical_slack_in_blocks_minutes"], 20)

    def test_project_identity_uses_host_or_pooler_username_not_password_or_query(self):
        self.assertTrue(m.database_identity_matches("postgresql://postgres:secret@db.expected.supabase.co/postgres", "expected"))
        self.assertTrue(m.database_identity_matches("postgresql://postgres.expected:secret@aws-0-region.pooler.supabase.com/postgres", "expected"))
        self.assertFalse(m.database_identity_matches("postgresql://postgres.other:expected@aws-0-region.pooler.supabase.com/postgres?ref=expected", "expected"))
        self.assertFalse(m.database_identity_matches("postgresql://postgres.expected:secret@evil.example/postgres", "expected"))

    def test_complete_small_sample_reports_only_descriptive_difference(self):
        rows = [row("08:00", day="2026-09-01"), row("09:00", day="2026-09-01"),
                row("08:00", day="2026-10-06", created_at=RELEASE + timedelta(hours=1)),
                row("08:45", day="2026-10-06", created_at=RELEASE + timedelta(hours=1))]
        result = m.make_report(rows, as_of=datetime(2026, 11, 2, 3, tzinfo=timezone.utc), release=RELEASE)
        self.assertEqual(result["comparison"]["status"], "DESCRIPTIVE_SMALL_SAMPLE")
        self.assertEqual(result["comparison"]["differences_post_minus_pre"]["stored_duration_primary"]["eligible_gap_mean_minutes"], -15)
        self.assertIsNone(result["comparison"]["causal_gain"])
        self.assertEqual(result["post_complete_weeks"]["conservative_current_catalog_sensitivity"]["eligible_pairs_both_created_at_or_after_release"], 1)

    def test_new_cancelled_record_does_not_count_as_post_created_active_exposure(self):
        result = summary([row("08:00", status="Cancelado", created_at=RELEASE + timedelta(minutes=1))])
        self.assertEqual(result["created_at_or_after_release_records"], 1)
        self.assertEqual(result["active_records_created_at_or_after_release"], 0)

    def test_catalog_changes_cannot_rewrite_primary_comparison(self):
        rows = [row("08:00", day="2026-09-01", duration=20, catalogo_min=40), row("09:00", day="2026-09-01"),
                row("08:00", day="2026-10-06"), row("09:00", day="2026-10-06")]
        result = m.make_report(rows, as_of=datetime(2026, 11, 2, 3, tzinfo=timezone.utc), release=RELEASE)
        delta = result["comparison"]["differences_post_minus_pre"]
        self.assertEqual(delta["stored_duration_primary"]["eligible_gap_mean_minutes"], -20)
        self.assertEqual(delta["current_catalog_sensitivity"]["eligible_gap_mean_minutes"], 0)

    def test_database_readonly_transaction_and_rollback_are_enforced_without_live_db(self):
        psycopg, extras, dotenv = MagicMock(), MagicMock(), MagicMock()
        dotenv.dotenv_values.return_value = {"DATABASE_URL": "postgresql://postgres:secret@db.expected.supabase.co/postgres"}
        conn = psycopg.connect.return_value
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"read_only": "on", "isolation": "repeatable read", "snapshot_at": AS_OF}
        cursor.fetchall.return_value = []
        with patch.dict(sys.modules, {"psycopg2": psycopg, "psycopg2.extras": extras, "dotenv": dotenv}):
            rows, metadata = m.read_postgres(Path("unused.env"), "expected", date(2026, 9, 1), date(2026, 10, 1))
        self.assertEqual(rows, [])
        self.assertEqual(metadata["read_only"], "on")
        conn.set_session.assert_called_once_with(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
        self.assertIn("default_transaction_read_only=on", psycopg.connect.call_args.kwargs["options"])
        self.assertTrue(all(call.args[0].strip().startswith("SELECT") for call in cursor.execute.call_args_list))
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_database_aborts_before_reading_records_if_readonly_not_confirmed(self):
        psycopg, extras, dotenv = MagicMock(), MagicMock(), MagicMock()
        dotenv.dotenv_values.return_value = {"DATABASE_URL": "postgresql://postgres:secret@db.expected.supabase.co/postgres"}
        conn = psycopg.connect.return_value
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"read_only": "off", "isolation": "repeatable read", "snapshot_at": AS_OF}
        with patch.dict(sys.modules, {"psycopg2": psycopg, "psycopg2.extras": extras, "dotenv": dotenv}):
            with self.assertRaisesRegex(ValueError, "READ_ONLY_REQUIRED"):
                m.read_postgres(Path("unused.env"), "expected", date(2026, 9, 1), date(2026, 10, 1))
        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
