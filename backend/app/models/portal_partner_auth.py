from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class PortalPartnerInvite(Base):
    __tablename__ = "portal_partner_invites"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    delivery_channel = Column(String(20), nullable=False, default="whatsapp")
    delivery_target_masked = Column(String(255), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, nullable=True, index=True)
    contexto_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PortalPartnerAccount(Base):
    __tablename__ = "portal_partner_accounts"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    email_normalized = Column(String(255), nullable=False, unique=True, index=True)
    responsavel_nome = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False, default="pending_verification", index=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    force_mfa_on_next_login = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class PortalPartnerSession(Base):
    __tablename__ = "portal_partner_sessions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    device_label = Column(String(255), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    trusted_until = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class PortalPartnerPasswordResetToken(Base):
    __tablename__ = "portal_partner_password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PortalPartnerAuthChallenge(Base):
    __tablename__ = "portal_partner_auth_challenges"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(String(64), nullable=False, unique=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    challenge_type = Column(String(40), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    failed_attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    contexto_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
