from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.portal_security import (
    PORTAL_DOWNLOAD_TOKEN_HEADER,
    PortalDownloadContext,
    PortalSessionContext,
    create_portal_download_token,
    create_portal_session_token,
    get_current_portal_download_token,
    get_current_portal_session,
)
from app.core.portal_release import (
    PORTAL_RELEASED_EXAM_STATUSES,
    PORTAL_RELEASED_LAUDO_STATUSES,
    is_portal_released_status,
)
from app.api.v1.endpoints.agenda import _adquirir_lock_escrita_agenda
from app.api.v1.endpoints.ordens_servico import (
    _carregar_dados_emissor_recibo_empresa,
    _gerar_pdf_recibos_ordens,
    _montar_recibos_os,
)
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.portal_access import PortalAccessChallenge
from app.models.portal_clinic_auth import PortalClinicAccount
from app.services.portal_clinic_exam_link_service import (
    register_link_open,
    resolve_active_link,
)
from app.services.portal_clinic_device_trust_service import (
    DEVICE_TRUST_SCOPE,
    clear_device_cookie,
    create_trust,
    get_device_cookie,
    resolve_active_trust,
    revoke_trust,
    rotate_and_renew,
    set_device_cookie,
    user_agent_matches,
)
from app.services.portal_clinic_notification_service import notify_clinic_device_trusted
from app.models.portal_partner import PortalPartnerProfile, PortalPartnerReleaseTarget
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.schemas.portal import (
    PortalChallengeResponse,
    PortalClinicOperationalItemResponse,
    PortalClinicOperationalSummaryResponse,
    PortalClinicaAgendamentoCancelResponse,
    PortalClinicaAgendamentoItemResponse,
    PortalClinicaAgendamentoListResponse,
    PortalClinicaFinanceiroResponse,
    PortalClinicaFinanceiroSummaryResponse,
    PortalClinicaOrdemServicoItemResponse,
    PortalClinicaSessionLinkRequest,
    PortalCodeVerifyRequest,
    PortalDeviceTrustEndResponse,
    PortalDeviceTrustRequest,
    PortalDeviceTrustResponse,
    PortalDownloadLinkItemResponse,
    PortalDownloadUrlResponse,
    PortalExamAttachmentResponse,
    PortalExamLinkResponse,
    PortalExamListResponse,
    PortalExamSummaryResponse,
    PortalTokenResponse,
    PortalTutorSessionLinkRequest,
)
from app.services.alerta_interno_service import criar_alerta_interno
from app.services.attachment_download_service import (
    attachment_has_download_source,
    build_attachment_download_response,
)
from app.services.auditoria_service import registrar_auditoria
from app.services.portal_delivery_service import (
    PortalChallengeDeliveryRequest,
    PortalDeliveryError,
    send_portal_access_code,
)

router = APIRouter()
logger = logging.getLogger(__name__)
PORTAL_LOCAL_TZ = timezone(timedelta(hours=-3))

PORTAL_CHALLENGE_STATUS_PENDING = "pending"
PORTAL_CHALLENGE_STATUS_CONSUMED = "consumed"
PORTAL_CHALLENGE_STATUS_EXPIRED = "expired"
PORTAL_CHALLENGE_STATUS_LOCKED = "locked"
PORTAL_SCOPE_TUTOR = ["pet:read", "exam:read", "exam:download"]
PORTAL_SCOPE_CLINICA = ["clinic:read", "exam:read", "exam:download"]
PORTAL_SCOPE_PARTNER = ["partner:read", "exam:read", "exam:download"]

# Permissoes conferidas de fato pelos endpoints (ver _assert_portal_scope).
# `clinic:read` cobre o que e gestao da unidade - agenda, financeiro e recibo.
# Exame liberado e download ficam em `exam:*`, que toda sessao do portal carrega.
PORTAL_PERMISSION_CLINIC_READ = "clinic:read"
PORTAL_PERMISSION_EXAM_READ = "exam:read"
PORTAL_PERMISSION_EXAM_DOWNLOAD = "exam:download"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits


def _json_dump(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_load_dict(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _json_load_list(value: str | None) -> list[str]:
    try:
        loaded = json.loads(value or "[]")
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded if str(item).strip()]


def _mask_email(value: str) -> str:
    normalized = _normalize_email(value)
    if "@" not in normalized:
        return "***"
    local, domain = normalized.split("@", 1)
    local_mask = (local[:2] + "***") if len(local) > 2 else "***"
    return f"{local_mask}@{domain}"


def _mask_phone(value: str) -> str:
    digits = _normalize_phone(value)
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def _mask_contact(canal: str, contato: str) -> str:
    if canal == "email":
        return _mask_email(contato)
    return _mask_phone(contato)


def _hash_challenge_code(challenge_id: str, code: str) -> str:
    raw = f"{challenge_id}:{code}:{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _generate_challenge_id() -> str:
    return secrets.token_urlsafe(24)


def _generate_challenge_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _challenge_response(
    challenge_id: str,
    *,
    debug_code: str | None = None,
) -> PortalChallengeResponse:
    return PortalChallengeResponse(
        challenge_id=challenge_id,
        message="Se os dados corresponderem ao cadastro, enviaremos um codigo temporario.",
        expires_in_seconds=max(60, settings.PORTAL_CHALLENGE_EXPIRE_MINUTES * 60),
        debug_code=debug_code,
    )


def _assert_canal_portal_habilitado(canal: str) -> None:
    if canal == "whatsapp" and not settings.PORTAL_WHATSAPP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Acesso por WhatsApp ainda nao esta disponivel. Use o email cadastrado.",
        )


def _debug_code_for_response(code: str | None) -> str | None:
    if not code:
        return None
    if settings.APP_ENV.lower() in {"production", "stage", "staging"}:
        return None
    if not settings.PORTAL_DEBUG_EXPOSE_CODE:
        return None
    return code


def _is_tutor_active(tutor: Tutor | None) -> bool:
    return tutor is not None and getattr(tutor, "ativo", 0) == 1


def _is_paciente_active(paciente: Paciente | None) -> bool:
    return paciente is not None and getattr(paciente, "ativo", 0) == 1


def _is_clinica_active(clinica: Clinica | None) -> bool:
    ativo = getattr(clinica, "ativo", False)
    return clinica is not None and ativo not in (False, 0, "0")


def _obter_tutor_e_paciente(
    db: Session,
    *,
    tutor_id: int,
    paciente_id: int,
) -> tuple[Tutor | None, Paciente | None]:
    tutor = db.query(Tutor).filter(Tutor.id == tutor_id).first()
    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not _is_tutor_active(tutor) or not _is_paciente_active(paciente):
        return None, None
    if paciente.tutor_id != tutor.id:
        return None, None
    return tutor, paciente


def _contato_tutor_confere(tutor: Tutor, canal: str, contato: str) -> bool:
    if canal == "email":
        return _normalize_email(tutor.email) == _normalize_email(contato)
    destino = tutor.whatsapp or tutor.telefone
    return _normalize_phone(destino) == _normalize_phone(contato)


def _obter_clinica_ativa(db: Session, clinica_id: int) -> Clinica | None:
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if not _is_clinica_active(clinica):
        return None
    return clinica


def _criar_desafio(
    db: Session,
    *,
    actor_type: str,
    actor_id: int,
    canal: str,
    contato_mascarado: str,
    scope: list[str],
    contexto: dict[str, Any],
    paciente_id: int | None = None,
    clinica_id: int | None = None,
    responsavel_nome: str | None = None,
) -> tuple[PortalAccessChallenge, str]:
    challenge_id = _generate_challenge_id()
    code = _generate_challenge_code()
    challenge = PortalAccessChallenge(
        challenge_id=challenge_id,
        actor_type=actor_type,
        actor_id=actor_id,
        paciente_id=paciente_id,
        clinica_id=clinica_id,
        responsavel_nome=(responsavel_nome or "").strip() or None,
        canal=canal,
        contato_mascarado=contato_mascarado,
        scope_json=_json_dump(scope),
        contexto_json=_json_dump(contexto),
        code_hash=_hash_challenge_code(challenge_id, code),
        status=PORTAL_CHALLENGE_STATUS_PENDING,
        failed_attempts=0,
        max_attempts=max(1, int(settings.PORTAL_MAX_CHALLENGE_ATTEMPTS)),
        expires_at=_utcnow() + timedelta(minutes=settings.PORTAL_CHALLENGE_EXPIRE_MINUTES),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge, code


def _expirar_desafio_se_preciso(db: Session, challenge: PortalAccessChallenge) -> bool:
    if challenge.expires_at and challenge.expires_at <= _utcnow():
        if challenge.status == PORTAL_CHALLENGE_STATUS_PENDING:
            challenge.status = PORTAL_CHALLENGE_STATUS_EXPIRED
            db.commit()
        return True
    return False


def _bloquear_desafio_se_preciso(db: Session, challenge: PortalAccessChallenge) -> None:
    if challenge.failed_attempts >= challenge.max_attempts:
        challenge.status = PORTAL_CHALLENGE_STATUS_LOCKED
        db.commit()


def _portal_contexto_exibicao(challenge: PortalAccessChallenge) -> tuple[str | None, list[str]]:
    contexto = _json_load_dict(challenge.contexto_json)
    display_name = str(contexto.get("display_name") or "").strip() or None
    scope = _json_load_list(challenge.scope_json)
    return display_name, scope


def _enviar_desafio_portal(
    *,
    challenge: PortalAccessChallenge,
    code: str,
    channel: str,
    destination: str,
    display_name: str | None,
    paciente_nome: str | None = None,
    clinica_nome: str | None = None,
    responsavel_nome: str | None = None,
) -> str:
    try:
        result = send_portal_access_code(
            PortalChallengeDeliveryRequest(
                challenge_id=challenge.challenge_id,
                actor_type=challenge.actor_type,
                actor_id=challenge.actor_id,
                channel=channel,
                destination=destination,
                code=code,
                expires_in_minutes=max(1, int(settings.PORTAL_CHALLENGE_EXPIRE_MINUTES or 15)),
                display_name=display_name,
                paciente_nome=paciente_nome,
                clinica_nome=clinica_nome,
                responsavel_nome=responsavel_nome,
            )
        )
        return result.provider
    except PortalDeliveryError as exc:
        logger.exception(
            "Falha ao enviar codigo do portal (challenge_id=%s, actor_type=%s, channel=%s)",
            challenge.challenge_id,
            challenge.actor_type,
            channel,
        )
        return f"failed:{exc.__class__.__name__}"


def _emitir_token_desafio(challenge: PortalAccessChallenge) -> PortalTokenResponse:
    display_name, scope = _portal_contexto_exibicao(challenge)
    token, expires_at = create_portal_session_token(
        actor_type=challenge.actor_type,
        actor_id=challenge.actor_id,
        challenge_id=challenge.challenge_id,
        paciente_id=challenge.paciente_id,
        clinica_id=challenge.clinica_id,
        display_name=display_name,
        channel=challenge.canal,
        scope=scope,
    )
    return PortalTokenResponse(
        access_token=token,
        expires_at=expires_at,
        actor_type=challenge.actor_type,
        actor_id=challenge.actor_id,
        paciente_id=challenge.paciente_id,
        clinica_id=challenge.clinica_id,
        scope=scope,
    )


def _assert_tutor_scope(
    db: Session,
    session: PortalSessionContext,
    paciente_id: int,
) -> Paciente:
    if session.actor_type != "tutor" or session.paciente_id != paciente_id:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso a este pet.")

    paciente = db.query(Paciente).filter(Paciente.id == paciente_id).first()
    if not _is_paciente_active(paciente) or paciente.tutor_id != session.actor_id:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso a este pet.")
    return paciente


def _load_map(db: Session, model, ids: Iterable[int]) -> dict[int, Any]:
    unique_ids = sorted({int(item) for item in ids if item is not None})
    if not unique_ids:
        return {}
    items = db.query(model).filter(model.id.in_(unique_ids)).all()
    return {item.id: item for item in items}


def _resolve_exam_clinica_id(
    exam: Exame,
    atendimentos_map: dict[int, AtendimentoClinico],
    laudos_map: dict[int, Laudo],
) -> int | None:
    if exam.atendimento_id:
        atendimento = atendimentos_map.get(exam.atendimento_id)
        if atendimento and atendimento.clinica_id is not None:
            return int(atendimento.clinica_id)
    if exam.laudo_id:
        laudo = laudos_map.get(exam.laudo_id)
        if laudo and laudo.clinic_id is not None:
            return int(laudo.clinic_id)
    return None


def _assert_portal_scope(session: PortalSessionContext, permissao: str) -> None:
    """Confere a PERMISSAO da sessao, nao a posse do recurso.

    Ate aqui o portal so tinha `_assert_*_scope_for_exam`, que conferem se aquele
    exame pertence aquele ator - nunca se o ator tem direito a operacao. O campo
    `scope` era gravado no token desde `portal-secure-access-foundation` e nunca
    lido, ou seja, toda sessao valia tudo dentro do seu `actor_type`.

    Isso passa a valer de verdade aqui. Hoje nao muda nada na pratica, porque
    todas as sessoes emitidas (senha, MFA, refresh e o fluxo legado de codigo)
    carregam o escopo cheio do seu ator - e o teste
    `test_portal_escopo_sessao.py` existe para provar isso. O ganho e poder
    emitir sessao com menos poder sem ter que confiar so na tela, que e o que
    `portal-clinica-dispositivo-confiavel` precisa.
    """
    if permissao not in (session.scope or ()):
        raise HTTPException(
            status_code=403,
            detail="Sessao do portal sem permissao para esta operacao.",
        )


def _assert_clinica_scope_for_exam(
    session: PortalSessionContext,
    exam: Exame,
    atendimentos_map: dict[int, AtendimentoClinico],
    laudos_map: dict[int, Laudo],
) -> None:
    if session.actor_type != "clinica" or session.clinica_id is None:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso para clinica.")
    resolved_clinica_id = _resolve_exam_clinica_id(exam, atendimentos_map, laudos_map)
    if resolved_clinica_id is None or resolved_clinica_id != session.clinica_id:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso a este exame.")


def _portal_exam_release_filter():
    return or_(
        Exame.status.in_(PORTAL_RELEASED_EXAM_STATUSES),
        Laudo.status.in_(PORTAL_RELEASED_LAUDO_STATUSES),
    )


def _is_exam_released_to_portal(exam: Exame, laudos_map: dict[int, Laudo]) -> bool:
    if is_portal_released_status(exam.status):
        return True
    if exam.laudo_id:
        laudo = laudos_map.get(exam.laudo_id)
        if laudo and is_portal_released_status(laudo.status, kind="laudo"):
            return True
    return False


def _marcar_exame_visualizado_no_portal(
    db: Session,
    exame_id: int,
    actor_type: str | None,
    actor_id: int | None = None,
) -> None:
    """Registra o primeiro download externo do ciclo de liberacao vigente.

    O mesmo endpoint tambem atende o tutor (dono do pet), que nao pode contar
    como parceiro. Clinica grava no exame; veterinario grava no destino de
    liberacao correspondente. Ambos sao idempotentes no ciclo vigente.
    """
    if actor_type == "clinica":
        exame = db.query(Exame).filter(Exame.id == exame_id).first()
        if not exame or exame.visualizado_portal_em is not None:
            return
        if not is_portal_released_status(exame.status):
            return
        exame.visualizado_portal_em = datetime.now()
        db.commit()
        return

    if actor_type == "parceiro" and actor_id is not None:
        target = (
            db.query(PortalPartnerReleaseTarget)
            .filter(
                PortalPartnerReleaseTarget.partner_id == actor_id,
                PortalPartnerReleaseTarget.exame_id == exame_id,
                PortalPartnerReleaseTarget.revoked_at.is_(None),
            )
            .first()
        )
        if target is None or target.downloaded_at is not None:
            return
        target.downloaded_at = datetime.now()
        db.commit()


def _serialize_exam_attachment(anexo: AnexoAtendimento) -> PortalExamAttachmentResponse:
    return PortalExamAttachmentResponse(
        anexo_id=anexo.id,
        nome_original=anexo.nome_original or f"anexo_{anexo.id}",
        mime_type=anexo.mime_type or "application/octet-stream",
        tamanho=anexo.tamanho,
        download_available=attachment_has_download_source(anexo),
    )


def _build_exam_summary(
    exam: Exame,
    attachments: list[AnexoAtendimento],
    paciente: Paciente | None = None,
    tutor: Tutor | None = None,
    laudo: Laudo | None = None,
) -> PortalExamSummaryResponse:
    return PortalExamSummaryResponse(
        id=exam.id,
        paciente_id=exam.paciente_id,
        paciente_nome=getattr(paciente, "nome", None),
        tutor_nome=getattr(tutor, "nome", None),
        especie=getattr(paciente, "especie", None),
        atendimento_id=exam.atendimento_id,
        laudo_id=exam.laudo_id,
        tipo_exame=exam.tipo_exame,
        categoria_exame=exam.categoria_exame,
        prioridade=exam.prioridade,
        status=exam.status,
        data_exame=laudo.data_exame.isoformat() if laudo and laudo.data_exame else None,
        data_solicitacao=exam.data_solicitacao.isoformat() if exam.data_solicitacao else None,
        data_resultado=exam.data_resultado.isoformat() if exam.data_resultado else None,
        observacoes=exam.observacoes,
        anexos=[_serialize_exam_attachment(item) for item in attachments],
    )


def _load_exam_with_context(
    db: Session,
    exame_id: int,
) -> tuple[Exame, dict[int, AtendimentoClinico], dict[int, Laudo]]:
    exam = db.query(Exame).filter(Exame.id == exame_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exame nao encontrado.")
    atendimentos_map = _load_map(db, AtendimentoClinico, [exam.atendimento_id] if exam.atendimento_id else [])
    laudos_map = _load_map(db, Laudo, [exam.laudo_id] if exam.laudo_id else [])
    return exam, atendimentos_map, laudos_map


def _assert_portal_exam_access(
    db: Session,
    session: PortalSessionContext,
    exam: Exame,
    atendimentos_map: dict[int, AtendimentoClinico],
    laudos_map: dict[int, Laudo],
) -> None:
    if not _is_exam_released_to_portal(exam, laudos_map):
        raise HTTPException(status_code=403, detail="Exame nao liberado no portal.")
    if session.actor_type == "tutor":
        _assert_tutor_scope(db, session, exam.paciente_id)
        return
    if session.actor_type == "clinica":
        _assert_clinica_scope_for_exam(session, exam, atendimentos_map, laudos_map)
        return
    if session.actor_type == "parceiro":
        _assert_partner_scope_for_exam(db, session, exam.id)
        return
    raise HTTPException(status_code=403, detail="Sessao do portal sem escopo reconhecido.")


def _partner_label(tipo: str | None) -> str:
    if str(tipo or "").strip().lower() == "veterinario":
        return "Veterinario parceiro"
    return "Parceiro externo"


def _load_active_partner_for_session(
    db: Session,
    session: PortalSessionContext,
) -> PortalPartnerProfile:
    partner = db.query(PortalPartnerProfile).filter(PortalPartnerProfile.id == session.actor_id).first()
    if partner is None or not bool(partner.ativo):
        raise HTTPException(status_code=403, detail="Parceiro externo sem acesso ativo ao portal.")
    return partner


def _partner_release_target_exists(
    db: Session,
    *,
    partner_id: int,
    exame_id: int,
) -> bool:
    target = (
        db.query(PortalPartnerReleaseTarget.id)
        .filter(
            PortalPartnerReleaseTarget.partner_id == partner_id,
            PortalPartnerReleaseTarget.exame_id == exame_id,
            PortalPartnerReleaseTarget.revoked_at.is_(None),
        )
        .first()
    )
    return target is not None


def _assert_partner_scope_for_exam(
    db: Session,
    session: PortalSessionContext,
    exame_id: int,
) -> None:
    if not _partner_release_target_exists(db, partner_id=session.actor_id, exame_id=exame_id):
        raise HTTPException(status_code=403, detail="Exame fora do escopo do parceiro externo.")


def _date_start(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time())


def _date_end_exclusive(value: date) -> datetime:
    return _date_start(value) + timedelta(days=1)


def _portal_exam_date_expression():
    return func.coalesce(Laudo.data_exame, Exame.data_solicitacao, Exame.data_resultado)


def _portal_exam_sort_expression(sort_by: str):
    data_expr = _portal_exam_date_expression()
    mapping = {
        "data": data_expr,
        "tipo_exame": func.lower(func.coalesce(Exame.tipo_exame, "")),
        "especie": func.lower(func.coalesce(Paciente.especie, "")),
        "pet": func.lower(func.coalesce(Paciente.nome, "")),
        "tutor": func.lower(func.coalesce(Tutor.nome, "")),
        "status": func.lower(func.coalesce(Exame.status, "")),
    }
    return mapping.get(sort_by, data_expr)


def _portal_local_now() -> datetime:
    return datetime.now(PORTAL_LOCAL_TZ)


def _normalize_local_naive_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value
    return value.astimezone(PORTAL_LOCAL_TZ).replace(tzinfo=None)


def _portal_local_date(value: datetime | None) -> date | None:
    normalized = _normalize_local_naive_datetime(value)
    return normalized.date() if normalized else None


def _portal_utc_naive_bounds_for_local_day(value: date) -> tuple[datetime, datetime]:
    """Return UTC-naive bounds for a calendar day in the portal's local timezone."""
    local_start = datetime.combine(value, datetime.min.time(), tzinfo=PORTAL_LOCAL_TZ)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _portal_clinic_release_sla_hours() -> int:
    return max(1, int(settings.PORTAL_CLINIC_RELEASE_SLA_HOURS or 48))


def _portal_tipo_label_from_laudo(laudo: Laudo) -> str:
    tipo = str(laudo.tipo or "").strip().lower()
    labels = {
        "ecocardiograma": "Ecocardiograma",
        "eletrocardiograma": "Eletrocardiograma",
        "pressao_arterial": "Pressao arterial",
        "ultrassonografia_abdominal": "Ultrassonografia abdominal",
    }
    if tipo in labels:
        return labels[tipo]
    return str(laudo.titulo or laudo.tipo or "Laudo").strip() or "Laudo"


def _portal_operational_datetime_for_laudo(laudo: Laudo) -> datetime | None:
    return laudo.data_exame or laudo.data_laudo or laudo.created_at


def _portal_operational_datetime_for_external_exam(
    exam: Exame,
    atendimento: AtendimentoClinico | None = None,
) -> datetime | None:
    return exam.data_solicitacao or exam.data_resultado or getattr(atendimento, "data_atendimento", None) or exam.created_at


def _portal_operational_release_estimate(value: datetime | None) -> str | None:
    reference = _normalize_local_naive_datetime(value)
    if reference is None:
        return None
    return (reference + timedelta(hours=_portal_clinic_release_sla_hours())).isoformat()


def _portal_operational_status_for_laudo(
    laudo: Laudo,
    related_exam: Exame | None = None,
) -> tuple[str, str]:
    if related_exam and is_portal_released_status(related_exam.status):
        return "liberado_portal", "Liberado no portal"
    if is_portal_released_status(laudo.status, kind="laudo"):
        return "liberado_portal", "Liberado no portal"

    normalized_status = str(laudo.status or "").strip().lower()
    if normalized_status == "finalizado":
        return "aguardando_liberacao", "Aguardando liberacao"
    return "em_laudo", "Em laudo"


def _portal_operational_status_for_external_exam(exam: Exame) -> tuple[str, str]:
    if is_portal_released_status(exam.status):
        return "liberado_portal", "Liberado no portal"

    normalized_status = str(exam.status or "").strip().lower()
    if normalized_status in {"concluido", "finalizado"}:
        return "aguardando_liberacao", "Aguardando liberacao"
    return "em_andamento", "Em andamento"


_PORTAL_OPERATIONAL_RECENT_LIMIT = 8
_PORTAL_OPERATIONAL_PENDING_CANDIDATE_LIMIT = 30


def _portal_build_laudo_operational_items(
    db: Session,
    laudos: list[Laudo],
    *,
    sla_horas: int,
    clinica_nome: str,
) -> list[tuple[datetime, PortalClinicOperationalItemResponse]]:
    if not laudos:
        return []
    pacientes_map = _load_map(db, Paciente, [laudo.paciente_id for laudo in laudos if laudo.paciente_id])
    tutores_map = _load_map(
        db,
        Tutor,
        [paciente.tutor_id for paciente in pacientes_map.values() if paciente and paciente.tutor_id],
    )
    related_exams = (
        db.query(Exame)
        .filter(Exame.laudo_id.in_([laudo.id for laudo in laudos if laudo.id]))
        .order_by(Exame.id.desc())
        .all()
    )
    exams_by_laudo_id: dict[int, Exame] = {}
    for exam in related_exams:
        exams_by_laudo_id.setdefault(int(exam.laudo_id or 0), exam)

    items: list[tuple[datetime, PortalClinicOperationalItemResponse]] = []
    for laudo in laudos:
        related_exam = exams_by_laudo_id.get(int(laudo.id))
        status_key, status_label = _portal_operational_status_for_laudo(laudo, related_exam)
        operational_dt = _portal_operational_datetime_for_laudo(laudo)
        paciente = pacientes_map.get(laudo.paciente_id)
        tutor = tutores_map.get(getattr(paciente, "tutor_id", None))
        items.append(
            (
                _normalize_local_naive_datetime(operational_dt) or datetime.min,
                PortalClinicOperationalItemResponse(
                    item_id=f"laudo:{laudo.id}",
                    origem="laudo",
                    paciente_id=laudo.paciente_id,
                    paciente_nome=getattr(paciente, "nome", None),
                    tutor_nome=getattr(tutor, "nome", None),
                    especie=getattr(paciente, "especie", None),
                    tipo_exame=getattr(related_exam, "tipo_exame", None) or _portal_tipo_label_from_laudo(laudo),
                    status_key=status_key,
                    status_label=status_label,
                    data_realizacao=operational_dt.isoformat() if operational_dt else None,
                    data_liberacao=(
                        getattr(related_exam, "data_resultado", None) or getattr(laudo, "updated_at", None)
                    ).isoformat()
                    if status_key == "liberado_portal"
                    and (getattr(related_exam, "data_resultado", None) or getattr(laudo, "updated_at", None))
                    else None,
                    previsao_liberacao=(
                        _portal_operational_release_estimate(operational_dt)
                        if status_key != "liberado_portal"
                        else None
                    ),
                    observacoes=(
                        "Prazo padrao de ate "
                        f"{sla_horas}h apos a realizacao."
                        if status_key != "liberado_portal"
                        else f"Disponivel no portal da unidade {clinica_nome}."
                    ),
                ),
            )
        )
    return items


def _portal_build_external_exam_operational_items(
    db: Session,
    exams: list[Exame],
    *,
    sla_horas: int,
) -> list[tuple[datetime, PortalClinicOperationalItemResponse]]:
    if not exams:
        return []
    pacientes_map = _load_map(db, Paciente, [exam.paciente_id for exam in exams if exam.paciente_id])
    tutores_map = _load_map(
        db,
        Tutor,
        [paciente.tutor_id for paciente in pacientes_map.values() if paciente and paciente.tutor_id],
    )
    atendimentos_map = _load_map(
        db,
        AtendimentoClinico,
        [exam.atendimento_id for exam in exams if exam.atendimento_id],
    )

    items: list[tuple[datetime, PortalClinicOperationalItemResponse]] = []
    for exam in exams:
        status_key, status_label = _portal_operational_status_for_external_exam(exam)
        atendimento = atendimentos_map.get(getattr(exam, "atendimento_id", None))
        operational_dt = _portal_operational_datetime_for_external_exam(exam, atendimento)
        paciente = pacientes_map.get(exam.paciente_id)
        tutor = tutores_map.get(getattr(paciente, "tutor_id", None))
        items.append(
            (
                _normalize_local_naive_datetime(operational_dt) or datetime.min,
                PortalClinicOperationalItemResponse(
                    item_id=f"exame:{exam.id}",
                    origem="exame",
                    paciente_id=exam.paciente_id,
                    paciente_nome=getattr(paciente, "nome", None),
                    tutor_nome=getattr(tutor, "nome", None),
                    especie=getattr(paciente, "especie", None),
                    tipo_exame=exam.tipo_exame or "Exame",
                    status_key=status_key,
                    status_label=status_label,
                    data_realizacao=operational_dt.isoformat() if operational_dt else None,
                    data_liberacao=exam.data_resultado.isoformat() if status_key == "liberado_portal" and exam.data_resultado else None,
                    previsao_liberacao=(
                        _portal_operational_release_estimate(operational_dt)
                        if status_key != "liberado_portal"
                        else None
                    ),
                    observacoes=(
                        "Arquivo ja disponivel para consulta e download."
                        if status_key == "liberado_portal"
                        else f"Prazo padrao de ate {sla_horas}h para disponibilizacao."
                    ),
                ),
            )
        )
    return items


def _build_clinic_operational_panel(
    db: Session,
    *,
    clinica_id: int,
    clinica_nome: str,
) -> tuple[
    PortalClinicOperationalSummaryResponse,
    list[PortalClinicOperationalItemResponse],
    list[PortalClinicOperationalItemResponse],
]:
    local_now = _portal_local_now()
    local_today = local_now.date()
    today_start = datetime.combine(local_today, datetime.min.time())
    today_end = today_start + timedelta(days=1)
    released_today_start, released_today_end = _portal_utc_naive_bounds_for_local_day(local_today)
    sla_horas = _portal_clinic_release_sla_hours()

    clinic_filter = or_(
        AtendimentoClinico.clinica_id == clinica_id,
        Laudo.clinic_id == clinica_id,
    )
    released_exam_base = (
        db.query(Exame)
        .outerjoin(AtendimentoClinico, AtendimentoClinico.id == Exame.atendimento_id)
        .outerjoin(Laudo, Laudo.id == Exame.laudo_id)
        .filter(clinic_filter)
        .filter(_portal_exam_release_filter())
    )
    released_today = released_exam_base.filter(
        Exame.data_resultado.is_not(None),
        Exame.data_resultado >= released_today_start,
        Exame.data_resultado < released_today_end,
    ).count()

    laudo_base = db.query(Laudo).filter(Laudo.clinic_id == clinica_id)
    em_laudo = (
        laudo_base.filter(
            ~Laudo.status.in_(PORTAL_RELEASED_LAUDO_STATUSES),
            func.lower(func.coalesce(Laudo.status, "")) != "finalizado",
        ).count()
    )
    aguardando_liberacao = (
        laudo_base.filter(
            ~Laudo.status.in_(PORTAL_RELEASED_LAUDO_STATUSES),
            func.lower(func.coalesce(Laudo.status, "")) == "finalizado",
        ).count()
    )

    laudo_realizados_hoje = laudo_base.filter(
        func.coalesce(Laudo.data_exame, Laudo.data_laudo, Laudo.created_at) >= today_start,
        func.coalesce(Laudo.data_exame, Laudo.data_laudo, Laudo.created_at) < today_end,
    ).count()

    external_exam_scope = (
        db.query(Exame)
        .join(AtendimentoClinico, AtendimentoClinico.id == Exame.atendimento_id)
        .filter(
            AtendimentoClinico.clinica_id == clinica_id,
            Exame.laudo_id.is_(None),
        )
    )
    external_realizados_hoje = external_exam_scope.filter(
        func.coalesce(Exame.data_solicitacao, Exame.data_resultado, Exame.created_at) >= today_start,
        func.coalesce(Exame.data_solicitacao, Exame.data_resultado, Exame.created_at) < today_end,
    ).count()

    external_exam_base = external_exam_scope.filter(~Exame.status.in_(PORTAL_RELEASED_EXAM_STATUSES))
    em_laudo += external_exam_base.filter(
        func.lower(func.coalesce(Exame.status, "")).notin_(["concluido", "finalizado"])
    ).count()
    aguardando_liberacao += external_exam_base.filter(
        func.lower(func.coalesce(Exame.status, "")).in_(["concluido", "finalizado"])
    ).count()

    recent_laudos = (
        laudo_base.order_by(
            func.coalesce(Laudo.data_exame, Laudo.data_laudo, Laudo.created_at).desc(),
            Laudo.id.desc(),
        ).limit(_PORTAL_OPERATIONAL_RECENT_LIMIT).all()
    )
    recent_external_exams = (
        external_exam_scope.order_by(
            func.coalesce(Exame.data_solicitacao, Exame.data_resultado, Exame.created_at).desc(),
            Exame.id.desc(),
        )
        .limit(_PORTAL_OPERATIONAL_RECENT_LIMIT)
        .all()
    )

    operational_items = (
        _portal_build_laudo_operational_items(db, recent_laudos, sla_horas=sla_horas, clinica_nome=clinica_nome)
        + _portal_build_external_exam_operational_items(db, recent_external_exams, sla_horas=sla_horas)
    )
    operational_items.sort(key=lambda item: item[0], reverse=True)

    # `recent_laudos`/`recent_external_exams` acima misturam todos os status e sao
    # cortados a `_PORTAL_OPERATIONAL_RECENT_LIMIT` por recencia - serve como feed
    # de atividade, mas um exame `aguardando_liberacao` mais antigo pode ficar de
    # fora se houver bastante atividade recente de outros status na frente dele.
    # Por isso `operational_pending_items` roda uma consulta propria, pre-filtrada
    # pra excluir so o que ja esta liberado (sem misturar com outros status antes
    # do corte), com um limite bem mais generoso.
    pending_laudo_candidates = (
        laudo_base.filter(~Laudo.status.in_(PORTAL_RELEASED_LAUDO_STATUSES))
        .order_by(
            func.coalesce(Laudo.data_exame, Laudo.data_laudo, Laudo.created_at).desc(),
            Laudo.id.desc(),
        )
        .limit(_PORTAL_OPERATIONAL_PENDING_CANDIDATE_LIMIT)
        .all()
    )
    pending_external_candidates = (
        external_exam_base.order_by(
            func.coalesce(Exame.data_solicitacao, Exame.data_resultado, Exame.created_at).desc(),
            Exame.id.desc(),
        )
        .limit(_PORTAL_OPERATIONAL_PENDING_CANDIDATE_LIMIT)
        .all()
    )
    operational_pending_items = [
        (sort_key, item)
        for sort_key, item in (
            _portal_build_laudo_operational_items(
                db, pending_laudo_candidates, sla_horas=sla_horas, clinica_nome=clinica_nome
            )
            + _portal_build_external_exam_operational_items(db, pending_external_candidates, sla_horas=sla_horas)
        )
        if item.status_key == "aguardando_liberacao"
    ]
    operational_pending_items.sort(key=lambda item: item[0], reverse=True)

    summary = PortalClinicOperationalSummaryResponse(
        realizados_hoje=laudo_realizados_hoje + external_realizados_hoje,
        em_laudo=em_laudo,
        aguardando_liberacao=aguardando_liberacao,
        liberados_hoje=released_today,
        sla_horas=sla_horas,
    )
    return (
        summary,
        [item for _, item in operational_items[:_PORTAL_OPERATIONAL_RECENT_LIMIT]],
        [item for _, item in operational_pending_items],
    )


def _load_exam_related_maps(
    db: Session,
    exams: list[Exame],
) -> tuple[dict[int, list[AnexoAtendimento]], dict[int, Paciente], dict[int, Tutor], dict[int, Laudo]]:
    exam_ids = [exam.id for exam in exams]
    attachments: list[AnexoAtendimento] = []
    if exam_ids:
        attachments = (
            db.query(AnexoAtendimento)
            .filter(AnexoAtendimento.exame_id.in_(exam_ids))
            .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
            .all()
        )
    attachments_by_exam: dict[int, list[AnexoAtendimento]] = {}
    for attachment in attachments:
        attachments_by_exam.setdefault(int(attachment.exame_id or 0), []).append(attachment)

    pacientes_map = _load_map(db, Paciente, [exam.paciente_id for exam in exams])
    tutores_map = _load_map(
        db,
        Tutor,
        [paciente.tutor_id for paciente in pacientes_map.values() if paciente and paciente.tutor_id],
    )
    laudos_map = _load_map(db, Laudo, [exam.laudo_id for exam in exams if exam.laudo_id])
    return attachments_by_exam, pacientes_map, tutores_map, laudos_map


@router.post("/tutores/sessao-link", response_model=PortalChallengeResponse, status_code=status.HTTP_202_ACCEPTED)
def solicitar_sessao_tutor(
    payload: PortalTutorSessionLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    challenge_id = _generate_challenge_id()
    debug_code = None
    _assert_canal_portal_habilitado(payload.canal)
    tutor, paciente = _obter_tutor_e_paciente(
        db,
        tutor_id=payload.tutor_id,
        paciente_id=payload.paciente_id,
    )

    if tutor and paciente and _contato_tutor_confere(tutor, payload.canal, payload.contato):
        contexto = {
            "display_name": tutor.nome,
            "tutor_nome": tutor.nome,
            "paciente_nome": paciente.nome,
        }
        challenge, code = _criar_desafio(
            db,
            actor_type="tutor",
            actor_id=tutor.id,
            paciente_id=paciente.id,
            canal=payload.canal,
            contato_mascarado=_mask_contact(payload.canal, payload.contato),
            scope=PORTAL_SCOPE_TUTOR,
            contexto=contexto,
        )
        challenge_id = challenge.challenge_id
        debug_code = _debug_code_for_response(code)
        delivery_provider = _enviar_desafio_portal(
            challenge=challenge,
            code=code,
            channel=payload.canal,
            destination=payload.contato,
            display_name=tutor.nome,
            paciente_nome=paciente.nome,
        )
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_access_challenge",
            acao="PORTAL_TUTOR_CHALLENGE_CREATED",
            descricao="Desafio do portal criado para tutor.",
            entidade_id=challenge.challenge_id,
            detalhes={
                "actor_type": "tutor",
                "actor_id": tutor.id,
                "paciente_id": paciente.id,
                "canal": payload.canal,
                "delivery_provider": delivery_provider,
            },
            request=request,
        )
    else:
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_access_challenge",
            acao="PORTAL_TUTOR_CHALLENGE_REQUESTED",
            descricao="Solicitacao de acesso tutor recebida sem confirmacao de match.",
            entidade_id=challenge_id,
            detalhes={
                "actor_type": "tutor",
                "tutor_id": payload.tutor_id,
                "paciente_id": payload.paciente_id,
                "canal": payload.canal,
                "accepted": False,
            },
            request=request,
        )

    return _challenge_response(challenge_id, debug_code=debug_code)


@router.post("/clinicas/sessao-link", response_model=PortalChallengeResponse, status_code=status.HTTP_202_ACCEPTED)
def solicitar_sessao_clinica(
    payload: PortalClinicaSessionLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not settings.PORTAL_CLINIC_LEGACY_CODE_LOGIN_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fluxo legado de codigo da clinica indisponivel.",
        )
    challenge_id = _generate_challenge_id()
    debug_code = None
    clinica = _obter_clinica_ativa(db, payload.clinica_id)

    if clinica and _normalize_email(clinica.email) == _normalize_email(payload.email):
        contexto = {
            "display_name": payload.responsavel_nome.strip(),
            "clinica_nome": clinica.nome,
        }
        challenge, code = _criar_desafio(
            db,
            actor_type="clinica",
            actor_id=clinica.id,
            clinica_id=clinica.id,
            responsavel_nome=payload.responsavel_nome,
            canal="email",
            contato_mascarado=_mask_email(payload.email),
            scope=PORTAL_SCOPE_CLINICA,
            contexto=contexto,
        )
        challenge_id = challenge.challenge_id
        debug_code = _debug_code_for_response(code)
        delivery_provider = _enviar_desafio_portal(
            challenge=challenge,
            code=code,
            channel="email",
            destination=payload.email,
            display_name=payload.responsavel_nome.strip(),
            clinica_nome=clinica.nome,
            responsavel_nome=payload.responsavel_nome.strip(),
        )
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_access_challenge",
            acao="PORTAL_CLINICA_CHALLENGE_CREATED",
            descricao="Desafio do portal criado para clinica parceira.",
            entidade_id=challenge.challenge_id,
            detalhes={
                "actor_type": "clinica",
                "clinica_id": clinica.id,
                "canal": "email",
                "delivery_provider": delivery_provider,
            },
            request=request,
        )
    else:
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_access_challenge",
            acao="PORTAL_CLINICA_CHALLENGE_REQUESTED",
            descricao="Solicitacao de acesso de clinica recebida sem confirmacao de match.",
            entidade_id=challenge_id,
            detalhes={
                "actor_type": "clinica",
                "clinica_id": payload.clinica_id,
                "canal": "email",
                "accepted": False,
            },
            request=request,
        )

    return _challenge_response(challenge_id, debug_code=debug_code)


@router.post("/auth/verificar-codigo", response_model=PortalTokenResponse)
def verificar_codigo_portal(
    payload: PortalCodeVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    challenge = (
        db.query(PortalAccessChallenge)
        .filter(PortalAccessChallenge.challenge_id == payload.challenge_id)
        .first()
    )

    if not challenge:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    if _expirar_desafio_se_preciso(db, challenge):
        raise HTTPException(status_code=410, detail="Codigo expirado.")

    if challenge.status != PORTAL_CHALLENGE_STATUS_PENDING:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    expected_hash = _hash_challenge_code(challenge.challenge_id, payload.codigo.strip())
    if challenge.code_hash != expected_hash:
        challenge.failed_attempts += 1
        db.commit()
        _bloquear_desafio_se_preciso(db, challenge)
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_access_challenge",
            acao="PORTAL_CODE_REJECTED",
            descricao="Codigo do portal rejeitado.",
            entidade_id=challenge.challenge_id,
            detalhes={
                "actor_type": challenge.actor_type,
                "failed_attempts": challenge.failed_attempts,
            },
            request=request,
        )
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    challenge.status = PORTAL_CHALLENGE_STATUS_CONSUMED
    challenge.consumed_at = _utcnow()
    db.commit()

    token_response = _emitir_token_desafio(challenge)
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_access_challenge",
        acao="PORTAL_CODE_VERIFIED",
        descricao="Codigo do portal validado com sucesso.",
        entidade_id=challenge.challenge_id,
        detalhes={
            "actor_type": challenge.actor_type,
            "actor_id": challenge.actor_id,
            "paciente_id": challenge.paciente_id,
            "clinica_id": challenge.clinica_id,
        },
        request=request,
    )
    return token_response


def _resolver_link_laudo(
    db: Session,
    token: str,
) -> tuple[Any, Clinica, Exame, dict[int, AtendimentoClinico], dict[int, Laudo]]:
    """Valida o link de laudo e devolve o contexto do exame.

    Fonte unica da regra de recusa, usada tanto para abrir o laudo quanto para
    conectar o computador da recepcao. Reimplementar isso em cada endpoint faria
    os dois divergirem com o tempo, e a porta mais fraca viraria a efetiva.

    Toda recusa e o MESMO 404: a pagina publica nao pode revelar se o token
    existiu, se foi revogado ou se o exame saiu do ar.
    """
    link_invalido = HTTPException(
        status_code=404,
        detail="Link de laudo invalido ou indisponivel.",
    )

    link = resolve_active_link(db, token)
    if link is None:
        raise link_invalido

    clinica = _obter_clinica_ativa(db, link.clinica_id)
    if clinica is None:
        raise link_invalido

    exam = db.query(Exame).filter(Exame.id == link.exame_id).first()
    if exam is None:
        raise link_invalido

    atendimentos_map = _load_map(
        db, AtendimentoClinico, [exam.atendimento_id] if exam.atendimento_id else []
    )
    laudos_map = _load_map(db, Laudo, [exam.laudo_id] if exam.laudo_id else [])

    if not _is_exam_released_to_portal(exam, laudos_map):
        raise link_invalido

    # O vinculo exame->clinica e reconferido a cada uso: o link guarda a clinica
    # de quando foi emitido, e um exame remanejado depois nao pode continuar
    # acessivel pela unidade antiga.
    resolved_clinica_id = _resolve_exam_clinica_id(exam, atendimentos_map, laudos_map)
    if resolved_clinica_id is None or resolved_clinica_id != link.clinica_id:
        raise link_invalido

    return link, clinica, exam, atendimentos_map, laudos_map


@router.post("/laudo-link/{token}", response_model=PortalExamLinkResponse)
def abrir_laudo_por_link(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Abre UM laudo a partir do link enviado no WhatsApp da clinica.

    Publico de proposito: quem usa e a secretaria da clinica, que nao tem a senha
    do portal (criada pelo gerente) nem acesso ao e-mail do cadastro. Ver
    docs/specs/portal-clinica-link-laudo-whatsapp/intent.md.

    NAO emite sessao de portal. Uma sessao de clinica abriria todos os exames da
    unidade; este link vale por um exame so. O acesso ao arquivo sai por token de
    download ja preso ao par (exame, anexo), com validade curta.

    Todo caminho de recusa devolve o MESMO 404: a pagina publica nao pode revelar
    se o token existiu, se foi revogado ou se o exame saiu do ar (NFR-003).
    """
    link, clinica, exam, atendimentos_map, laudos_map = _resolver_link_laudo(db, token)

    paciente = db.query(Paciente).filter(Paciente.id == exam.paciente_id).first()
    laudo = laudos_map.get(exam.laudo_id) if exam.laudo_id else None

    # Contexto sintetico so para emitir o token de download preso a (exame, anexo).
    # actor_type "clinica" mantem a contagem de "a clinica ja viu" coerente com o
    # acesso pelo portal com senha (_marcar_exame_visualizado_no_portal).
    download_context = PortalSessionContext(
        actor_type="clinica",
        actor_id=link.clinica_id,
        paciente_id=exam.paciente_id,
        clinica_id=link.clinica_id,
        challenge_id=f"exam-link:{link.id}",
        display_name=clinica.nome,
        channel="whatsapp",
        scope=("exam:read", "exam:download"),
        expires_at=_utcnow(),
        auth_method="exam_link",
    )

    attachments = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.exame_id == exam.id)
        .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
        .all()
    )
    arquivos: list[PortalDownloadLinkItemResponse] = []
    for attachment in attachments:
        if not attachment_has_download_source(attachment):
            continue
        download_token, expires_at = create_portal_download_token(
            download_context,
            exame_id=exam.id,
            anexo_id=attachment.id,
        )
        arquivos.append(
            PortalDownloadLinkItemResponse(
                anexo_id=attachment.id,
                nome_original=attachment.nome_original or f"anexo_{attachment.id}",
                mime_type=attachment.mime_type or "application/octet-stream",
                download_url=f"/api/v1/portal/anexos/{attachment.id}/arquivo",
                download_token=download_token,
                download_token_header=PORTAL_DOWNLOAD_TOKEN_HEADER,
                expires_at=expires_at,
            )
        )

    register_link_open(db, link)
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_exam_link",
        acao="PORTAL_EXAM_LINK_OPENED",
        descricao="Laudo aberto pelo link direto enviado no WhatsApp da clinica.",
        entidade_id=str(link.id),
        detalhes={
            "exame_id": exam.id,
            "clinica_id": link.clinica_id,
            "open_count": link.open_count,
            "arquivos_disponiveis": len(arquivos),
        },
        request=request,
    )

    return PortalExamLinkResponse(
        clinica_nome=clinica.nome or "Clinica parceira",
        paciente_nome=getattr(paciente, "nome", None),
        tipo_exame=exam.tipo_exame or "Exame",
        data_exame=laudo.data_exame.isoformat() if laudo and laudo.data_exame else None,
        arquivos=arquivos,
        dispositivo_confiavel_disponivel=bool(settings.PORTAL_CLINIC_DEVICE_TRUST_ENABLED),
    )


def _emitir_sessao_dispositivo(
    trust,
    clinica: Clinica,
) -> PortalDeviceTrustResponse:
    """Access token curto em modo laudos para o dispositivo confiavel.

    O escopo sai da linha da confianca, nao de uma constante do endpoint: se um
    dia houver confianca com escopo diferente, o token acompanha.
    """
    scope = _json_load_list(trust.scope_json) or list(DEVICE_TRUST_SCOPE)
    access_token, expires_at = create_portal_session_token(
        actor_type="clinica",
        actor_id=clinica.id,
        challenge_id=f"device-trust:{trust.id}",
        clinica_id=clinica.id,
        display_name=clinica.nome,
        channel="device_trust",
        scope=scope,
        auth_method="device_trust",
    )
    return PortalDeviceTrustResponse(
        access_token=access_token,
        expires_at=expires_at,
        actor_id=clinica.id,
        clinica_id=clinica.id,
        clinica_nome=clinica.nome or "Clinica parceira",
        scope=list(scope),
        trusted_until=trust.expires_at,
    )


@router.post("/laudo-link/{token}/confiar-dispositivo", response_model=PortalDeviceTrustResponse)
def confiar_dispositivo_por_link(
    token: str,
    payload: PortalDeviceTrustRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Conecta o computador da recepcao ao portal em modo laudos.

    Nasce da mesma validacao que abre o laudo (`_resolver_link_laudo`), entao um
    link revogado, um exame despublicado ou uma clinica inativa recusam aqui
    exatamente como recusam la.

    Amplia o alcance em relacao ao link - que vale por um exame - para o acervo
    de laudos da unidade. E consciente: o preco de tirar a secretaria da
    dependencia do gerente. O teto e escopo de laudo, prazo por inatividade,
    revogacao e aviso ao gestor.
    """
    if not settings.PORTAL_CLINIC_DEVICE_TRUST_ENABLED:
        raise HTTPException(status_code=404, detail="Recurso indisponivel.")

    link, clinica, _exam, _atendimentos_map, _laudos_map = _resolver_link_laudo(db, token)

    trust, raw_token = create_trust(
        db,
        clinica_id=clinica.id,
        request=request,
        origin_exam_link_id=link.id,
        device_label=payload.device_label,
    )
    set_device_cookie(response, raw_token, expires_at=trust.expires_at, request=request)

    try:
        notify_clinic_device_trusted(
            db=db,
            request=request,
            clinica_id=clinica.id,
            clinica_nome=clinica.nome,
            device_label=trust.device_label,
            trusted_until=trust.expires_at,
        )
    except Exception:
        # O aviso ao gestor e supervisao, nao pre-requisito: SMTP fora do ar nao
        # pode impedir a recepcao de se conectar.
        logger.exception(
            "Falha ao avisar os gestores sobre dispositivo confiavel (clinica_id=%s)",
            clinica.id,
        )

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_trusted_device",
        acao="PORTAL_CLINIC_DEVICE_TRUSTED",
        descricao="Computador da recepcao conectado ao portal em modo laudos.",
        entidade_id=str(trust.id),
        detalhes={
            "clinica_id": clinica.id,
            "origin": trust.origin,
            "origin_exam_link_id": trust.origin_exam_link_id,
            "trusted_until": trust.expires_at.isoformat() if trust.expires_at else None,
        },
        request=request,
    )
    return _emitir_sessao_dispositivo(trust, clinica)


@router.post("/clinicas/dispositivo/sessao", response_model=PortalDeviceTrustResponse)
def abrir_sessao_dispositivo_confiavel(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Troca o cookie do dispositivo por uma sessao curta em modo laudos.

    Nao audita: a recepcao chama isso a cada carregamento de pagina por meses, e
    uma linha por chamada inundaria a auditoria sem informar nada. O que fica e
    `last_seen_at` na propria confianca. Criacao e revogacao continuam auditadas.

    Segue honrando confianca existente com a flag desligada - so a criacao e
    cortada la em cima.
    """
    sessao_invalida = HTTPException(status_code=401, detail="Dispositivo nao esta mais conectado.")

    raw_token = get_device_cookie(request)
    trust = resolve_active_trust(db, raw_token)
    if trust is None:
        clear_device_cookie(response, request)
        raise sessao_invalida

    if not user_agent_matches(trust, request):
        # Mesmo criterio de refresh_login_clinica: divergencia de navegador
        # encerra a confianca em vez de so recusar a chamada.
        revoke_trust(db, trust, motivo="mudanca-de-dispositivo")
        clear_device_cookie(response, request)
        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_clinic_trusted_device",
            acao="PORTAL_CLINIC_DEVICE_REVOKED",
            descricao="Confianca de dispositivo encerrada por divergencia de navegador.",
            entidade_id=str(trust.id),
            detalhes={"clinica_id": trust.clinica_id, "motivo": "mudanca-de-dispositivo"},
            request=request,
        )
        raise sessao_invalida

    clinica = _obter_clinica_ativa(db, trust.clinica_id)
    if clinica is None:
        revoke_trust(db, trust, motivo="clinica-inativa")
        clear_device_cookie(response, request)
        raise sessao_invalida

    novo_token = rotate_and_renew(db, trust, request=request)
    set_device_cookie(response, novo_token, expires_at=trust.expires_at, request=request)
    return _emitir_sessao_dispositivo(trust, clinica)


@router.post("/clinicas/dispositivo/encerrar", response_model=PortalDeviceTrustEndResponse)
def encerrar_dispositivo_confiavel(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """"Sair deste computador". Idempotente: sem confianca viva, so limpa o cookie."""
    raw_token = get_device_cookie(request)
    trust = resolve_active_trust(db, raw_token)
    clear_device_cookie(response, request)
    if trust is None:
        return PortalDeviceTrustEndResponse(encerrado=True)

    revoke_trust(db, trust, motivo="encerrado-pela-unidade")
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_clinic_trusted_device",
        acao="PORTAL_CLINIC_DEVICE_REVOKED",
        descricao="Confianca de dispositivo encerrada pela propria unidade.",
        entidade_id=str(trust.id),
        detalhes={"clinica_id": trust.clinica_id, "motivo": "encerrado-pela-unidade"},
        request=request,
    )
    return PortalDeviceTrustEndResponse(encerrado=True)


@router.get("/clinicas/exames", response_model=PortalExamListResponse)
def listar_exames_clinica_portal(
    q: str | None = Query(default=None, max_length=120),
    pet: str | None = Query(default=None, max_length=120),
    tutor: str | None = Query(default=None, max_length=120),
    especie: str | None = Query(default=None, max_length=80),
    tipo_exame: str | None = Query(default=None, max_length=120),
    status_exame: str | None = Query(default=None, max_length=80),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    sort_by: str = Query(default="data", pattern="^(data|tipo_exame|especie|pet|tutor|status)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    if portal_session.actor_type != "clinica" or portal_session.clinica_id is None:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso para clinica.")
    # Exame liberado exige `exam:read`, nao `clinic:read`: esta e a leitura que
    # uma sessao de menos poder precisa alcancar.
    _assert_portal_scope(portal_session, PORTAL_PERMISSION_EXAM_READ)

    clinica = _obter_clinica_ativa(db, portal_session.clinica_id)
    if not clinica:
        raise HTTPException(status_code=403, detail="Clinica sem acesso ativo ao portal.")

    clinic_filter = or_(
        AtendimentoClinico.clinica_id == portal_session.clinica_id,
        Laudo.clinic_id == portal_session.clinica_id,
    )
    query = (
        db.query(Exame)
        .outerjoin(AtendimentoClinico, AtendimentoClinico.id == Exame.atendimento_id)
        .outerjoin(Laudo, Laudo.id == Exame.laudo_id)
        .join(Paciente, Paciente.id == Exame.paciente_id)
        .outerjoin(Tutor, Tutor.id == Paciente.tutor_id)
        .filter(clinic_filter)
        .filter(_portal_exam_release_filter())
    )

    def _like(value: str) -> str:
        return f"%{value.strip()}%"

    if q and q.strip():
        term = _like(q)
        query = query.filter(
            or_(
                Paciente.nome.ilike(term),
                Tutor.nome.ilike(term),
                Exame.tipo_exame.ilike(term),
                Exame.categoria_exame.ilike(term),
            )
        )
    if pet and pet.strip():
        query = query.filter(Paciente.nome.ilike(_like(pet)))
    if tutor and tutor.strip():
        query = query.filter(Tutor.nome.ilike(_like(tutor)))
    if especie and especie.strip():
        query = query.filter(Paciente.especie.ilike(_like(especie)))
    if tipo_exame and tipo_exame.strip():
        query = query.filter(Exame.tipo_exame.ilike(_like(tipo_exame)))
    if status_exame and status_exame.strip():
        query = query.filter(Exame.status.ilike(_like(status_exame)))
    if data_inicio and data_fim and data_inicio > data_fim:
        raise HTTPException(status_code=422, detail="data_inicio nao pode ser maior que data_fim.")

    effective_data_fim = data_fim or data_inicio
    date_expr = _portal_exam_date_expression()
    if data_inicio:
        query = query.filter(date_expr >= _date_start(data_inicio))
    if effective_data_fim:
        query = query.filter(date_expr < _date_end_exclusive(effective_data_fim))

    total = query.count()
    sort_expr = _portal_exam_sort_expression(sort_by)
    primary_order = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()
    exams = query.order_by(primary_order, Exame.id.desc()).offset(offset).limit(limit).all()

    attachments_by_exam, pacientes_map, tutores_map, laudos_map = _load_exam_related_maps(db, exams)
    operational_summary, operational_items, operational_pending_items = _build_clinic_operational_panel(
        db,
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
    )
    items = [
        _build_exam_summary(
            exam,
            attachments_by_exam.get(exam.id, []),
            pacientes_map.get(exam.paciente_id),
            tutores_map.get(getattr(pacientes_map.get(exam.paciente_id), "tutor_id", None)),
            laudos_map.get(exam.laudo_id) if exam.laudo_id else None,
        )
        for exam in exams
    ]

    must_change_password = None
    if portal_session.account_id is not None:
        must_change_password = bool(
            db.query(PortalClinicAccount.must_change_password)
            .filter(PortalClinicAccount.id == portal_session.account_id)
            .scalar()
        )

    return PortalExamListResponse(
        total=total,
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
        operational_summary=operational_summary,
        operational_items=operational_items,
        operational_pending_items=operational_pending_items,
        items=items,
        must_change_password=must_change_password,
    )


AGENDA_PORTAL_STATUSES_VISIVEIS = ("Agendado", "Reservado", "Confirmado", "Em atendimento")
AGENDA_PORTAL_STATUSES_CANCELAVEIS = ("Agendado", "Reservado", "Confirmado")


def _exigir_sessao_clinica_portal(
    db: Session,
    portal_session: PortalSessionContext,
    *,
    permissao: str = PORTAL_PERMISSION_CLINIC_READ,
) -> Clinica:
    """Sessao de clinica ativa, com a permissao pedida.

    O default e `clinic:read` de proposito: hoje quem usa este helper sao os
    endpoints de gestao da unidade (agenda, financeiro, recibo), e o default
    seguro evita que um endpoint novo nasca sem conferencia nenhuma. Endpoint de
    clinica que deva valer tambem para sessao de menos poder passa `permissao`
    explicitamente - e a escolha fica visivel no call site.
    """
    if portal_session.actor_type != "clinica" or portal_session.clinica_id is None:
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso para clinica.")
    _assert_portal_scope(portal_session, permissao)
    clinica = _obter_clinica_ativa(db, portal_session.clinica_id)
    if not clinica:
        raise HTTPException(status_code=403, detail="Clinica sem acesso ativo ao portal.")
    return clinica


def _build_portal_agendamento_item(agendamento: Agendamento) -> PortalClinicaAgendamentoItemResponse:
    status_atual = str(agendamento.status or "")
    return PortalClinicaAgendamentoItemResponse(
        id=agendamento.id,
        data=agendamento.data,
        hora=agendamento.hora,
        inicio=agendamento.inicio,
        fim=agendamento.fim,
        status=status_atual,
        paciente_nome=agendamento.paciente,
        tutor_nome=agendamento.tutor,
        servico_nome=agendamento.servico,
        pode_cancelar=status_atual in AGENDA_PORTAL_STATUSES_CANCELAVEIS,
    )


@router.get("/clinicas/agendamentos", response_model=PortalClinicaAgendamentoListResponse)
def listar_agendamentos_clinica_portal(
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    clinica = _exigir_sessao_clinica_portal(db, portal_session)

    agendamentos = (
        db.query(Agendamento)
        .filter(Agendamento.clinica_id == clinica.id)
        .filter(Agendamento.status.in_(AGENDA_PORTAL_STATUSES_VISIVEIS))
        .order_by(Agendamento.inicio.asc())
        .limit(200)
        .all()
    )

    return PortalClinicaAgendamentoListResponse(
        total=len(agendamentos),
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
        items=[_build_portal_agendamento_item(agendamento) for agendamento in agendamentos],
    )


@router.patch(
    "/clinicas/agendamentos/{agendamento_id}/cancelar",
    response_model=PortalClinicaAgendamentoCancelResponse,
)
def cancelar_agendamento_clinica_portal(
    agendamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    clinica = _exigir_sessao_clinica_portal(db, portal_session)
    _adquirir_lock_escrita_agenda(db)

    agendamento = (
        db.query(Agendamento)
        .filter(Agendamento.id == agendamento_id, Agendamento.clinica_id == clinica.id)
        .first()
    )
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    status_atual = str(agendamento.status or "")
    if status_atual not in AGENDA_PORTAL_STATUSES_CANCELAVEIS:
        raise HTTPException(
            status_code=409,
            detail=(
                "Este agendamento nao pode ser cancelado pelo portal no status atual "
                f"({status_atual or 'desconhecido'}). Entre em contato com a Fort Cordis."
            ),
        )

    nota_portal = (
        f"[Portal] Cancelado pela clinica parceira ({clinica.nome}) em "
        f"{_utcnow().strftime('%d/%m/%Y %H:%M')} UTC."
    )
    observacoes_atuais = str(agendamento.observacoes or "").strip()
    agendamento.observacoes = "\n".join(filter(None, [observacoes_atuais, nota_portal]))
    agendamento.status = "Cancelado"

    detalhes_agendamento = " | ".join(
        filter(
            None,
            [
                f"Data: {agendamento.data} {agendamento.hora}".strip() if agendamento.data else None,
                f"Paciente: {agendamento.paciente}" if agendamento.paciente else None,
                f"Servico: {agendamento.servico}" if agendamento.servico else None,
            ],
        )
    )
    criar_alerta_interno(
        db,
        tipo="agendamento_cancelado_portal",
        nivel="aviso",
        titulo=f"Cancelamento pelo portal: {clinica.nome}",
        mensagem=(
            f"A clinica {clinica.nome} cancelou o agendamento #{agendamento.id} pelo portal."
            + (f" {detalhes_agendamento}." if detalhes_agendamento else "")
        ),
        entidade_tipo="agendamento",
        entidade_id=agendamento.id,
        clinica_id=clinica.id,
    )

    # O alerta interno e criado na MESMA transacao do cancelamento (ver
    # alerta_interno_service.criar_alerta_interno) para garantir que nunca exista um
    # cancelamento "bem-sucedido" sem o aviso correspondente para a equipe.
    db.commit()
    db.refresh(agendamento)

    registrar_auditoria(
        current_user=None,
        modulo="portal_clinica",
        entidade="Agendamento",
        acao="cancelar",
        descricao=f"Agendamento #{agendamento.id} cancelado pela clinica parceira via portal.",
        entidade_id=agendamento.id,
        detalhes={
            "clinica_id": clinica.id,
            "clinica_nome": clinica.nome,
            "status_anterior": status_atual,
            "portal_actor_id": portal_session.actor_id,
        },
        request=request,
    )

    return PortalClinicaAgendamentoCancelResponse(
        item=_build_portal_agendamento_item(agendamento),
        message="Agendamento cancelado com sucesso.",
    )


FINANCEIRO_PORTAL_PENDENTES_LIMIT = 200
FINANCEIRO_PORTAL_PAGAS_LIMIT = 50


def _build_portal_os_item(
    ordem: OrdemServico,
    paciente_nome: str | None,
    servico_nome: str | None,
) -> PortalClinicaOrdemServicoItemResponse:
    return PortalClinicaOrdemServicoItemResponse(
        id=ordem.id,
        numero_os=ordem.numero_os,
        status=str(ordem.status or ""),
        valor=float(ordem.valor_final or 0),
        data_atendimento=ordem.data_atendimento,
        paciente_nome=paciente_nome,
        servico_nome=servico_nome,
    )


@router.get("/clinicas/financeiro", response_model=PortalClinicaFinanceiroResponse)
def obter_financeiro_clinica_portal(
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    clinica = _exigir_sessao_clinica_portal(db, portal_session)

    base_query = (
        db.query(OrdemServico, Paciente.nome, Servico.nome)
        .outerjoin(Paciente, Paciente.id == OrdemServico.paciente_id)
        .outerjoin(Servico, Servico.id == OrdemServico.servico_id)
        .filter(OrdemServico.clinica_id == clinica.id)
    )

    pendentes_rows = (
        base_query.filter(OrdemServico.status == "Pendente")
        .order_by(OrdemServico.id.desc())
        .limit(FINANCEIRO_PORTAL_PENDENTES_LIMIT)
        .all()
    )
    pagas_rows = (
        base_query.filter(OrdemServico.status == "Pago")
        .order_by(OrdemServico.id.desc())
        .limit(FINANCEIRO_PORTAL_PAGAS_LIMIT)
        .all()
    )

    def _agregados(status_os: str) -> tuple[float, int]:
        total, quantidade = (
            db.query(
                func.coalesce(func.sum(OrdemServico.valor_final), 0),
                func.count(OrdemServico.id),
            )
            .filter(OrdemServico.clinica_id == clinica.id, OrdemServico.status == status_os)
            .one()
        )
        return float(total or 0), int(quantidade or 0)

    total_pendente, quantidade_pendente = _agregados("Pendente")
    total_pago, quantidade_pago = _agregados("Pago")

    return PortalClinicaFinanceiroResponse(
        clinica_id=clinica.id,
        clinica_nome=clinica.nome,
        summary=PortalClinicaFinanceiroSummaryResponse(
            total_pendente=total_pendente,
            total_pago=total_pago,
            quantidade_pendente=quantidade_pendente,
            quantidade_pago=quantidade_pago,
        ),
        pendentes=[_build_portal_os_item(o, nome_p, nome_s) for o, nome_p, nome_s in pendentes_rows],
        pagas=[_build_portal_os_item(o, nome_p, nome_s) for o, nome_p, nome_s in pagas_rows],
    )


@router.get("/clinicas/ordens-servico/{ordem_servico_id}/recibo")
def baixar_recibo_os_clinica_portal(
    ordem_servico_id: int,
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    clinica = _exigir_sessao_clinica_portal(db, portal_session)

    ordem_existe = (
        db.query(OrdemServico.id)
        .filter(
            OrdemServico.id == ordem_servico_id,
            OrdemServico.clinica_id == clinica.id,
            OrdemServico.status == "Pago",
        )
        .first()
    )
    if not ordem_existe:
        raise HTTPException(status_code=404, detail="Ordem de servico nao encontrada.")

    recibos = _montar_recibos_os(db, [ordem_servico_id])
    if not recibos:
        raise HTTPException(status_code=404, detail="Ordem de servico nao encontrada.")

    dados_empresa = _carregar_dados_emissor_recibo_empresa(db)
    pdf_bytes = _gerar_pdf_recibos_ordens(
        recibos=recibos,
        nome_empresa=dados_empresa["nome_empresa"],
        contato_empresa=dados_empresa["contato_empresa"],
        texto_rodape=dados_empresa["texto_rodape"],
        agrupar=False,
        nome_emitente=dados_empresa["nome_empresa"],
        crmv_emitente="",
        assinatura_emitente_dados=dados_empresa["assinatura_emitente"],
        logomarca_dados=dados_empresa["logomarca"],
    )

    filename = f"recibo_os_{recibos[0]['numero_os']}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/parceiros/exames", response_model=PortalExamListResponse)
def listar_exames_parceiro_portal(
    q: str | None = Query(default=None, max_length=120),
    pet: str | None = Query(default=None, max_length=120),
    tutor: str | None = Query(default=None, max_length=120),
    especie: str | None = Query(default=None, max_length=80),
    tipo_exame: str | None = Query(default=None, max_length=120),
    status_exame: str | None = Query(default=None, max_length=80),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    sort_by: str = Query(default="data", pattern="^(data|tipo_exame|especie|pet|tutor|status)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    if portal_session.actor_type != "parceiro":
        raise HTTPException(status_code=403, detail="Sessao do portal sem acesso para parceiro externo.")
    _assert_portal_scope(portal_session, PORTAL_PERMISSION_EXAM_READ)

    partner = _load_active_partner_for_session(db, portal_session)
    query = (
        db.query(Exame)
        .join(
            PortalPartnerReleaseTarget,
            PortalPartnerReleaseTarget.exame_id == Exame.id,
        )
        .outerjoin(AtendimentoClinico, AtendimentoClinico.id == Exame.atendimento_id)
        .outerjoin(Laudo, Laudo.id == Exame.laudo_id)
        .join(Paciente, Paciente.id == Exame.paciente_id)
        .outerjoin(Tutor, Tutor.id == Paciente.tutor_id)
        .filter(PortalPartnerReleaseTarget.partner_id == partner.id)
        .filter(PortalPartnerReleaseTarget.revoked_at.is_(None))
        .filter(_portal_exam_release_filter())
    )

    def _like(value: str) -> str:
        return f"%{value.strip()}%"

    if q and q.strip():
        term = _like(q)
        query = query.filter(
            or_(
                Paciente.nome.ilike(term),
                Tutor.nome.ilike(term),
                Exame.tipo_exame.ilike(term),
                Exame.categoria_exame.ilike(term),
            )
        )
    if pet and pet.strip():
        query = query.filter(Paciente.nome.ilike(_like(pet)))
    if tutor and tutor.strip():
        query = query.filter(Tutor.nome.ilike(_like(tutor)))
    if especie and especie.strip():
        query = query.filter(Paciente.especie.ilike(_like(especie)))
    if tipo_exame and tipo_exame.strip():
        query = query.filter(Exame.tipo_exame.ilike(_like(tipo_exame)))
    if status_exame and status_exame.strip():
        query = query.filter(Exame.status.ilike(_like(status_exame)))
    if data_inicio and data_fim and data_inicio > data_fim:
        raise HTTPException(status_code=422, detail="data_inicio nao pode ser maior que data_fim.")

    effective_data_fim = data_fim or data_inicio
    date_expr = _portal_exam_date_expression()
    if data_inicio:
        query = query.filter(date_expr >= _date_start(data_inicio))
    if effective_data_fim:
        query = query.filter(date_expr < _date_end_exclusive(effective_data_fim))

    total = query.count()
    sort_expr = _portal_exam_sort_expression(sort_by)
    primary_order = sort_expr.asc() if sort_dir == "asc" else sort_expr.desc()
    exams = query.order_by(primary_order, Exame.id.desc()).offset(offset).limit(limit).all()

    attachments_by_exam, pacientes_map, tutores_map, laudos_map = _load_exam_related_maps(db, exams)
    items = [
        _build_exam_summary(
            exam,
            attachments_by_exam.get(exam.id, []),
            pacientes_map.get(exam.paciente_id),
            tutores_map.get(getattr(pacientes_map.get(exam.paciente_id), "tutor_id", None)),
            laudos_map.get(exam.laudo_id) if exam.laudo_id else None,
        )
        for exam in exams
    ]

    return PortalExamListResponse(
        total=total,
        partner_id=partner.id,
        partner_nome=partner.nome_exibicao,
        partner_tipo=partner.tipo,
        partner_tipo_label=_partner_label(partner.tipo),
        items=items,
    )


@router.get("/pets/{paciente_id}/exames", response_model=PortalExamListResponse)
def listar_exames_pet_portal(
    paciente_id: int,
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    # Atende tutor, clinica e parceiro - por isso a permissao pedida e `exam:read`,
    # comum aos tres, e nao a permissao especifica de cada ator.
    _assert_portal_scope(portal_session, PORTAL_PERMISSION_EXAM_READ)
    if portal_session.actor_type == "tutor":
        _assert_tutor_scope(db, portal_session, paciente_id)

    exams = (
        db.query(Exame)
        .outerjoin(Laudo, Laudo.id == Exame.laudo_id)
        .filter(Exame.paciente_id == paciente_id)
        .filter(_portal_exam_release_filter())
        .order_by(_portal_exam_date_expression().desc(), Exame.id.desc())
        .all()
    )

    attachments_by_exam, pacientes_map, tutores_map, laudos_map = _load_exam_related_maps(db, exams)
    atendimentos_map = _load_map(db, AtendimentoClinico, [exam.atendimento_id for exam in exams if exam.atendimento_id])

    items: list[PortalExamSummaryResponse] = []
    for exam in exams:
        if portal_session.actor_type == "clinica":
            try:
                _assert_clinica_scope_for_exam(portal_session, exam, atendimentos_map, laudos_map)
            except HTTPException:
                continue
        if portal_session.actor_type == "parceiro":
            try:
                _assert_partner_scope_for_exam(db, portal_session, exam.id)
            except HTTPException:
                continue
        paciente = pacientes_map.get(exam.paciente_id)
        tutor = tutores_map.get(getattr(paciente, "tutor_id", None))
        items.append(
            _build_exam_summary(
                exam,
                attachments_by_exam.get(exam.id, []),
                paciente,
                tutor,
                laudos_map.get(exam.laudo_id) if exam.laudo_id else None,
            )
        )

    response = PortalExamListResponse(total=len(items), clinica_id=portal_session.clinica_id, items=items)
    if portal_session.actor_type == "parceiro":
        partner = _load_active_partner_for_session(db, portal_session)
        response.partner_id = partner.id
        response.partner_nome = partner.nome_exibicao
        response.partner_tipo = partner.tipo
        response.partner_tipo_label = _partner_label(partner.tipo)
    return response


@router.post("/exames/{exame_id}/download-url", response_model=PortalDownloadUrlResponse)
def gerar_download_url_exame_portal(
    exame_id: int,
    db: Session = Depends(get_db),
    portal_session: PortalSessionContext = Depends(get_current_portal_session),
):
    _assert_portal_scope(portal_session, PORTAL_PERMISSION_EXAM_DOWNLOAD)
    exam, atendimentos_map, laudos_map = _load_exam_with_context(db, exame_id)
    _assert_portal_exam_access(db, portal_session, exam, atendimentos_map, laudos_map)

    attachments = (
        db.query(AnexoAtendimento)
        .filter(AnexoAtendimento.exame_id == exam.id)
        .order_by(AnexoAtendimento.created_at.desc(), AnexoAtendimento.id.desc())
        .all()
    )

    items: list[PortalDownloadLinkItemResponse] = []
    for attachment in attachments:
        if not attachment_has_download_source(attachment):
            continue
        download_token, expires_at = create_portal_download_token(
            portal_session,
            exame_id=exam.id,
            anexo_id=attachment.id,
        )
        items.append(
            PortalDownloadLinkItemResponse(
                anexo_id=attachment.id,
                nome_original=attachment.nome_original or f"anexo_{attachment.id}",
                mime_type=attachment.mime_type or "application/octet-stream",
                download_url=f"/api/v1/portal/anexos/{attachment.id}/arquivo",
                download_token=download_token,
                download_token_header=PORTAL_DOWNLOAD_TOKEN_HEADER,
                expires_at=expires_at,
            )
        )

    if not items:
        raise HTTPException(status_code=404, detail="Nenhum anexo disponivel para este exame.")

    return PortalDownloadUrlResponse(exame_id=exam.id, items=items)


@router.get("/anexos/{anexo_id}/arquivo")
def baixar_arquivo_anexo_portal(
    anexo_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    attachment = db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Anexo nao encontrado.")

    download_context: PortalDownloadContext | None = None
    actor_type = None
    actor_id = None
    clinica_id = None
    account_id = None
    raw_download_token = (request.headers.get(PORTAL_DOWNLOAD_TOKEN_HEADER) or "").strip()
    if raw_download_token:
        download_context = get_current_portal_download_token(request)
        if download_context.anexo_id != anexo_id:
            raise HTTPException(status_code=403, detail="Token de download sem acesso a este anexo.")
        if attachment.exame_id is None or download_context.exame_id != attachment.exame_id:
            raise HTTPException(status_code=403, detail="Token de download sem acesso a este anexo.")
        actor_type = download_context.actor_type
        actor_id = download_context.actor_id
        clinica_id = download_context.clinica_id
    else:
        portal_session = get_current_portal_session(request)
        # So o caminho por sessao confere escopo: o token de download nao carrega
        # `scope` (PortalDownloadContext nao tem o campo) e ja nasce preso ao par
        # (exame, anexo), conferido logo acima.
        _assert_portal_scope(portal_session, PORTAL_PERMISSION_EXAM_DOWNLOAD)
        if attachment.exame_id is None:
            raise HTTPException(status_code=403, detail="Anexo sem exame associado para o portal.")
        exam, atendimentos_map, laudos_map = _load_exam_with_context(db, int(attachment.exame_id))
        _assert_portal_exam_access(db, portal_session, exam, atendimentos_map, laudos_map)
        actor_type = portal_session.actor_type
        actor_id = portal_session.actor_id
        clinica_id = portal_session.clinica_id
        account_id = portal_session.account_id

    _marcar_exame_visualizado_no_portal(db, attachment.exame_id, actor_type, actor_id)

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="anexo_atendimento",
        acao="PORTAL_DOWNLOAD_ARQUIVO",
        descricao="Download de anexo do portal realizado.",
        entidade_id=anexo_id,
        detalhes={
            "exame_id": attachment.exame_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "clinica_id": clinica_id,
            "account_id": account_id,
            "via_download_token": bool(download_context),
        },
        request=request,
    )

    return build_attachment_download_response(
        attachment,
        missing_detail="Arquivo do anexo nao encontrado.",
    )
