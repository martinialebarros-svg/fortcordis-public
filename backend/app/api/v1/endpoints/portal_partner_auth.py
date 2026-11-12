from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_papel
from app.db.database import get_db
from app.models.portal_partner import PORTAL_PARTNER_TYPE_VETERINARIO, PortalPartnerProfile
from app.models.portal_partner_auth import (
    PortalPartnerAccount,
    PortalPartnerAuthChallenge,
    PortalPartnerInvite,
)
from app.models.user import User
from app.schemas.portal import (
    PortalPartnerActivationRequest,
    PortalPartnerActivationResponse,
    PortalPartnerAuthResponse,
    PortalPartnerInviteCreateRequest,
    PortalPartnerInviteResponse,
    PortalPartnerInviteStatusResponse,
    PortalPartnerLoginRequest,
    PortalPartnerMfaVerifyRequest,
    PortalPartnerPasswordResetConfirmRequest,
    PortalPartnerPasswordResetRequest,
    PortalSimpleAcceptedResponse,
)
from app.services.auditoria_service import registrar_auditoria
from app.services.portal_clinic_auth_service import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_LOCKED,
    ACCOUNT_STATUS_PENDING,
    ACCOUNT_STATUS_REVOKED,
    CHALLENGE_TYPE_LOGIN_MFA,
    INVITE_STATUS_PENDING,
    INVITE_STATUS_USED,
    SESSION_STATUS_ACTIVE,
    generate_opaque_token,
    hash_password,
    hash_secret,
    request_user_agent_hash,
    verify_password,
)
from app.services.portal_partner_auth_service import (
    build_partner_activation_url,
    build_partner_password_reset_url,
    build_partner_portal_url,
    clear_partner_refresh_cookie,
    create_or_replace_pending_partner_account,
    create_partner_auth_challenge,
    create_partner_invite,
    create_partner_password_reset_token,
    expire_partner_invite_if_needed,
    get_active_partner_account,
    get_active_partner_or_404,
    get_partner_account_by_email,
    get_partner_account_by_id,
    get_partner_invite_by_raw_token,
    get_partner_password_reset_token,
    get_partner_refresh_cookie,
    get_partner_session_by_refresh_token,
    issue_partner_session,
    json_load_dict,
    logout_partner_session,
    mask_email,
    mask_phone,
    maybe_require_partner_mfa,
    normalize_email,
    partner_allows_invite_flow,
    partner_type_label,
    revoke_partner_session,
    revoke_partner_sessions,
    send_partner_login_mfa_code,
    send_partner_password_reset_email,
    send_partner_whatsapp_invite,
    send_partner_whatsapp_login_access,
    set_partner_refresh_cookie,
    utcnow,
    validate_partner_password_reset_token_or_401,
    verify_partner_auth_challenge_code,
)

router = APIRouter()


def _require_portal_admin(current_user: User = Depends(require_papel("admin"))) -> User:
    return current_user


def _assert_partner_invite_auth_enabled() -> None:
    if not settings.PORTAL_PARTNER_INVITE_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="Fluxo do parceiro externo indisponivel.")


def _assert_partner_password_login_enabled() -> None:
    _assert_partner_invite_auth_enabled()
    if not settings.PORTAL_PARTNER_PASSWORD_LOGIN_ENABLED:
        raise HTTPException(status_code=404, detail="Login do parceiro por senha indisponivel.")


def _generic_reset_response() -> PortalSimpleAcceptedResponse:
    return PortalSimpleAcceptedResponse(
        message="Se existir uma conta ativa para este email, enviaremos as instrucoes de redefinicao.",
    )


def _login_result_response(
    result,
    *,
    message: str | None = None,
) -> PortalPartnerAuthResponse:
    return PortalPartnerAuthResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        actor_type="parceiro",
        actor_id=result.partner_id,
        partner_id=result.partner_id,
        partner_nome=result.partner_nome,
        partner_tipo=result.partner_tipo,
        partner_tipo_label=result.partner_tipo_label,
        clinica_id=result.clinica_id,
        account_id=result.account_id,
        auth_method=result.auth_method,
        trusted_session_expires_at=result.trusted_session_expires_at,
        scope=result.scope,
        message=message,
    )


@router.post("/parceiros/{partner_id}/convites", response_model=PortalPartnerInviteResponse)
def criar_convite_parceiro_externo(
    partner_id: int,
    payload: PortalPartnerInviteCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    _assert_partner_invite_auth_enabled()
    partner = get_active_partner_or_404(
        db,
        partner_id,
        allowed_types={PORTAL_PARTNER_TYPE_VETERINARIO},
    )
    if not partner_allows_invite_flow(partner):
        raise HTTPException(status_code=409, detail="Use o fluxo da clinica parceira para este perfil.")
    if not partner.email_login:
        raise HTTPException(status_code=422, detail="Defina o email de login do parceiro antes de gerar convite.")

    active_account = get_active_partner_account(db, partner.id)
    if active_account and normalize_email(active_account.email_normalized) != normalize_email(partner.email_login):
        raise HTTPException(
            status_code=409,
            detail="O parceiro ja possui acesso ativo com outro email. Revogue a conta atual antes de trocar o email.",
        )

    invite = None
    access_mode = "activation"
    access_url: str
    account_email_masked: str | None

    if active_account and active_account.status == ACCOUNT_STATUS_ACTIVE:
        access_mode = "login"
        access_url = build_partner_portal_url(request)
        account_email_masked = mask_email(active_account.email_normalized)
    else:
        invite, raw_token = create_partner_invite(
            db,
            partner_id=partner.id,
            delivery_channel=payload.delivery_channel,
            delivery_target=payload.delivery_target,
            expires_in_hours=payload.expires_in_hours,
            created_by_user_id=current_user.id,
        )
        access_url = build_partner_activation_url(request, raw_token)
        account_email_masked = mask_email(partner.email_login)

    delivery_status = "manual_copy"
    delivery_provider = None

    if settings.PORTAL_WHATSAPP_ENABLED:
        try:
            if access_mode == "login":
                result = send_partner_whatsapp_login_access(
                    destination=payload.delivery_target,
                    partner_nome=partner.nome_exibicao,
                    portal_url=access_url,
                    account_email=normalize_email(active_account.email_normalized),
                )
            else:
                result = send_partner_whatsapp_invite(
                    destination=payload.delivery_target,
                    partner_nome=partner.nome_exibicao,
                    activation_url=access_url,
                    expires_in_hours=payload.expires_in_hours,
                )
            if invite is not None:
                invite.delivered_at = utcnow()
                db.commit()
            delivery_status = "sent"
            delivery_provider = result.provider
        except Exception:
            if not payload.allow_manual_copy:
                raise HTTPException(
                    status_code=502,
                    detail="Nao foi possivel enviar o convite do parceiro por WhatsApp.",
                )
    elif not payload.allow_manual_copy:
        raise HTTPException(
            status_code=400,
            detail="Envio automatico por WhatsApp indisponivel neste ambiente.",
        )

    registrar_auditoria(
        current_user=current_user,
        modulo="portal",
        entidade="portal_partner_account" if access_mode == "login" else "portal_partner_invite",
        acao="PORTAL_PARTNER_ACCESS_REMINDER_SENT" if access_mode == "login" else "PORTAL_PARTNER_INVITE_CREATED",
        descricao="Acesso do parceiro externo reenviado." if access_mode == "login" else "Convite do parceiro externo criado.",
        entidade_id=active_account.id if access_mode == "login" else invite.id,
        detalhes={
            "partner_id": partner.id,
            "partner_tipo": partner.tipo,
            "delivery_channel": payload.delivery_channel,
            "delivery_status": delivery_status,
            "access_mode": access_mode,
        },
        request=request,
    )
    return PortalPartnerInviteResponse(
        invite_id=invite.id if invite is not None else None,
        status=active_account.status if access_mode == "login" else invite.status,
        expires_at=invite.expires_at if invite is not None else None,
        activation_url=access_url,
        access_mode=access_mode,
        delivery_channel=payload.delivery_channel,
        delivery_target_masked=mask_phone(payload.delivery_target),
        account_email_masked=account_email_masked,
        delivery_status=delivery_status,
        delivery_provider=delivery_provider,
    )


@router.get("/parceiros/convites/{invite_token}", response_model=PortalPartnerInviteStatusResponse)
def consultar_convite_parceiro(
    invite_token: str,
    db: Session = Depends(get_db),
):
    _assert_partner_invite_auth_enabled()
    invite = get_partner_invite_by_raw_token(db, invite_token)
    if not invite:
        raise HTTPException(status_code=404, detail="Convite do parceiro nao encontrado.")
    partner = get_active_partner_or_404(db, invite.partner_id, allowed_types={PORTAL_PARTNER_TYPE_VETERINARIO})
    account = get_active_partner_account(db, partner.id)
    email_hint = mask_email(account.email_normalized) if account else mask_email(partner.email_login)
    return PortalPartnerInviteStatusResponse(
        status=invite.status,
        partner_id=partner.id,
        partner_nome=partner.nome_exibicao,
        partner_tipo=partner.tipo,
        partner_tipo_label=partner_type_label(partner.tipo),
        expires_at=invite.expires_at,
        can_activate=invite.status == INVITE_STATUS_PENDING and not expire_partner_invite_if_needed(db, invite),
        email_hint=email_hint,
    )


@router.post("/parceiros/ativacao", response_model=PortalPartnerActivationResponse)
def ativar_conta_parceiro(
    payload: PortalPartnerActivationRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_partner_invite_auth_enabled()
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="A confirmacao de senha nao confere.")

    invite = get_partner_invite_by_raw_token(db, payload.invite_token)
    if not invite:
        raise HTTPException(status_code=404, detail="Convite do parceiro nao encontrado.")
    if expire_partner_invite_if_needed(db, invite) or invite.status != INVITE_STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Convite do parceiro indisponivel para ativacao.")

    partner = get_active_partner_or_404(db, invite.partner_id, allowed_types={PORTAL_PARTNER_TYPE_VETERINARIO})
    if not partner.email_login:
        raise HTTPException(status_code=422, detail="Defina o email de login do parceiro antes da ativacao.")

    account = create_or_replace_pending_partner_account(
        db,
        partner_id=partner.id,
        email=partner.email_login,
        responsavel_nome=payload.responsavel_nome,
        password=payload.password,
    )
    now = utcnow()
    account.status = ACCOUNT_STATUS_ACTIVE
    account.email_verified_at = now
    account.activated_at = now
    account.force_mfa_on_next_login = False
    invite.status = INVITE_STATUS_USED
    invite.used_at = now
    db.commit()

    result = issue_partner_session(
        db,
        account=account,
        partner=partner,
        request=request,
        remember_device_until_shift_end=True,
        auth_reference=f"invite:{invite.id}:{account.id}:{int(datetime.utcnow().timestamp())}",
        auth_method="invite_activation",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_partner_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )
    account.last_login_at = utcnow()
    db.commit()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_account",
        acao="PORTAL_PARTNER_ACCOUNT_ACTIVATED_BY_INVITE",
        descricao="Conta do parceiro ativada por convite seguro.",
        entidade_id=account.id,
        detalhes={
            "partner_id": partner.id,
            "partner_tipo": partner.tipo,
            "invite_id": invite.id,
            "auto_session": True,
        },
        request=request,
    )
    return PortalPartnerActivationResponse(
        activation_id=account.id,
        access_token=result.access_token,
        expires_at=result.expires_at,
        actor_type="parceiro",
        actor_id=result.partner_id,
        partner_id=result.partner_id,
        partner_nome=result.partner_nome,
        partner_tipo=result.partner_tipo,
        partner_tipo_label=result.partner_tipo_label,
        clinica_id=result.clinica_id,
        account_id=result.account_id,
        auth_method=result.auth_method,
        trusted_session_expires_at=result.trusted_session_expires_at,
        scope=result.scope,
        message="Conta do parceiro criada com sucesso. Acesso liberado neste computador.",
    )


@router.post("/parceiros/auth/login", response_model=PortalPartnerAuthResponse)
def login_parceiro_com_senha(
    payload: PortalPartnerLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    account = get_partner_account_by_email(db, payload.email)
    if not account or account.status not in {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED}:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")
    if account.status == ACCOUNT_STATUS_REVOKED:
        raise HTTPException(status_code=403, detail="Conta do parceiro indisponivel.")
    if account.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Email de login ainda nao verificado.")
    if not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")

    partner = get_active_partner_or_404(db, account.partner_id)
    if maybe_require_partner_mfa(account, remember_device_until_shift_end=payload.remember_device_until_shift_end):
        challenge, raw_code = create_partner_auth_challenge(
            db,
            account_id=account.id,
            partner_id=partner.id,
            challenge_type=CHALLENGE_TYPE_LOGIN_MFA,
            context={"remember_device_until_shift_end": payload.remember_device_until_shift_end},
            expires_minutes=settings.PORTAL_CLINIC_MFA_EXPIRE_MINUTES,
        )
        try:
            send_partner_login_mfa_code(
                destination=account.email_normalized,
                responsavel_nome=account.responsavel_nome,
                partner_nome=partner.nome_exibicao,
                code=raw_code,
                expires_in_minutes=settings.PORTAL_CLINIC_MFA_EXPIRE_MINUTES,
            )
        except Exception:
            challenge.status = "expired"
            db.commit()
            raise HTTPException(
                status_code=502,
                detail="Nao foi possivel enviar o codigo adicional de acesso.",
            )

        registrar_auditoria(
            current_user=None,
            modulo="portal",
            entidade="portal_partner_auth_challenge",
            acao="PORTAL_PARTNER_MFA_CHALLENGE_CREATED",
            descricao="Codigo adicional de login do parceiro emitido.",
            entidade_id=challenge.challenge_id,
            detalhes={"partner_id": partner.id, "account_id": account.id},
            request=request,
        )
        clear_partner_refresh_cookie(response, request)
        return PortalPartnerAuthResponse(
            mfa_required=True,
            challenge_id=challenge.challenge_id,
            message="Enviamos um codigo adicional para o email do parceiro.",
        )

    result = issue_partner_session(
        db,
        account=account,
        partner=partner,
        request=request,
        remember_device_until_shift_end=payload.remember_device_until_shift_end,
        auth_reference=f"login:{account.id}:{int(datetime.utcnow().timestamp())}",
        auth_method="password",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_partner_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )
    else:
        clear_partner_refresh_cookie(response, request)
    account.last_login_at = utcnow()
    db.commit()
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_account",
        acao="PORTAL_PARTNER_PASSWORD_LOGIN_SUCCEEDED",
        descricao="Login do parceiro por email e senha concluido.",
        entidade_id=account.id,
        detalhes={"partner_id": partner.id, "partner_tipo": partner.tipo},
        request=request,
    )
    return _login_result_response(result, message="Sessao do parceiro iniciada com sucesso.")


@router.post("/parceiros/auth/mfa/verificar", response_model=PortalPartnerAuthResponse)
def verificar_mfa_parceiro(
    payload: PortalPartnerMfaVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    challenge = (
        db.query(PortalPartnerAuthChallenge)
        .filter(PortalPartnerAuthChallenge.challenge_id == payload.challenge_id)
        .first()
    )
    if not challenge or challenge.challenge_type != CHALLENGE_TYPE_LOGIN_MFA:
        raise HTTPException(status_code=401, detail="Codigo invalido ou expirado.")

    verify_partner_auth_challenge_code(db, challenge=challenge, code=payload.codigo)
    account = get_partner_account_by_id(db, challenge.account_id)
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="Conta do parceiro indisponivel.")
    partner = get_active_partner_or_404(db, challenge.partner_id)

    result = issue_partner_session(
        db,
        account=account,
        partner=partner,
        request=request,
        remember_device_until_shift_end=payload.remember_device_until_shift_end,
        auth_reference=challenge.challenge_id,
        auth_method="password_mfa",
    )
    if result.refresh_token and result.trusted_session_expires_at:
        set_partner_refresh_cookie(
            response,
            result.refresh_token,
            expires_at=result.trusted_session_expires_at,
            request=request,
        )

    account.last_login_at = utcnow()
    account.force_mfa_on_next_login = False
    db.commit()
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_account",
        acao="PORTAL_PARTNER_MFA_LOGIN_VERIFIED",
        descricao="Login do parceiro confirmado por MFA.",
        entidade_id=account.id,
        detalhes={"partner_id": partner.id, "trusted_session": bool(result.refresh_token)},
        request=request,
    )
    return _login_result_response(result, message="Sessao do parceiro iniciada com sucesso.")


@router.post("/parceiros/auth/refresh", response_model=PortalPartnerAuthResponse)
def refresh_login_parceiro(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    raw_refresh_token = get_partner_refresh_cookie(request)
    session = get_partner_session_by_refresh_token(db, raw_refresh_token)
    if not session or session.status != SESSION_STATUS_ACTIVE:
        clear_partner_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao do parceiro expirada.")

    current_user_agent_hash = request_user_agent_hash(request)
    if session.user_agent_hash and current_user_agent_hash and session.user_agent_hash != current_user_agent_hash:
        revoke_partner_session(db, session, reason="mudanca-de-dispositivo")
        clear_partner_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao do parceiro expirada.")

    account = get_partner_account_by_id(db, session.account_id)
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        revoke_partner_session(db, session, reason="conta-inativa")
        clear_partner_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Sessao do parceiro expirada.")
    partner = get_active_partner_or_404(db, session.partner_id)

    new_raw_refresh_token = generate_opaque_token()
    session.refresh_token_hash = hash_secret("portal_partner_refresh", new_raw_refresh_token)
    session.last_seen_at = utcnow()
    db.commit()

    result = issue_partner_session(
        db,
        account=account,
        partner=partner,
        request=request,
        remember_device_until_shift_end=False,
        auth_reference=f"session:{session.id}",
        auth_method="refresh",
    )
    set_partner_refresh_cookie(
        response,
        new_raw_refresh_token,
        expires_at=session.trusted_until,
        request=request,
    )
    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_session",
        acao="PORTAL_PARTNER_SESSION_REFRESHED",
        descricao="Sessao do parceiro renovada via refresh seguro.",
        entidade_id=session.id,
        detalhes={"partner_id": session.partner_id, "account_id": session.account_id},
        request=request,
    )
    return _login_result_response(result, message="Sessao do parceiro renovada.")


@router.post("/parceiros/auth/logout", response_model=PortalSimpleAcceptedResponse)
def logout_parceiro(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    raw_refresh_token = get_partner_refresh_cookie(request)
    if raw_refresh_token:
        logout_partner_session(db, raw_refresh_token=raw_refresh_token)
    clear_partner_refresh_cookie(response, request)
    return PortalSimpleAcceptedResponse(message="Sessao do parceiro encerrada neste dispositivo.")


@router.post("/parceiros/auth/esqueci-senha", response_model=PortalSimpleAcceptedResponse)
def esqueci_senha_parceiro(
    payload: PortalPartnerPasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    account = get_partner_account_by_email(db, payload.email)
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        return _generic_reset_response()

    partner = get_active_partner_or_404(db, account.partner_id)
    _, raw_reset_token = create_partner_password_reset_token(db, account_id=account.id)
    reset_url = build_partner_password_reset_url(request, raw_reset_token)
    try:
        send_partner_password_reset_email(
            destination=account.email_normalized,
            responsavel_nome=account.responsavel_nome,
            partner_nome=partner.nome_exibicao,
            reset_url=reset_url,
            expires_in_minutes=settings.PORTAL_CLINIC_PASSWORD_RESET_EXPIRE_MINUTES,
        )
    except Exception:
        return _generic_reset_response()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_account",
        acao="PORTAL_PARTNER_PASSWORD_RESET_REQUESTED",
        descricao="Solicitacao de redefinicao de senha do parceiro recebida.",
        entidade_id=account.id,
        detalhes={"partner_id": partner.id},
        request=request,
    )
    return _generic_reset_response()


@router.post("/parceiros/auth/redefinir-senha", response_model=PortalSimpleAcceptedResponse)
def redefinir_senha_parceiro(
    payload: PortalPartnerPasswordResetConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _assert_partner_password_login_enabled()
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="A confirmacao de senha nao confere.")

    token = validate_partner_password_reset_token_or_401(
        get_partner_password_reset_token(db, payload.reset_token),
    )
    account = get_partner_account_by_id(db, token.account_id)
    if not account or account.status != ACCOUNT_STATUS_ACTIVE:
        raise HTTPException(status_code=401, detail="Link de redefinicao invalido ou expirado.")
    partner = get_active_partner_or_404(db, account.partner_id)

    account.password_hash = hash_password(payload.password)
    account.password_changed_at = utcnow()
    account.force_mfa_on_next_login = True
    token.used_at = utcnow()
    revoke_partner_session_count = revoke_partner_sessions(
        db,
        partner_id=partner.id,
        reason="senha-redefinida",
    )
    db.commit()

    registrar_auditoria(
        current_user=None,
        modulo="portal",
        entidade="portal_partner_account",
        acao="PORTAL_PARTNER_PASSWORD_RESET_CONFIRMED",
        descricao="Senha do parceiro redefinida com sucesso.",
        entidade_id=account.id,
        detalhes={"partner_id": partner.id, "revoked_sessions": revoke_partner_session_count},
        request=request,
    )
    return PortalSimpleAcceptedResponse(
        message="Senha atualizada com sucesso. Use o portal do parceiro para entrar novamente.",
    )
