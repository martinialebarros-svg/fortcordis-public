import os
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "background-worker-isolation-test-secret-key-1234567890")

from app import main  # noqa: E402
from app.core import runtime_checks  # noqa: E402
from app.services import background_workers  # noqa: E402


_START_CALLS = (
    "start_atendimento_assistente_worker",
    "restart_incomplete_laudo_pdf_jobs",
    "restart_incomplete_xml_import_jobs",
    "restart_incomplete_eco_study_import_jobs",
    "restart_incomplete_ai_echo_sessions",
    "start_upload_dedupe_cleanup_worker",
    "start_push_scheduler_worker",
    "start_whatsapp_reminder_scheduler_worker",
    "start_whatsapp_bot_worker",
    "start_assistant_scheduler_worker",
    "start_ai_echo_cleanup_worker",
)

_SHUTDOWN_CALLS = (
    "shutdown_atendimento_assistente_worker",
    "shutdown_laudo_pdf_jobs",
    "shutdown_xml_import_jobs",
    "shutdown_eco_study_import_jobs",
    "shutdown_upload_dedupe_cleanup_worker",
    "shutdown_push_scheduler_worker",
    "shutdown_whatsapp_reminder_scheduler_worker",
    "shutdown_whatsapp_bot_worker",
    "shutdown_assistant_scheduler_worker",
    "shutdown_ai_echo_cleanup_worker",
)


class BackgroundWorkerLifecycleTest(unittest.TestCase):
    def _patched_calls(self, names: tuple[str, ...]) -> ExitStack:
        stack = ExitStack()
        for name in names:
            stack.enter_context(patch.object(background_workers, name))
        return stack

    def test_start_background_workers_starts_every_registered_job(self) -> None:
        with self._patched_calls(_START_CALLS):
            background_workers.start_background_workers()
            for name in _START_CALLS:
                getattr(background_workers, name).assert_called_once_with()

    def test_shutdown_background_workers_stops_every_registered_job(self) -> None:
        with self._patched_calls(_SHUTDOWN_CALLS):
            background_workers.shutdown_background_workers()
            for name in _SHUTDOWN_CALLS:
                getattr(background_workers, name).assert_called_once_with()

    def test_dedicated_process_validates_then_starts_and_stops_workers(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        with patch.object(background_workers, "validate_startup_or_raise") as validate:
            with patch.object(background_workers, "start_background_workers") as start:
                with patch.object(background_workers, "shutdown_background_workers") as shutdown:
                    background_workers.run_background_worker(
                        stop_event=stop_event,
                        register_signal_handlers=False,
                    )

        validate.assert_called_once_with()
        start.assert_called_once_with()
        shutdown.assert_called_once_with()


class ApiProcessRoleTest(unittest.TestCase):
    def test_agenda_schema_compatibility_uses_one_startup_session(self) -> None:
        with patch.object(main, "SessionLocal") as session_factory:
            with patch.object(
                main.agenda,
                "_ensure_agendamento_workflow_columns",
            ) as ensure_columns:
                main._ensure_agenda_schema_compat()

        db = session_factory.return_value
        ensure_columns.assert_called_once_with(db)
        db.close.assert_called_once_with()

    def test_agenda_schema_compatibility_closes_session_on_failure(self) -> None:
        with patch.object(main, "SessionLocal") as session_factory:
            with patch.object(
                main.agenda,
                "_ensure_agendamento_workflow_columns",
                side_effect=RuntimeError("schema desatualizado"),
            ):
                with self.assertRaisesRegex(RuntimeError, "schema desatualizado"):
                    main._ensure_agenda_schema_compat()

        session_factory.return_value.close.assert_called_once_with()

    def test_api_role_does_not_start_or_stop_background_workers(self) -> None:
        with patch.object(main.settings, "FORTCORDIS_PROCESS_ROLE", "api"):
            with patch.object(main, "_ensure_financeiro_schema_compat"):
                with patch.object(main, "_ensure_agenda_schema_compat"):
                    with patch.object(main, "validate_startup_or_raise"):
                        with patch.object(main, "start_background_workers") as start:
                            with patch.object(main, "shutdown_background_worker_services") as shutdown:
                                main.startup_schema_compatibility()
                                main.shutdown_background_workers()

        start.assert_not_called()
        shutdown.assert_not_called()

    def test_all_role_preserves_local_worker_lifecycle(self) -> None:
        with patch.object(main.settings, "FORTCORDIS_PROCESS_ROLE", "all"):
            with patch.object(main, "_ensure_financeiro_schema_compat"):
                with patch.object(main, "_ensure_agenda_schema_compat"):
                    with patch.object(main, "validate_startup_or_raise"):
                        with patch.object(main, "start_background_workers") as start:
                            with patch.object(main, "shutdown_background_worker_services") as shutdown:
                                main.startup_schema_compatibility()
                                main.shutdown_background_workers()

        start.assert_called_once_with()
        shutdown.assert_called_once_with()

    def test_api_role_marks_workers_as_external_without_local_thread_warning(self) -> None:
        inactive_worker = {"enabled": True, "status": "stopped", "thread_alive": False}
        with ExitStack() as stack:
            stack.enter_context(patch.object(runtime_checks.settings, "FORTCORDIS_PROCESS_ROLE", "api"))
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "_check_database",
                    return_value={"connected": True, "status": "connected", "error": None},
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "_check_migrations",
                    return_value={"tracking_table_exists": True, "pending_count": 0, "warnings": []},
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "_check_secret_key",
                    return_value={"configured": True, "strong": True, "warning": None},
                )
            )
            stack.enter_context(
                patch.object(runtime_checks, "get_http_5xx_monitor_status", return_value={"config_warnings": []})
            )
            stack.enter_context(
                patch.object(runtime_checks, "get_http_latency_monitor_status", return_value={"config_warnings": []})
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "get_upload_dedupe_cleanup_worker_runtime_state",
                    return_value=inactive_worker,
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "get_push_scheduler_worker_runtime_state",
                    return_value=inactive_worker,
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "get_whatsapp_reminder_scheduler_worker_runtime_state",
                    return_value=inactive_worker,
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "get_whatsapp_bot_worker_runtime_state",
                    return_value=inactive_worker,
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "get_assistant_scheduler_worker_runtime_state",
                    return_value=inactive_worker,
                )
            )
            stack.enter_context(
                patch.object(
                    runtime_checks,
                    "_check_eco_study_ocr",
                    return_value={"available": True, "missing_languages": []},
                )
            )
            stack.enter_context(patch.object(runtime_checks, "get_laudo_pdf_storage_dir", return_value="/tmp/jobs"))
            report = runtime_checks.build_runtime_report()

        self.assertTrue(report["environment"]["background_workers_managed_externally"])
        self.assertNotIn("Worker de", " | ".join(report["warnings"]))
