"""Create generic external partner portal tables with clinic backfill."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260729_57"
DESCRIPTION = "Cria parceiros externos do portal e faz backfill das clinicas parceiras"

PORTAL_PARTNER_TYPE_CLINICA = "clinica"
PORTAL_RELEASED_STATUS = "Liberado no portal"


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _columns_for(inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _create_table(connection: Connection, dialect: str, *, name: str, postgresql_sql: str, sqlite_sql: str) -> None:
    inspector = inspect(connection)
    if _table_exists(inspector, name):
        return
    connection.execute(text(postgresql_sql if dialect == "postgresql" else sqlite_sql))


def _normalize_text(value: Any) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


def _normalize_email(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if value in (False, 0):
        return False
    text_value = str(value).strip().lower()
    if text_value in {"", "false", "f", "0", "nao", "não", "no"}:
        return False
    return True


def _load_context_email(raw_context: Any) -> str | None:
    try:
        payload = json.loads(raw_context or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _normalize_email(payload.get("account_email"))


def _backfill_clinic_partner_profiles(connection: Connection) -> None:
    inspector = inspect(connection)
    if not _table_exists(inspector, "clinicas") or not _table_exists(inspector, "portal_partner_profiles"):
        return

    account_email_by_clinic: dict[int, str] = {}
    if _table_exists(inspector, "portal_clinic_accounts"):
        rows = connection.execute(
            text(
                """
                SELECT clinica_id, email_normalized, status, id
                FROM portal_clinic_accounts
                ORDER BY id DESC
                """
            )
        ).mappings()
        for row in rows:
            clinic_id = row.get("clinica_id")
            if clinic_id in (None, ""):
                continue
            clinic_id = int(clinic_id)
            email = _normalize_email(row.get("email_normalized"))
            status_value = str(row.get("status") or "").strip().lower()
            if clinic_id not in account_email_by_clinic and email and status_value != "revoked":
                account_email_by_clinic[clinic_id] = email

    invite_email_by_clinic: dict[int, str] = {}
    if _table_exists(inspector, "portal_clinic_invites"):
        rows = connection.execute(
            text(
                """
                SELECT clinica_id, contexto_json, id
                FROM portal_clinic_invites
                ORDER BY id DESC
                """
            )
        ).mappings()
        for row in rows:
            clinic_id = row.get("clinica_id")
            if clinic_id in (None, ""):
                continue
            clinic_id = int(clinic_id)
            email = _load_context_email(row.get("contexto_json"))
            if clinic_id not in invite_email_by_clinic and email:
                invite_email_by_clinic[clinic_id] = email

    clinic_rows = connection.execute(
        text(
            """
            SELECT id, nome, email, telefone, cidade, estado, observacoes, ativo
            FROM clinicas
            """
        )
    ).mappings()

    existing_by_clinic = {
        int(row["clinica_id"]): int(row["id"])
        for row in connection.execute(
            text(
                """
                SELECT id, clinica_id
                FROM portal_partner_profiles
                WHERE tipo = :tipo
                  AND clinica_id IS NOT NULL
                """
            ),
            {"tipo": PORTAL_PARTNER_TYPE_CLINICA},
        ).mappings()
        if row.get("clinica_id") is not None
    }

    for row in clinic_rows:
        clinic_id = int(row["id"])
        payload = {
            "tipo": PORTAL_PARTNER_TYPE_CLINICA,
            "clinica_id": clinic_id,
            "nome_exibicao": _normalize_text(row.get("nome")) or f"Clinica {clinic_id}",
            "email_login": account_email_by_clinic.get(clinic_id)
            or invite_email_by_clinic.get(clinic_id)
            or _normalize_email(row.get("email")),
            "telefone": _normalize_text(row.get("telefone")),
            "whatsapp": _normalize_text(row.get("telefone")),
            "cidade_base": _normalize_text(row.get("cidade")),
            "estado_base": _normalize_text(row.get("estado")),
            "observacoes": _normalize_text(row.get("observacoes")),
            "ativo": _normalize_bool(row.get("ativo"), default=True),
        }

        if clinic_id in existing_by_clinic:
            connection.execute(
                text(
                    """
                    UPDATE portal_partner_profiles
                    SET nome_exibicao = :nome_exibicao,
                        email_login = COALESCE(:email_login, email_login),
                        telefone = COALESCE(:telefone, telefone),
                        whatsapp = COALESCE(:whatsapp, whatsapp),
                        cidade_base = COALESCE(:cidade_base, cidade_base),
                        estado_base = COALESCE(:estado_base, estado_base),
                        observacoes = COALESCE(:observacoes, observacoes),
                        ativo = :ativo
                    WHERE clinica_id = :clinica_id
                      AND tipo = :tipo
                    """
                ),
                payload,
            )
            continue

        connection.execute(
            text(
                """
                INSERT INTO portal_partner_profiles (
                    tipo,
                    clinica_id,
                    nome_exibicao,
                    email_login,
                    telefone,
                    whatsapp,
                    cidade_base,
                    estado_base,
                    observacoes,
                    ativo
                ) VALUES (
                    :tipo,
                    :clinica_id,
                    :nome_exibicao,
                    :email_login,
                    :telefone,
                    :whatsapp,
                    :cidade_base,
                    :estado_base,
                    :observacoes,
                    :ativo
                )
                """
            ),
            payload,
        )


def _exam_release_rows(connection: Connection, inspector) -> list[dict[str, Any]]:
    if not _table_exists(inspector, "exames"):
        return []

    has_laudos = _table_exists(inspector, "laudos")
    has_atendimentos = _table_exists(inspector, "atendimentos_clinicos")

    if has_laudos and has_atendimentos:
        rows = connection.execute(
            text(
                """
                SELECT
                    e.id AS exame_id,
                    e.laudo_id AS laudo_id,
                    e.data_resultado AS released_at,
                    l.clinic_id AS laudo_clinica_id,
                    ac.clinica_id AS atendimento_clinica_id
                FROM exames e
                LEFT JOIN laudos l ON l.id = e.laudo_id
                LEFT JOIN atendimentos_clinicos ac ON ac.id = e.atendimento_id
                WHERE TRIM(COALESCE(e.status, '')) = :released_status
                """
            ),
            {"released_status": PORTAL_RELEASED_STATUS},
        ).mappings()
    elif has_laudos:
        rows = connection.execute(
            text(
                """
                SELECT
                    e.id AS exame_id,
                    e.laudo_id AS laudo_id,
                    e.data_resultado AS released_at,
                    l.clinic_id AS laudo_clinica_id,
                    NULL AS atendimento_clinica_id
                FROM exames e
                LEFT JOIN laudos l ON l.id = e.laudo_id
                WHERE TRIM(COALESCE(e.status, '')) = :released_status
                """
            ),
            {"released_status": PORTAL_RELEASED_STATUS},
        ).mappings()
    elif has_atendimentos:
        rows = connection.execute(
            text(
                """
                SELECT
                    e.id AS exame_id,
                    e.laudo_id AS laudo_id,
                    e.data_resultado AS released_at,
                    NULL AS laudo_clinica_id,
                    ac.clinica_id AS atendimento_clinica_id
                FROM exames e
                LEFT JOIN atendimentos_clinicos ac ON ac.id = e.atendimento_id
                WHERE TRIM(COALESCE(e.status, '')) = :released_status
                """
            ),
            {"released_status": PORTAL_RELEASED_STATUS},
        ).mappings()
    else:
        rows = connection.execute(
            text(
                """
                SELECT
                    e.id AS exame_id,
                    e.laudo_id AS laudo_id,
                    e.data_resultado AS released_at,
                    NULL AS laudo_clinica_id,
                    NULL AS atendimento_clinica_id
                FROM exames e
                WHERE TRIM(COALESCE(e.status, '')) = :released_status
                """
            ),
            {"released_status": PORTAL_RELEASED_STATUS},
        ).mappings()

    return [dict(row) for row in rows]


def _backfill_partner_release_targets(connection: Connection) -> None:
    inspector = inspect(connection)
    if not _table_exists(inspector, "portal_partner_profiles") or not _table_exists(
        inspector, "portal_partner_release_targets"
    ):
        return

    partner_by_clinic = {
        int(row["clinica_id"]): int(row["id"])
        for row in connection.execute(
            text(
                """
                SELECT id, clinica_id
                FROM portal_partner_profiles
                WHERE tipo = :tipo
                  AND clinica_id IS NOT NULL
                """
            ),
            {"tipo": PORTAL_PARTNER_TYPE_CLINICA},
        ).mappings()
        if row.get("clinica_id") is not None
    }

    existing_pairs = {
        (int(row["partner_id"]), int(row["exame_id"]))
        for row in connection.execute(
            text("SELECT partner_id, exame_id FROM portal_partner_release_targets")
        ).mappings()
    }

    for row in _exam_release_rows(connection, inspector):
        exame_id = row.get("exame_id")
        if exame_id in (None, ""):
            continue
        clinic_id = row.get("laudo_clinica_id") or row.get("atendimento_clinica_id")
        if clinic_id in (None, ""):
            continue
        partner_id = partner_by_clinic.get(int(clinic_id))
        if partner_id is None:
            continue
        pair = (partner_id, int(exame_id))
        if pair in existing_pairs:
            continue
        context_json = json.dumps(
            {
                "migrated_from": "clinic_portal_release",
                "legacy_clinica_id": int(clinic_id),
                "migration_version": VERSION,
            },
            ensure_ascii=False,
        )
        connection.execute(
            text(
                """
                INSERT INTO portal_partner_release_targets (
                    partner_id,
                    exame_id,
                    laudo_id,
                    permitir_download,
                    released_at,
                    contexto_json
                ) VALUES (
                    :partner_id,
                    :exame_id,
                    :laudo_id,
                    :permitir_download,
                    COALESCE(:released_at, CURRENT_TIMESTAMP),
                    :contexto_json
                )
                """
            ),
            {
                "partner_id": partner_id,
                "exame_id": int(exame_id),
                "laudo_id": row.get("laudo_id"),
                "permitir_download": True,
                "released_at": row.get("released_at"),
                "contexto_json": context_json,
            },
        )
        existing_pairs.add(pair)


def upgrade(connection: Connection, dialect: str) -> None:
    _create_table(
        connection,
        dialect,
        name="portal_partner_profiles",
        postgresql_sql="""
            CREATE TABLE portal_partner_profiles (
                id SERIAL PRIMARY KEY,
                tipo VARCHAR(20) NOT NULL,
                clinica_id INTEGER NULL UNIQUE,
                nome_exibicao VARCHAR(255) NOT NULL,
                email_login VARCHAR(255) NULL,
                telefone VARCHAR(50) NULL,
                whatsapp VARCHAR(50) NULL,
                cidade_base VARCHAR(120) NULL,
                estado_base VARCHAR(20) NULL,
                crmv VARCHAR(80) NULL,
                cpf_documento VARCHAR(40) NULL,
                area_atuacao VARCHAR(120) NULL,
                observacoes TEXT NULL,
                ativo BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NULL
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_partner_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                clinica_id INTEGER NULL UNIQUE,
                nome_exibicao TEXT NOT NULL,
                email_login TEXT NULL,
                telefone TEXT NULL,
                whatsapp TEXT NULL,
                cidade_base TEXT NULL,
                estado_base TEXT NULL,
                crmv TEXT NULL,
                cpf_documento TEXT NULL,
                area_atuacao TEXT NULL,
                observacoes TEXT NULL,
                ativo BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL
            )
        """,
    )

    _create_table(
        connection,
        dialect,
        name="portal_partner_release_targets",
        postgresql_sql="""
            CREATE TABLE portal_partner_release_targets (
                id SERIAL PRIMARY KEY,
                partner_id INTEGER NOT NULL,
                exame_id INTEGER NOT NULL,
                laudo_id INTEGER NULL,
                permitir_download BOOLEAN NOT NULL DEFAULT TRUE,
                released_at TIMESTAMP NOT NULL DEFAULT NOW(),
                revoked_at TIMESTAMP NULL,
                created_by_user_id INTEGER NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NULL,
                CONSTRAINT uq_portal_partner_release_partner_exam UNIQUE (partner_id, exame_id)
            )
        """,
        sqlite_sql="""
            CREATE TABLE portal_partner_release_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                exame_id INTEGER NOT NULL,
                laudo_id INTEGER NULL,
                permitir_download BOOLEAN NOT NULL DEFAULT 1,
                released_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME NULL,
                created_by_user_id INTEGER NULL,
                contexto_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL,
                CONSTRAINT uq_portal_partner_release_partner_exam UNIQUE (partner_id, exame_id)
            )
        """,
    )

    indexes = [
        ("ix_portal_partner_profiles_tipo", "portal_partner_profiles", "tipo"),
        ("ix_portal_partner_profiles_clinica_id", "portal_partner_profiles", "clinica_id"),
        ("ix_portal_partner_profiles_email_login", "portal_partner_profiles", "email_login"),
        ("ix_portal_partner_profiles_ativo", "portal_partner_profiles", "ativo"),
        ("ix_portal_partner_release_targets_partner_id", "portal_partner_release_targets", "partner_id"),
        ("ix_portal_partner_release_targets_exame_id", "portal_partner_release_targets", "exame_id"),
        ("ix_portal_partner_release_targets_laudo_id", "portal_partner_release_targets", "laudo_id"),
        ("ix_portal_partner_release_targets_released_at", "portal_partner_release_targets", "released_at"),
        ("ix_portal_partner_release_targets_revoked_at", "portal_partner_release_targets", "revoked_at"),
    ]
    for index_name, table_name, column_name in indexes:
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))

    _backfill_clinic_partner_profiles(connection)
    _backfill_partner_release_targets(connection)
