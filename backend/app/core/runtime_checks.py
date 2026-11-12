from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.database import engine
from app.services.laudo_pdf_jobs import get_laudo_pdf_storage_dir
from app.services.runtime_observability import (
    get_http_5xx_monitor_status,
    get_http_latency_monitor_status,
)
from app.services.upload_dedupe_cleanup_service import (
    get_upload_dedupe_cleanup_worker_runtime_state,
)
from app.services.push_scheduler_service import get_push_scheduler_worker_runtime_state
from app.services.whatsapp_reminder_scheduler_service import (
    get_whatsapp_reminder_scheduler_worker_runtime_state,
)
from app.services.whatsapp_bot_worker_service import get_whatsapp_bot_worker_runtime_state
from app.services.assistente_ia_autonomy import get_assistant_scheduler_worker_runtime_state
from app.services.tesseract_runtime import resolve_tesseract_command
from migrations.runner import get_migration_status

_PLACEHOLDER_SECRET_KEYS = {"", "change-me", "changeme", "secret", "default"}
_MIN_SECRET_KEY_LENGTH = 32


def _is_production_environment() -> bool:
    env = str(
        settings.APP_ENV
        or os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("ENV")
        or os.getenv("FASTAPI_ENV")
        or ""
    ).strip().lower()
    return env in {"prod", "production"}


def _check_database() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"connected": True, "status": "connected", "error": None}
    except Exception as exc:
        return {"connected": False, "status": "disconnected", "error": str(exc)}


def _check_secret_key() -> dict[str, Any]:
    secret = str(settings.SECRET_KEY or "").strip()
    strong = len(secret) >= _MIN_SECRET_KEY_LENGTH and secret.lower() not in _PLACEHOLDER_SECRET_KEYS

    warning = None
    if not secret:
        warning = "SECRET_KEY ausente."
    elif secret.lower() in _PLACEHOLDER_SECRET_KEYS:
        warning = "SECRET_KEY usa valor padrao ou inseguro."
    elif len(secret) < _MIN_SECRET_KEY_LENGTH:
        warning = f"SECRET_KEY curta (< {_MIN_SECRET_KEY_LENGTH} caracteres)."

    return {
        "configured": bool(secret),
        "strong": strong,
        "warning": warning,
    }


def _check_migrations() -> dict[str, Any]:
    fallback = {
        "tracking_table_exists": False,
        "discovered_count": 0,
        "applied_count": 0,
        "current_version": None,
        "latest_version": None,
        "pending_versions": [],
        "pending_count": 0,
        "unknown_applied_versions": [],
        "descriptions": {},
        "warnings": [],
        "error": None,
    }

    try:
        status = get_migration_status()
    except Exception as exc:
        fallback["warnings"] = [f"Falha ao inspecionar migracoes: {exc}"]
        fallback["error"] = str(exc)
        return fallback

    warnings: list[str] = []
    if not status.get("tracking_table_exists"):
        warnings.append("Tabela schema_migrations ausente; nao e possivel confirmar o schema aplicado.")
    if int(status.get("pending_count") or 0) > 0:
        warnings.append(f"{status['pending_count']} migracao(oes) pendente(s).")
    if status.get("unknown_applied_versions"):
        warnings.append("Existem versoes aplicadas que nao estao no codigo atual.")

    status["warnings"] = warnings
    status["error"] = None
    return status


def _check_eco_study_ocr() -> dict[str, Any]:
    command = resolve_tesseract_command()
    resolved = command if os.path.isabs(command) else shutil.which(command)
    if not resolved:
        return {
            "available": False,
            "command": command,
            "version": None,
            "languages": [],
            "language_count": 0,
            "required_languages": ["por", "eng"],
            "missing_languages": ["por", "eng"],
            "error": "Comando Tesseract nao encontrado.",
        }

    try:
        version_result = subprocess.run(
            [resolved, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=5,
            text=True,
        )
        language_result = subprocess.run(
            [resolved, "--list-langs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=5,
            text=True,
        )
    except Exception as exc:
        return {
            "available": False,
            "command": resolved,
            "version": None,
            "languages": [],
            "language_count": 0,
            "required_languages": ["por", "eng"],
            "missing_languages": ["por", "eng"],
            "error": str(exc),
        }

    version_line = (version_result.stdout or "").splitlines()
    languages = sorted(
        line.strip()
        for line in (language_result.stdout or "").splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    )
    missing_languages = [language for language in ("por", "eng") if language not in languages]
    required_languages_available = [
        language for language in ("por", "eng") if language in languages
    ]
    available = version_result.returncode == 0 and language_result.returncode == 0
    return {
        "available": available,
        "command": resolved,
        "version": version_line[0].strip() if version_line else None,
        "languages": required_languages_available,
        "language_count": len(languages),
        "required_languages": ["por", "eng"],
        "missing_languages": missing_languages,
        "error": None if available else "Falha ao consultar o Tesseract.",
    }


def build_runtime_report() -> dict[str, Any]:
    database = _check_database()
    migrations = _check_migrations()
    secret_key = _check_secret_key()
    http_5xx_monitor = get_http_5xx_monitor_status()
    http_latency_monitor = get_http_latency_monitor_status()
    upload_cleanup_worker = get_upload_dedupe_cleanup_worker_runtime_state()
    push_scheduler_worker = get_push_scheduler_worker_runtime_state()
    whatsapp_reminder_scheduler_worker = get_whatsapp_reminder_scheduler_worker_runtime_state()
    whatsapp_bot_worker = get_whatsapp_bot_worker_runtime_state()
    assistant_scheduler_worker = get_assistant_scheduler_worker_runtime_state()
    eco_study_ocr = _check_eco_study_ocr()
    workers_run_in_this_process = settings.FORTCORDIS_PROCESS_ROLE != "api"

    warnings: list[str] = []
    if not database["connected"]:
        warnings.append("Banco indisponivel para consultas de saude.")
    warnings.extend(migrations.get("warnings") or [])
    if secret_key["warning"]:
        warnings.append(secret_key["warning"])
    for monitor_warning in http_5xx_monitor.get("config_warnings") or []:
        warnings.append(f"Monitor runtime 5xx: {monitor_warning}")
    for monitor_warning in http_latency_monitor.get("config_warnings") or []:
        warnings.append(f"Monitor runtime latencia: {monitor_warning}")
    if http_5xx_monitor.get("alert_active"):
        warnings.append(
            "Alerta operacional: "
            f"{http_5xx_monitor.get('recent_5xx_count', 0)} erro(s) HTTP 5xx "
            f"nos ultimos {http_5xx_monitor.get('window_minutes')} minuto(s)."
        )
    if workers_run_in_this_process:
        if upload_cleanup_worker.get("status") == "invalid_config":
            warnings.append(
                "Worker de auto-cleanup dedupe com configuracao invalida: "
                f"{upload_cleanup_worker.get('config_error')}"
            )
        elif upload_cleanup_worker.get("enabled") and not upload_cleanup_worker.get("thread_alive"):
            warnings.append("Worker de auto-cleanup dedupe habilitado, mas inativo.")
        if push_scheduler_worker.get("enabled") and not push_scheduler_worker.get("thread_alive"):
            warnings.append("Worker de push agendado habilitado, mas inativo.")
        if whatsapp_reminder_scheduler_worker.get("enabled") and not whatsapp_reminder_scheduler_worker.get("thread_alive"):
            warnings.append("Worker de lembrete automatico do WhatsApp habilitado, mas inativo.")
        if whatsapp_bot_worker.get("enabled") and not whatsapp_bot_worker.get("thread_alive"):
            warnings.append("Worker do bot de atendimento do WhatsApp habilitado, mas inativo.")
        if assistant_scheduler_worker.get("enabled") and not assistant_scheduler_worker.get("thread_alive"):
            warnings.append("Worker de missoes da Mente habilitado, mas inativo.")
    if not eco_study_ocr.get("available"):
        warnings.append("OCR de estudos indisponivel: Tesseract nao encontrado ou inacessivel.")
    elif eco_study_ocr.get("missing_languages"):
        warnings.append(
            "OCR de estudos sem idiomas obrigatorios: "
            + ", ".join(eco_study_ocr["missing_languages"])
        )

    startup_enforced_issues: list[str] = []
    if (
        settings.ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION
        and _is_production_environment()
        and not secret_key["strong"]
    ):
        startup_enforced_issues.append(
            "APP_ENV=production exige SECRET_KEY forte e nao padrao."
        )

    if settings.REQUIRE_STRONG_SECRET_KEY and not secret_key["strong"]:
        startup_enforced_issues.append(
            "REQUIRE_STRONG_SECRET_KEY ativo, mas a SECRET_KEY nao atende ao minimo esperado."
        )
    if settings.REQUIRE_UP_TO_DATE_MIGRATIONS:
        if not migrations.get("tracking_table_exists"):
            startup_enforced_issues.append(
                "REQUIRE_UP_TO_DATE_MIGRATIONS ativo, mas schema_migrations nao existe."
            )
        elif int(migrations.get("pending_count") or 0) > 0:
            startup_enforced_issues.append(
                "REQUIRE_UP_TO_DATE_MIGRATIONS ativo, com migracoes pendentes."
            )

    readiness_issues = list(startup_enforced_issues)
    if not database["connected"]:
        readiness_issues.insert(0, "Banco indisponivel.")

    laudo_pdf_jobs_dir = None
    try:
        laudo_pdf_jobs_dir = get_laudo_pdf_storage_dir()
    except Exception as exc:
        warnings.append(f"Diretorio de PDFs assincronos indisponivel: {exc}")

    return {
        "status": "healthy" if database["connected"] else "unhealthy",
        "ready": len(readiness_issues) == 0,
        "database": database,
        "migrations": migrations,
        "security": {
            "secret_key": secret_key,
        },
        "compatibility_modes": {
            "allow_permission_matrix_fallback": bool(settings.ALLOW_PERMISSION_MATRIX_FALLBACK),
            "allow_legacy_plain_passwords": bool(settings.ALLOW_LEGACY_PLAIN_PASSWORDS),
        },
        "environment": {
            "app_env": str(settings.APP_ENV or "").strip() or "development",
            "is_production": _is_production_environment(),
            "process_role": settings.FORTCORDIS_PROCESS_ROLE,
            "background_workers_managed_externally": not workers_run_in_this_process,
            "enforce_strong_secret_key_in_production": bool(
                settings.ENFORCE_STRONG_SECRET_KEY_IN_PRODUCTION
            ),
        },
        "integrations": {
            "google_maps_configured": bool(str(settings.GOOGLE_MAPS_API_KEY or "").strip()),
            "web_push_configured": bool(
                str(settings.WEB_PUSH_VAPID_PUBLIC_KEY or "").strip()
                and str(settings.WEB_PUSH_VAPID_PRIVATE_KEY or "").strip()
            ),
            "upload_dir": settings.UPLOAD_DIR,
            "laudo_pdf_jobs_dir": laudo_pdf_jobs_dir,
            "eco_study_ocr": eco_study_ocr,
        },
        "observability": {
            "http_5xx_monitor": http_5xx_monitor,
            "http_latency_monitor": http_latency_monitor,
            "upload_dedupe_cleanup_worker": upload_cleanup_worker,
            "push_scheduler_worker": push_scheduler_worker,
            "whatsapp_reminder_scheduler_worker": whatsapp_reminder_scheduler_worker,
            "whatsapp_bot_worker": whatsapp_bot_worker,
            "assistant_scheduler_worker": assistant_scheduler_worker,
        },
        "warnings": warnings,
        "startup_enforced_issues": startup_enforced_issues,
        "readiness_issues": readiness_issues,
    }


def validate_startup_or_raise() -> dict[str, Any]:
    report = build_runtime_report()

    for warning in report["warnings"]:
        print(f"[startup-check] WARN: {warning}")
    for issue in report["startup_enforced_issues"]:
        print(f"[startup-check] ERROR: {issue}")

    if report["startup_enforced_issues"]:
        raise RuntimeError(" | ".join(report["startup_enforced_issues"]))

    return report
