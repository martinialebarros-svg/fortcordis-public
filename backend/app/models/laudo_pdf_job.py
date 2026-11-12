from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class LaudoPdfJob(Base):
    __tablename__ = "laudo_pdf_jobs"

    id = Column(Integer, primary_key=True, index=True)
    laudo_id = Column(Integer, nullable=False, index=True)
    requested_by_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    cache_key = Column(String(64), nullable=False, index=True)

    arquivo_nome = Column(String(255))
    arquivo_caminho = Column(String(500))
    erro = Column(Text)
    tentativas = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
