from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.database import Base


PORTAL_PARTNER_TYPE_CLINICA = "clinica"
PORTAL_PARTNER_TYPE_VETERINARIO = "veterinario"


class PortalPartnerProfile(Base):
    __tablename__ = "portal_partner_profiles"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(20), nullable=False, index=True)
    clinica_id = Column(Integer, nullable=True, unique=True, index=True)
    nome_exibicao = Column(String(255), nullable=False)
    email_login = Column(String(255), nullable=True, index=True)
    telefone = Column(String(50), nullable=True)
    whatsapp = Column(String(50), nullable=True)
    cidade_base = Column(String(120), nullable=True)
    estado_base = Column(String(20), nullable=True)
    crmv = Column(String(80), nullable=True)
    cpf_documento = Column(String(40), nullable=True)
    area_atuacao = Column(String(120), nullable=True)
    observacoes = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class PortalPartnerClinicLink(Base):
    """Clinicas em que um veterinario parceiro atende.

    `receber_todos_laudos` liga a difusao: todo laudo daquela clinica passa a
    liberar e avisar esse veterinario, sem precisar nomea-lo no laudo. Desligado,
    o vinculo so ordena o seletor de veterinario do fluxo de laudo.
    """

    __tablename__ = "portal_partner_clinic_links"
    __table_args__ = (
        UniqueConstraint("partner_id", "clinica_id", name="uq_portal_partner_clinic_link"),
    )

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    clinica_id = Column(Integer, nullable=False, index=True)
    receber_todos_laudos = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class PortalPartnerReleaseTarget(Base):
    __tablename__ = "portal_partner_release_targets"
    __table_args__ = (
        UniqueConstraint("partner_id", "exame_id", name="uq_portal_partner_release_partner_exam"),
    )

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, nullable=False, index=True)
    exame_id = Column(Integer, nullable=False, index=True)
    laudo_id = Column(Integer, nullable=True, index=True)
    permitir_download = Column(Boolean, nullable=False, default=True)
    released_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    downloaded_at = Column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_by_user_id = Column(Integer, nullable=True, index=True)
    contexto_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
