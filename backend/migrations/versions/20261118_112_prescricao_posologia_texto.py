"""Allow a veterinarian to enter unstructured posology for a prescription item."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

VERSION = "20261118_112"
DESCRIPTION = "Adiciona posologia em texto corrido aos itens da receita"


def upgrade(connection: Connection, dialect: str) -> None:
    schema = inspect(connection)
    if not schema.has_table("prescricoes_itens"):
        return

    columns = {column["name"] for column in schema.get_columns("prescricoes_itens")}
    if "posologia_texto" not in columns:
        connection.execute(text("ALTER TABLE prescricoes_itens ADD COLUMN posologia_texto TEXT"))
