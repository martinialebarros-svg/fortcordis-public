"""Premissas administrativas isoladas dos registros operacionais."""
from sqlalchemy import Column, DateTime, Integer, Text

from app.db.database import Base


class GestaoPremissas(Base):
    __tablename__ = "gestao_premissas"

    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    contexto_json = Column(Text, nullable=False)
    values_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    updated_by_id = Column(Integer, nullable=False)
