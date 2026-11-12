"""Correcoes administrativas preservam o registro original da mesclagem."""
from sqlalchemy import MetaData, Table, UniqueConstraint, inspect, select, text

VERSION = "20261027_104"
DESCRIPTION = "Historico privado de reversoes assistidas de mesclagem de tutores"


def upgrade(connection, dialect):
    if "tutores_mesclagens" not in inspect(connection).get_table_names():
        return
    quote = connection.dialect.identifier_preparer.quote
    constraints = [c for c in inspect(connection).get_unique_constraints("tutores_mesclagens")
                   if c["column_names"] == ["secundario_id"]]
    if dialect == "sqlite" and constraints:
        original = Table("tutores_mesclagens", MetaData(), autoload_with=connection)
        temporary = original.to_metadata(MetaData(), name="tutores_mesclagens_reversao_tmp")
        for constraint in list(temporary.constraints):
            if isinstance(constraint, UniqueConstraint) and [c.name for c in constraint.columns] == ["secundario_id"]:
                temporary.constraints.remove(constraint)
        temporary.indexes.clear()
        temporary.create(connection)
        names = [c.name for c in original.columns]
        connection.execute(temporary.insert().from_select(names, select(*original.c)))
        original.drop(connection)
        connection.execute(text("ALTER TABLE tutores_mesclagens_reversao_tmp RENAME TO tutores_mesclagens"))
        for index in original.indexes:
            if not (index.unique and [c.name for c in index.columns] == ["secundario_id"]):
                index.create(connection)
    else:
        for constraint in constraints:
            connection.execute(text(f'ALTER TABLE tutores_mesclagens DROP CONSTRAINT {quote(constraint["name"])}'))
    for index in inspect(connection).get_indexes("tutores_mesclagens"):
        if index.get("unique") and index.get("column_names") == ["secundario_id"]:
            connection.execute(text(f'DROP INDEX {quote(index["name"])}'))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tutores_mesclagens_secundario_id ON tutores_mesclagens (secundario_id)"))
    from app.models.tutor_mesclagem_reversao import TutorMesclagemReversao
    TutorMesclagemReversao.__table__.create(connection, checkfirst=True)
    if dialect == "postgresql":
        connection.execute(text("ALTER TABLE tutores_mesclagens_reversoes ENABLE ROW LEVEL SECURITY"))
        connection.execute(text("REVOKE ALL ON tutores_mesclagens_reversoes FROM PUBLIC"))
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.execute(text(f'REVOKE ALL ON tutores_mesclagens_reversoes FROM "{role}"'))
