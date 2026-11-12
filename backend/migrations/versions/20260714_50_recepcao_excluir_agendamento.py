"""Grant appointment-delete permission to reception role aliases."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20260714_50"
DESCRIPTION = "Libera exclusao de agendamentos para os papeis de recepcao"


def upgrade(connection: Connection, dialect: str) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "papeis" not in tables or "papeis_permissoes" not in tables:
        return

    papel_ids = connection.execute(
        text(
            "SELECT id FROM papeis "
            "WHERE LOWER(TRIM(nome)) IN "
            "('secretaria', 'secretária', 'recepcao', 'recepção')"
        )
    ).scalars().all()

    for papel_id in papel_ids:
        permissao_id = connection.execute(
            text(
                "SELECT id FROM papeis_permissoes "
                "WHERE papel_id = :papel_id AND modulo = 'agenda'"
            ),
            {"papel_id": papel_id},
        ).scalar_one_or_none()

        if permissao_id is None:
            connection.execute(
                text(
                    "INSERT INTO papeis_permissoes "
                    "(papel_id, modulo, visualizar, editar, excluir) "
                    "VALUES (:papel_id, 'agenda', 1, 1, 1)"
                ),
                {"papel_id": papel_id},
            )
            continue

        connection.execute(
            text(
                "UPDATE papeis_permissoes "
                "SET excluir = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :permissao_id"
            ),
            {"permissao_id": permissao_id},
        )
