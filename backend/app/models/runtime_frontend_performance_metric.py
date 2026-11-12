from sqlalchemy import Column, DateTime, Float, Index, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class RuntimeFrontendPerformanceMetric(Base):
    """Amostra RUM agregavel, sem URL completa, usuario ou dado de negocio."""

    __tablename__ = "runtime_frontend_performance_metrics"
    __table_args__ = (
        Index("ix_runtime_frontend_performance_created_at", "created_at"),
        Index(
            "ix_runtime_frontend_performance_route_release_created",
            "route_group",
            "release_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    route_group = Column(String(40), nullable=False)
    release_id = Column(String(80), nullable=False, default="unknown")
    navigation_type = Column(String(16), nullable=False)
    outcome = Column(String(16), nullable=False)
    shell_ms = Column(Float, nullable=False)
    content_ms = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
