from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.db.database import Base


class PortalClinicTrustedDevice(Base):
    """Computador da recepcao conectado ao portal em modo laudos, sem senha.

    Existe em tabela propria, e nao dentro de `portal_clinic_sessions`, porque
    aquela e presa a uma conta com senha (`account_id` e NOT NULL) e todo o
    caminho de refresh confere o status dessa conta. Uma confianca nascida do
    link de laudo nao tem conta nenhuma - encaixa-la la obrigaria a espalhar
    guardas de "conta pode ser nula" por todo o servico de autenticacao.

    Ver docs/specs/portal-clinica-dispositivo-confiavel/.
    """

    __tablename__ = "portal_clinic_trusted_devices"

    id = Column(Integer, primary_key=True, index=True)
    clinica_id = Column(Integer, nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    device_label = Column(String(120), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    # Como a confianca nasceu. Hoje so "exam_link"; o campo existe para que um
    # caminho futuro (ex.: o gerente marcando a maquina apos login com senha)
    # seja distinguivel na auditoria e na revogacao.
    origin = Column(String(20), nullable=False, default="exam_link")
    # Link de laudo que originou a confianca. Revogar aquele link revoga esta
    # confianca junto: se o link vazou, o que ele gerou morre com ele.
    origin_exam_link_id = Column(Integer, nullable=True, index=True)
    scope_json = Column(Text, nullable=False, default="[]")
    status = Column(String(20), nullable=False, default="active", index=True)
    # Prazo de inatividade: cada uso empurra para frente (ver rotate_and_renew).
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
