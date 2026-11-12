from sqlalchemy import Column, DateTime, Float, Index, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class RuntimeHttpLatencyMetric(Base):
    """Amostra agregada de performance, sem URL completa ou dados clinicos."""

    __tablename__ = "runtime_http_latency_metrics"
    __table_args__ = (
        Index("ix_runtime_http_latency_metrics_created_at", "created_at"),
        Index(
            "ix_runtime_http_latency_metrics_endpoint_release_created",
            "endpoint",
            "release_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String(120), nullable=False)
    release_id = Column(String(80), nullable=False, default="unknown")
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    database_ms = Column(Float, nullable=False, default=0.0)
    database_query_count = Column(Integer, nullable=False, default=0)
    pool_wait_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
