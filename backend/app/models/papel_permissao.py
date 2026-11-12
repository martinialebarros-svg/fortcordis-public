from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.database import Base


class PapelPermissao(Base):
    __tablename__ = "papeis_permissoes"
    __table_args__ = (
        UniqueConstraint("papel_id", "modulo", name="uq_papeis_permissoes_papel_modulo"),
    )

    id = Column(Integer, primary_key=True, index=True)
    papel_id = Column(Integer, ForeignKey("papeis.id"), nullable=False, index=True)
    modulo = Column(String(80), nullable=False, index=True)
    visualizar = Column(Integer, nullable=False, default=1)
    editar = Column(Integer, nullable=False, default=0)
    excluir = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    papel = relationship("Papel")
