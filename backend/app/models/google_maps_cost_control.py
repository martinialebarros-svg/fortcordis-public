"""Durable cost control. No addresses, payloads, API keys or bearer tokens are stored."""
from sqlalchemy import BigInteger, Column, Index, Integer, String, Text

from app.db.database import Base


class GoogleMapsCostConfig(Base):
    __tablename__ = "google_maps_cost_config"
    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    config_json = Column(Text, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    updated_by = Column(Integer)


class GoogleMapsCostAction(Base):
    __tablename__ = "google_maps_cost_actions"
    id = Column(String(64), primary_key=True)
    token_hash = Column(String(64), unique=True)
    user_id = Column(Integer)
    fingerprint = Column(String(64), nullable=False)
    action = Column(String(80), nullable=False)
    policy = Column(String(80))
    revision = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False)
    max_calls = Column(Integer, nullable=False)
    max_cost_micros = Column(BigInteger, nullable=False)
    used_calls = Column(Integer, nullable=False, default=0)
    used_cost_micros = Column(BigInteger, nullable=False, default=0)
    skus_json = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    claimed_at = Column(BigInteger)


class GoogleMapsCostEvent(Base):
    __tablename__ = "google_maps_cost_events"
    __table_args__ = (
        Index("ix_google_maps_cost_events_month", "month", "kind"),
        Index("ix_google_maps_cost_events_day", "day", "kind"),
        Index("ix_google_maps_cost_events_created", "created_at"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String(64))
    action = Column(String(80), nullable=False)
    user_id = Column(Integer)
    policy = Column(String(80))
    sku = Column(String(40))
    kind = Column(String(20), nullable=False)
    reason = Column(String(80))
    calls = Column(Integer, nullable=False, default=0)
    estimated_cost_micros = Column(BigInteger, nullable=False, default=0)
    day = Column(String(10), nullable=False)
    month = Column(String(7), nullable=False)
    created_at = Column(BigInteger, nullable=False)


COST_TABLES = (
    GoogleMapsCostConfig.__table__,
    GoogleMapsCostAction.__table__,
    GoogleMapsCostEvent.__table__,
)
