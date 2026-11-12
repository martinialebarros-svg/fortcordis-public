from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class WhatsappAgendaResposta(Base):
    __tablename__ = "whatsapp_agenda_respostas"

    id = Column(Integer, primary_key=True, index=True)
    provider_message_id = Column(String(160), nullable=False, unique=True, index=True)
    outbound_message_id = Column(String(160), nullable=True, index=True)
    agendamento_id = Column(Integer, nullable=True, index=True)
    action = Column(String(40), nullable=False)
    from_phone = Column(String(32), nullable=False)
    result = Column(String(80), nullable=False)
    result_json = Column(Text, nullable=False, default="{}")
    processed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
