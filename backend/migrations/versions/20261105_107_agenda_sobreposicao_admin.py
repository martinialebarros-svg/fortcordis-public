"""Excecao administrativa especifica, sem liberar os demais slots."""
from sqlalchemy import inspect, text

VERSION = "20261105_107"
DESCRIPTION = "Consentimento auditavel para sobreposicao administrativa da Agenda"


def upgrade(connection, dialect):
    inspector = inspect(connection)
    if "agendamentos" not in inspector.get_table_names():
        return
    if "excecao_sobreposicao" not in {c["name"] for c in inspector.get_columns("agendamentos")}:
        connection.execute(text("ALTER TABLE agendamentos ADD COLUMN excecao_sobreposicao TEXT"))
    if dialect != "postgresql":
        return
    # DDL transacional: se a nova exclusao falhar, a anterior permanece intacta.
    connection.execute(text("ALTER TABLE agendamentos DROP CONSTRAINT IF EXISTS ex_agendamentos_slot_ativo"))
    connection.execute(text("""
        ALTER TABLE agendamentos ADD CONSTRAINT ex_agendamentos_slot_ativo
        EXCLUDE USING gist (tstzrange(inicio, fim, '[)') WITH &&)
        WHERE (status IN ('Agendado', 'Reservado', 'Confirmado', 'Em atendimento')
               AND excecao_sobreposicao IS NULL)
    """))
    # Reutilizar a concessao num UPDATE SQL que move o slot tambem a revoga.
    # O backend fornece metadados novos somente apos revisar o novo conflito.
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION public.agenda_revogar_sobreposicao_obsoleta()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
        BEGIN
            IF OLD.excecao_sobreposicao IS NOT NULL
               AND NEW.excecao_sobreposicao IS NOT DISTINCT FROM OLD.excecao_sobreposicao
               AND (
                   ROW(NEW.inicio, NEW.fim, NEW.clinica_id, NEW.servico_id, NEW.origem_atendimento)
                   IS DISTINCT FROM
                   ROW(OLD.inicio, OLD.fim, OLD.clinica_id, OLD.servico_id, OLD.origem_atendimento)
                   OR ((NEW.origem_atendimento = 'domiciliar' OR OLD.origem_atendimento = 'domiciliar')
                       AND ROW(NEW.paciente_id, NEW.tutor_id) IS DISTINCT FROM ROW(OLD.paciente_id, OLD.tutor_id))
               ) THEN
                NEW.excecao_sobreposicao := NULL;
            END IF;
            RETURN NEW;
        END;
        $$
    """))
    connection.execute(text("DROP TRIGGER IF EXISTS agenda_revogar_sobreposicao ON agendamentos"))
    connection.execute(text("""
        CREATE TRIGGER agenda_revogar_sobreposicao BEFORE UPDATE ON agendamentos
        FOR EACH ROW EXECUTE FUNCTION public.agenda_revogar_sobreposicao_obsoleta()
    """))
