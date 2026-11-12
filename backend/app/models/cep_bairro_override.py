from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.db.database import Base


class CepBairroOverride(Base):
    __tablename__ = "cep_bairro_overrides"
    __table_args__ = (
        UniqueConstraint("cep", name="uq_cep_bairro_overrides_cep"),
    )

    id = Column(Integer, primary_key=True, index=True)
    cep = Column(String(8), nullable=False)
    bairro = Column(String(255), nullable=False)
    cidade = Column(String(255))
    estado = Column(String(10))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

