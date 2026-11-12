"""Nomes deixam de ser identidade; mesclagens preservam proveniencia."""
from sqlalchemy import MetaData, Table, UniqueConstraint, inspect, select, text

VERSION = "20261027_102"
DESCRIPTION = "Permite tutores homonimos, identificacao pendente e mesclagem auditada"


def _nome_unico(columns):
    return list(columns or []) in (["nome"], ["nome_key"])


def _remover_unicidade_nome(connection, dialect):
    inspector = inspect(connection)
    constraints = [c for c in inspector.get_unique_constraints("tutores") if _nome_unico(c["column_names"])]
    quote = connection.dialect.identifier_preparer.quote
    if dialect == "sqlite" and constraints:
        # SQLite nao permite DROP CONSTRAINT: reconstruir preservando colunas,
        # defaults, PK e todos os indices que nao identificam pessoas pelo nome.
        original = Table("tutores", MetaData(), autoload_with=connection)
        temporary = original.to_metadata(MetaData(), name="tutores_identidade_tmp")
        for constraint in list(temporary.constraints):
            if isinstance(constraint, UniqueConstraint) and _nome_unico([c.name for c in constraint.columns]):
                temporary.constraints.remove(constraint)
        temporary.indexes.clear()
        temporary.create(connection)
        names = [c.name for c in original.columns]
        connection.execute(temporary.insert().from_select(names, select(*original.c)))
        original.drop(connection)
        connection.execute(text('ALTER TABLE tutores_identidade_tmp RENAME TO tutores'))
        for index in original.indexes:
            if not (index.unique and _nome_unico([c.name for c in index.columns])):
                index.create(connection)
    else:
        for constraint in constraints:
            connection.execute(text(f'ALTER TABLE tutores DROP CONSTRAINT {quote(constraint["name"])}'))

    for index in inspect(connection).get_indexes("tutores"):
        if index.get("unique") and _nome_unico(index.get("column_names")):
            connection.execute(text(f'DROP INDEX {quote(index["name"])}'))


def upgrade(connection, dialect):
    if "tutores" not in inspect(connection).get_table_names():
        return
    _remover_unicidade_nome(connection, dialect)
    columns = {c["name"] for c in inspect(connection).get_columns("tutores")}
    additions = {
        "identificacao_pendente": "BOOLEAN NOT NULL DEFAULT TRUE",
        "origem_cadastro": "TEXT",
        "identificacao_observacoes": "TEXT",
        "mesclado_em_id": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(text(f'ALTER TABLE tutores ADD COLUMN {name} {definition}'))
    connection.execute(text('CREATE INDEX IF NOT EXISTS ix_tutores_nome_busca ON tutores (nome_key)'))
    connection.execute(text('CREATE INDEX IF NOT EXISTS ix_tutores_mesclado_em_id ON tutores (mesclado_em_id)'))

    from app.models.tutor_mesclagem import TutorMesclagem
    TutorMesclagem.__table__.create(connection, checkfirst=True)
    if dialect == "postgresql":
        # Exclusivamente backend autenticado. Nenhuma policy concede acesso
        # direto a snapshots pessoais pela Data API.
        connection.execute(text('ALTER TABLE tutores_mesclagens ENABLE ROW LEVEL SECURITY'))
        connection.execute(text('REVOKE ALL ON tutores_mesclagens FROM PUBLIC'))
        for role in ("anon", "authenticated"):
            if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {"role": role}).scalar():
                connection.execute(text(f'REVOKE ALL ON tutores_mesclagens FROM "{role}"'))
