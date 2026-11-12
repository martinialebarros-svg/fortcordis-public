"""Private editing workspaces; independent of issued clinical documents."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.database import Base


class LaudoEditorDraft(Base):
    __tablename__ = "laudo_editor_drafts"
    __table_args__ = (
        UniqueConstraint("owner_id", "draft_id", name="uq_laudo_editor_draft_owner_uuid"),
    )

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    draft_id = Column(String(36), nullable=False)
    context_key = Column(String(200), nullable=False)
    revision = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class LaudoEditorDraftRequest(Base):
    """Small idempotency receipts, without a second copy of clinical content."""

    __tablename__ = "laudo_editor_draft_requests"
    __table_args__ = (
        UniqueConstraint("draft_row_id", "request_id", name="uq_laudo_editor_draft_request"),
    )

    id = Column(Integer, primary_key=True)
    draft_row_id = Column(Integer, ForeignKey("laudo_editor_drafts.id"), nullable=False, index=True)
    request_id = Column(String(36), nullable=False)
    operation = Column(String(10), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
