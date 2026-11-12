from collections.abc import Mapping
from typing import Any

import time

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings


class ObservedQueuePool(QueuePool):
    """QueuePool que contabiliza espera apenas se houver requisicao monitorada."""

    def _do_get(self):
        started_at = time.perf_counter()
        try:
            return super()._do_get()
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            # Import tardio evita ciclo entre configuracao do banco e runtime.
            from app.services.runtime_observability import record_database_pool_wait

            record_database_pool_wait(elapsed_ms)


def build_database_engine_options(
    database_url: str,
    database_settings: Any = settings,
) -> Mapping[str, Any]:
    """Retorna opcoes de engine seguras para o dialeto configurado.

    SQLite e usado em testes e desenvolvimento local; os limites do QueuePool
    PostgreSQL nao se aplicam a ele. Para PostgreSQL, cada processo da API tem
    capacidade limitada, detecta sockets descartados antes do uso e deixa de
    esperar em tempo finito quando o pool ou a conexao externa degradarem.
    """

    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    return {
        "connect_args": {
            "connect_timeout": database_settings.DATABASE_CONNECT_TIMEOUT_SECONDS,
        },
        "pool_pre_ping": database_settings.DATABASE_POOL_PRE_PING,
        "pool_size": database_settings.DATABASE_POOL_SIZE,
        "max_overflow": database_settings.DATABASE_MAX_OVERFLOW,
        "pool_timeout": database_settings.DATABASE_POOL_TIMEOUT_SECONDS,
        "pool_recycle": database_settings.DATABASE_POOL_RECYCLE_SECONDS,
        "poolclass": ObservedQueuePool,
    }


def create_database_engine(
    database_url: str,
    database_settings: Any = settings,
):
    return create_engine(
        database_url,
        **build_database_engine_options(database_url, database_settings),
    )


engine = create_database_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _record_query_started(_connection, _cursor, _statement, _parameters, context, _executemany):
    context._fortcordis_query_started_at = time.perf_counter()


def _record_query_finished(_connection, _cursor, _statement, _parameters, context, _executemany):
    started_at = getattr(context, "_fortcordis_query_started_at", None)
    if started_at is None:
        return
    from app.services.runtime_observability import record_database_query_duration

    record_database_query_duration((time.perf_counter() - started_at) * 1000.0)


def _record_query_failed(exception_context):
    context = getattr(exception_context, "execution_context", None)
    started_at = getattr(context, "_fortcordis_query_started_at", None)
    if started_at is None:
        return
    from app.services.runtime_observability import record_database_query_duration

    record_database_query_duration((time.perf_counter() - started_at) * 1000.0)


event.listen(engine, "before_cursor_execute", _record_query_started)
event.listen(engine, "after_cursor_execute", _record_query_finished)
event.listen(engine, "handle_error", _record_query_failed)

def get_db():
    db = SessionLocal()
    try:
        # Lazy import avoids the database/cost boundary initialization cycle.
        from app.services.google_maps_cost_control import agenda_business_session
        with agenda_business_session(db):
            yield db
    finally:
        db.close()
