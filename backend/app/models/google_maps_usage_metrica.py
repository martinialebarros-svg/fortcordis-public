from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.db.database import Base


class GoogleMapsUsageMetrica(Base):
    __tablename__ = "google_maps_usage_metricas"
    __table_args__ = (
        Index("ix_google_maps_usage_metricas_created_at", "created_at"),
        Index("ix_google_maps_usage_metricas_service_created", "service", "created_at"),
        Index("ix_google_maps_usage_metricas_operation_created", "operation", "created_at"),
        Index(
            "ix_google_maps_usage_metricas_pair_created",
            "origem_clinica_id",
            "destino_clinica_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(40), nullable=False)
    operation = Column(String(80), nullable=False)
    provider = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="ok")
    origem_clinica_id = Column(Integer)
    destino_clinica_id = Column(Integer)
    perfil = Column(String(20))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
