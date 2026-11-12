from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class EcoStudyImportJob(Base):
    __tablename__ = "eco_study_import_jobs"

    id = Column(Integer, primary_key=True, index=True)
    requested_by_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)

    arquivo_nome = Column(String(255))
    arquivo_tipo = Column(String(100))
    arquivo_caminho = Column(String(500))
    conteudo_hash = Column(String(64), index=True)
    resultado_json = Column(Text)
    erro = Column(Text)
    tentativas = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
