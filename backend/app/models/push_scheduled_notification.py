from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class PushScheduledNotification(Base):
    __tablename__ = "push_scheduled_notifications"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(40), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    user_id = Column(Integer, nullable=True, index=True)
    module = Column(String(40), nullable=True)
    action = Column(String(80), nullable=True)
    resource_type = Column(String(40), nullable=True)
    resource_id = Column(Integer, nullable=True, index=True)
    title = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    priority = Column(String(12), nullable=True)
    payload_json = Column(Text, nullable=True)
    source_notification_id = Column(String(64), nullable=True)
    snooze_minutes = Column(Integer, nullable=True)
    send_at = Column(DateTime(timezone=True), nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
