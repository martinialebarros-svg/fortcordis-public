"""Enable RLS on public Supabase tables and reduce Data API exposure."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

VERSION = "20260430_32"
DESCRIPTION = "Habilita RLS em tabelas publicas e reduz grants da Data API Supabase"


def upgrade(connection: Connection, dialect: str) -> None:
    if dialect != "postgresql":
        return

    rows = connection.execute(
        text(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
    ).fetchall()

    preparer = connection.dialect.identifier_preparer
    for row in rows:
        table_name = str(row[0])
        qualified_table = f"public.{preparer.quote(table_name)}"
        connection.execute(
            text(f"ALTER TABLE IF EXISTS {qualified_table} ENABLE ROW LEVEL SECURITY")
        )

    role_rows = connection.execute(
        text(
            """
            SELECT rolname
            FROM pg_roles
            WHERE rolname IN ('anon', 'authenticated')
            ORDER BY rolname
            """
        )
    ).fetchall()
    data_api_roles = [preparer.quote(str(row[0])) for row in role_rows]
    if not data_api_roles:
        connection.execute(text("NOTIFY pgrst, 'reload schema'"))
        return

    role_list = ", ".join(data_api_roles)

    # The app talks to the database through the FastAPI backend, not Supabase's
    # browser-facing Data API. Keep direct backend access intact while removing
    # broad anon/authenticated grants from PostgREST.
    connection.execute(
        text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role_list}")
    )
    connection.execute(
        text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role_list}")
    )
    connection.execute(
        text(f"REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM {role_list}")
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE ALL ON TABLES FROM {role_list}"
        )
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE ALL ON SEQUENCES FROM {role_list}"
        )
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE EXECUTE ON FUNCTIONS FROM {role_list}"
        )
    )
    connection.execute(text("NOTIFY pgrst, 'reload schema'"))
