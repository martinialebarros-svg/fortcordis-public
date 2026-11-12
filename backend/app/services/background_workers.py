"""Ciclo de vida dos trabalhos que nao devem disputar o processo web.

O papel ``all`` continua util para desenvolvimento e testes. Nos ambientes
gerenciados, a API usa ``FORTCORDIS_PROCESS_ROLE=api`` e esta rotina e iniciada
por uma unidade systemd separada com o papel ``worker``.
"""

from __future__ import annotations

import logging
import signal
import threading
from typing import Optional

from app.core.runtime_checks import validate_startup_or_raise
from app.services.ai_echo_service import (
    restart_incomplete_ai_echo_sessions,
    shutdown_ai_echo_cleanup_worker,
    start_ai_echo_cleanup_worker,
)
from app.services.assistente_ia_autonomy import (
    shutdown_assistant_scheduler_worker,
    start_assistant_scheduler_worker,
)
from app.services.eco_study_import_jobs import (
    restart_incomplete_eco_study_import_jobs,
    shutdown_eco_study_import_jobs,
)
from app.services.laudo_pdf_jobs import (
    restart_incomplete_laudo_pdf_jobs,
    shutdown_laudo_pdf_jobs,
)
from app.services.push_scheduler_service import (
    shutdown_push_scheduler_worker,
    start_push_scheduler_worker,
)
from app.services.upload_dedupe_cleanup_service import (
    shutdown_upload_dedupe_cleanup_worker,
    start_upload_dedupe_cleanup_worker,
)
from app.services.whatsapp_bot_worker_service import (
    shutdown_whatsapp_bot_worker,
    start_whatsapp_bot_worker,
)
from app.services.whatsapp_reminder_scheduler_service import (
    shutdown_whatsapp_reminder_scheduler_worker,
    start_whatsapp_reminder_scheduler_worker,
)
from app.services.xml_import_jobs import (
    restart_incomplete_xml_import_jobs,
    shutdown_xml_import_jobs,
)

from app.services.atendimento_assistente_lotes import start_atendimento_assistente_worker, shutdown_atendimento_assistente_worker

logger = logging.getLogger(__name__)


def start_background_workers() -> None:
    """Retoma filas persistidas e inicia os agendadores em segundo plano."""

    start_atendimento_assistente_worker()
    restart_incomplete_laudo_pdf_jobs()
    restart_incomplete_xml_import_jobs()
    restart_incomplete_eco_study_import_jobs()
    restart_incomplete_ai_echo_sessions()
    start_upload_dedupe_cleanup_worker()
    start_push_scheduler_worker()
    start_whatsapp_reminder_scheduler_worker()
    start_whatsapp_bot_worker()
    start_assistant_scheduler_worker()
    start_ai_echo_cleanup_worker()


def shutdown_background_workers() -> None:
    """Solicita parada ordenada dos executores e agendadores locais."""

    shutdown_atendimento_assistente_worker()
    shutdown_laudo_pdf_jobs()
    shutdown_xml_import_jobs()
    shutdown_eco_study_import_jobs()
    shutdown_upload_dedupe_cleanup_worker()
    shutdown_push_scheduler_worker()
    shutdown_whatsapp_reminder_scheduler_worker()
    shutdown_whatsapp_bot_worker()
    shutdown_assistant_scheduler_worker()
    shutdown_ai_echo_cleanup_worker()


def run_background_worker(
    *,
    stop_event: Optional[threading.Event] = None,
    register_signal_handlers: bool = True,
) -> None:
    """Mantem o processo worker ativo ate receber SIGTERM ou SIGINT."""

    requested_stop = stop_event or threading.Event()

    if register_signal_handlers:
        def request_stop(_signal_number: int, _frame: object) -> None:
            logger.info("Sinal de parada recebido pelo processo de workers.")
            requested_stop.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    validate_startup_or_raise()
    start_background_workers()
    logger.info("Processo de workers do FortCordis iniciado.")
    try:
        requested_stop.wait()
    finally:
        shutdown_background_workers()
        logger.info("Processo de workers do FortCordis finalizado.")


def main() -> None:
    run_background_worker()


if __name__ == "__main__":
    main()
