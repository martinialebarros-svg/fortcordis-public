"""Private, versioned new-echo workspaces with no clinical record mutations."""

from sqlalchemy import text

VERSION = "20261101_105"
DESCRIPTION = "Rascunhos privados do editor de novos ecocardiogramas"


def upgrade(connection, dialect):
    from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest

    for model in (LaudoEditorDraft, LaudoEditorDraftRequest):
        model.__table__.create(connection, checkfirst=True)
        if dialect == "postgresql":
            table = model.__tablename__
            connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            connection.execute(text(f'REVOKE ALL ON "{table}" FROM PUBLIC'))
            for role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    connection.execute(text(f'REVOKE ALL ON "{table}" FROM "{role}"'))
