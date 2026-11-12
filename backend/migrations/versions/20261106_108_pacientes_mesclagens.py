"""Fila privada, trilha de mesclagem e proteção dos códigos arquivados."""

from sqlalchemy import inspect, text

from app.models.paciente_mesclagem import PacienteMesclagem
from app.services.paciente_mesclagem_vinculos import PRESERVAR, TRANSFERIR

VERSION = "20261106_108"
DESCRIPTION = "Mesclagem administrativa de pacientes, fila e histórico"


def upgrade(connection, dialect):
    inspector = inspect(connection)
    if not inspector.has_table("pacientes"):
        return
    if "mesclado_em_id" not in {c["name"] for c in inspector.get_columns("pacientes")}:
        connection.execute(text("ALTER TABLE pacientes ADD COLUMN mesclado_em_id INTEGER"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_pacientes_mesclado_em ON pacientes (mesclado_em_id)"))
    PacienteMesclagem.__table__.create(connection, checkfirst=True)
    if dialect == "postgresql":
        _privacidade_postgres(connection)

    tables = set(inspector.get_table_names())
    for table, col in {**TRANSFERIR, **PRESERVAR}.items():
        if table not in tables or col not in {c["name"] for c in inspector.get_columns(table)}:
            continue
        # Supports both previews and the merge's narrowly scoped updates.
        if not any(i["column_names"][:1] == [col] for i in inspector.get_indexes(table)):
            connection.execute(text(f'CREATE INDEX IF NOT EXISTS ix_merge_{table}_paciente ON "{table}" ("{col}")'))
        if dialect == "postgresql":
            connection.execute(text(f'DROP TRIGGER IF EXISTS bloquear_codigo_mesclado ON "{table}"'))
            connection.execute(text(
                f'CREATE TRIGGER bloquear_codigo_mesclado BEFORE INSERT OR UPDATE OF "{col}" ON "{table}" '
                f"FOR EACH ROW EXECUTE FUNCTION proteger_vinculo_paciente_mesclado('{col}')"
            ))
        elif dialect == "sqlite":
            for event, suffix in (("INSERT", "ins"), (f'UPDATE OF "{col}"', "upd")):
                connection.execute(text(f"""
                    CREATE TRIGGER IF NOT EXISTS bloquear_codigo_mesclado_{table}_{suffix}
                    BEFORE {event} ON "{table}"
                    WHEN EXISTS (SELECT 1 FROM pacientes WHERE id = NEW."{col}" AND mesclado_em_id IS NOT NULL)
                    BEGIN SELECT RAISE(ABORT, 'Paciente mesclado: selecione o cadastro principal'); END
                """))

    if dialect == "postgresql":
        connection.execute(text("DROP TRIGGER IF EXISTS preservar_paciente_mesclado ON pacientes"))
        connection.execute(text("""
            CREATE TRIGGER preservar_paciente_mesclado BEFORE UPDATE OR DELETE ON pacientes
            FOR EACH ROW WHEN (OLD.mesclado_em_id IS NOT NULL)
            EXECUTE FUNCTION proteger_cadastro_paciente_mesclado()
        """))
    elif dialect == "sqlite":
        for event in ("UPDATE", "DELETE"):
            connection.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS preservar_paciente_mesclado_{event.lower()}
                BEFORE {event} ON pacientes WHEN OLD.mesclado_em_id IS NOT NULL
                {"AND (NEW.mesclado_em_id IS NOT OLD.mesclado_em_id OR NEW.ativo IS NOT 0)" if event == "UPDATE" else ""}
                BEGIN SELECT RAISE(ABORT, 'Cadastro de paciente mesclado e arquivado'); END
            """))


def _privacidade_postgres(connection):
    connection.execute(text("ALTER TABLE pacientes_mesclagens ENABLE ROW LEVEL SECURITY"))
    for role in ("PUBLIC", "anon", "authenticated"):
        if role == "PUBLIC" or connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).scalar():
            target = role if role == "PUBLIC" else f'"{role}"'
            connection.execute(text(f"REVOKE ALL ON pacientes_mesclagens FROM {target}"))
            connection.execute(text(f"REVOKE ALL ON SEQUENCE pacientes_mesclagens_id_seq FROM {target}"))
    # Sem SECURITY DEFINER. A tabela do paciente é sempre do schema do trigger.
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION proteger_vinculo_paciente_mesclado() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE destino integer;
        DECLARE paciente integer := (to_jsonb(NEW)->>TG_ARGV[0])::integer;
        BEGIN
          IF paciente IS NULL THEN RETURN NEW; END IF;
          EXECUTE format('SELECT mesclado_em_id FROM %I.pacientes WHERE id=$1 FOR SHARE', TG_TABLE_SCHEMA)
            INTO destino USING paciente;
          IF destino IS NOT NULL THEN
            RAISE EXCEPTION 'Paciente mesclado: selecione o cadastro principal' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """))
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION proteger_cadastro_paciente_mesclado() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.mesclado_em_id = OLD.mesclado_em_id AND NEW.ativo = 0 THEN RETURN NEW; END IF;
          END IF;
          RAISE EXCEPTION 'Cadastro de paciente mesclado e arquivado' USING ERRCODE='23514';
        END;
        $$
    """))
