from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agenda_formalizacao import AgendaFormalizacaoInvite
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.services.portal_clinic_auth_service import generate_opaque_token, hash_secret
from app.services.whatsapp_agenda_service import (
    build_agenda_utility_template,
    normalize_whatsapp_number,
    send_agenda_utility_template,
)
from app.services.whatsapp_reminder_scheduler_service import _resolve_destination

INVITE_KIND = "agenda_formalizacao_invite"

STATUS_PENDING = "pending"
STATUS_USED = "used"
STATUS_EXPIRED = "expired"
STATUS_REVOKED = "revoked"

LOCAL_TZ = timezone(timedelta(hours=-3))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gerar_nome_key(nome: str | None) -> str:
    if not nome:
        return ""
    texto = unicodedata.normalize("NFKD", nome)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """Normaliza datetimes lidos do banco - SQLite descarta o tzinfo no

    round-trip mesmo em colunas `DateTime(timezone=True)`, enquanto o Postgres
    preserva; o valor persistido e sempre UTC nos dois casos.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _expire_if_needed(db: Session, invite: AgendaFormalizacaoInvite) -> bool:
    expires_at = _as_aware_utc(invite.expires_at)
    if expires_at is not None and expires_at <= _utcnow():
        if invite.status == STATUS_PENDING:
            invite.status = STATUS_EXPIRED
            db.commit()
        return True
    return False


def criar_ou_reutilizar_convite(db: Session, agendamento: Agendamento) -> tuple[AgendaFormalizacaoInvite, str]:
    """Emite um novo convite para a reserva, revogando qualquer pendente anterior.

    Convites so guardam o hash do token, nunca o valor bruto - por isso nao
    da pra "reaproveitar" o link de um convite pendente existente, so revogar
    e emitir outro.
    """
    pendente_anterior = (
        db.query(AgendaFormalizacaoInvite)
        .filter(
            AgendaFormalizacaoInvite.agendamento_id == agendamento.id,
            AgendaFormalizacaoInvite.status == STATUS_PENDING,
        )
        .order_by(AgendaFormalizacaoInvite.id.desc())
        .first()
    )
    if pendente_anterior is not None and not _expire_if_needed(db, pendente_anterior):
        pendente_anterior.status = STATUS_REVOKED
        pendente_anterior.revoked_at = _utcnow()
        db.commit()

    raw_token = generate_opaque_token()
    prazo_utc = _as_aware_utc(agendamento.reserva_expira_em)
    if prazo_utc is not None and prazo_utc > _utcnow():
        expires_at = prazo_utc
    else:
        default_hours = int(settings.AGENDA_FORMALIZACAO_INVITE_DEFAULT_HOURS or 72)
        expires_at = _utcnow() + timedelta(hours=max(1, default_hours))

    invite = AgendaFormalizacaoInvite(
        agendamento_id=agendamento.id,
        token_hash=hash_secret(INVITE_KIND, raw_token),
        status=STATUS_PENDING,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw_token


def build_formalizacao_url(raw_token: str) -> str:
    base_url = str(settings.PUBLIC_APP_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="URL publica do aplicativo nao configurada.")
    return f"{base_url}/agenda/formalizar/{raw_token}"


def obter_convite_valido(db: Session, raw_token: str) -> AgendaFormalizacaoInvite:
    token_hash = hash_secret(INVITE_KIND, raw_token)
    invite = (
        db.query(AgendaFormalizacaoInvite)
        .filter(AgendaFormalizacaoInvite.token_hash == token_hash)
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Link invalido ou nao encontrado.")
    _expire_if_needed(db, invite)
    if invite.status != STATUS_PENDING:
        detail = {
            STATUS_USED: "Este link ja foi utilizado.",
            STATUS_EXPIRED: "Este link expirou. Solicite um novo pela conversa do WhatsApp.",
            STATUS_REVOKED: "Este link nao esta mais disponivel. Solicite um novo pela conversa do WhatsApp.",
        }.get(invite.status, "Este link nao esta mais disponivel.")
        raise HTTPException(status_code=410, detail=detail)
    return invite


def obter_contexto_publico(db: Session, invite: AgendaFormalizacaoInvite) -> dict[str, Any]:
    agendamento = db.query(Agendamento).filter(Agendamento.id == invite.agendamento_id).first()
    if agendamento is None:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    clinica = db.query(Clinica).filter(Clinica.id == agendamento.clinica_id).first()
    inicio = agendamento.inicio
    inicio_local = inicio.astimezone(LOCAL_TZ) if inicio and inicio.tzinfo else inicio

    return {
        "clinica_nome": str((clinica.nome if clinica else None) or agendamento.clinica or "").strip(),
        "servico": str(agendamento.servico or "").strip(),
        "data": inicio_local.strftime("%d/%m/%Y") if inicio_local else "",
        "hora": inicio_local.strftime("%H:%M") if inicio_local else "",
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
    }


def _match_or_create_tutor(db: Session, *, nome: str, telefone: str) -> Tutor:
    nome_key = _gerar_nome_key(nome)
    tutor = Tutor(
        nome=nome,
        nome_key=nome_key,
        identificacao_pendente=True,
        origem_cadastro="Formalizacao de reserva",
        telefone=telefone,
        whatsapp=telefone,
        ativo=1,
    )
    db.add(tutor)
    db.flush()
    return tutor


def processar_submissao(
    db: Session,
    *,
    invite: AgendaFormalizacaoInvite,
    nome_paciente: str,
    nome_tutor: str,
    telefone_tutor: str,
) -> Agendamento:
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignora FOR UPDATE: reserve a escrita antes de ler o estado.
        db.execute(text("UPDATE agendamentos SET id=id WHERE id=:id"), {"id": invite.agendamento_id})
    agendamento = (
        db.query(Agendamento)
        .filter(Agendamento.id == invite.agendamento_id)
        .with_for_update()
        .first()
    )
    if agendamento is None:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")
    # O convite pode ter sido consumido enquanto esta requisicao aguardava o
    # lock do agendamento. Releia antes de criar outra pessoa ou outro animal.
    invite = (db.query(AgendaFormalizacaoInvite).filter(AgendaFormalizacaoInvite.id == invite.id)
              .populate_existing().with_for_update().first())
    if invite is None or invite.status != STATUS_PENDING:
        raise HTTPException(status_code=410, detail="Este link ja foi utilizado ou nao esta mais disponivel.")
    if invite.expires_at and _as_aware_utc(invite.expires_at) <= _utcnow():
        raise HTTPException(status_code=410, detail="Este link expirou. Solicite um novo pela conversa do WhatsApp.")

    if str(agendamento.status or "").strip() not in {"Reservado", "Agendado"}:
        raise HTTPException(status_code=409, detail="Este agendamento nao esta mais aguardando dados.")

    nome_paciente = nome_paciente.strip()[:200]
    nome_tutor = nome_tutor.strip()[:200]
    if not nome_paciente or not nome_tutor:
        raise HTTPException(
            status_code=422, detail="Preencha o nome do paciente e o primeiro nome do tutor."
        )
    telefone_tutor = normalize_whatsapp_number(telefone_tutor) if str(telefone_tutor or "").strip() else ""

    tutor = _match_or_create_tutor(db, nome=nome_tutor, telefone=telefone_tutor)
    db.flush()

    nome_key_paciente = _gerar_nome_key(nome_paciente)
    paciente = (
        db.query(Paciente)
        .filter(Paciente.tutor_id == tutor.id, Paciente.nome_key == nome_key_paciente,
                Paciente.mesclado_em_id.is_(None))
        .first()
    )
    if paciente is None:
        paciente = Paciente(
            nome=nome_paciente,
            nome_key=nome_key_paciente,
            tutor_id=tutor.id,
            especie=None,
            ativo=1,
        )
        db.add(paciente)
        db.flush()

    agendamento.paciente_id = paciente.id
    agendamento.tutor_id = tutor.id
    agendamento.paciente = nome_paciente
    agendamento.tutor = nome_tutor
    agendamento.telefone = telefone_tutor
    if agendamento.status == "Reservado":
        agendamento.status = "Agendado"

    invite.status = STATUS_USED
    invite.used_at = _utcnow()

    db.commit()
    db.refresh(agendamento)

    _tentar_notificar_formalizacao(db, agendamento)

    return agendamento


def _tentar_notificar_formalizacao(db: Session, agendamento: Agendamento) -> None:
    """Avisa a clinica que o agendamento foi formalizado - best-effort, nunca

    bloqueia o salvamento dos dados do paciente/tutor caso o envio falhe.
    """
    try:
        destino = _resolve_destination(db, agendamento, "clinica")
        if not destino:
            return
        template = build_agenda_utility_template(
            db,
            agendamento=agendamento,
            destination=destino,
            recipient_type="clinica",
            template_key="appointmentFormalized",
        )
        send_agenda_utility_template(
            agendamento_id=agendamento.id,
            template=template,
            idempotency_key=f"agendamento-formalizado-{agendamento.id}",
        )
    except Exception:
        pass
