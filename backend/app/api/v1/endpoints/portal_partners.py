from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_papel
from app.db.database import get_db
from app.models.clinica import Clinica
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_CLINICA,
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
)
from app.models.user import User
from app.schemas.portal import (
    PortalPartnerClinicLinkPayload,
    PortalPartnerClinicLinkResponse,
    PortalPartnerProfileCreateRequest,
    PortalPartnerProfileListResponse,
    PortalPartnerProfileResponse,
    PortalPartnerProfileUpdateRequest,
)

router = APIRouter()


def _require_portal_admin(current_user: User = Depends(require_papel("admin"))) -> User:
    return current_user


def _require_portal_operational_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


def _clean_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_email(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _first_clinic_whatsapp(clinica: Clinica | None) -> str | None:
    if clinica is None:
        return None
    valores = getattr(clinica, "whatsapps", None)
    if isinstance(valores, list):
        for valor in valores:
            texto = _clean_text(valor)
            if texto:
                return texto
    return _clean_text(getattr(clinica, "telefone", None))


def _partner_type_label(tipo: str) -> str:
    if tipo == PORTAL_PARTNER_TYPE_VETERINARIO:
        return "Veterinario parceiro"
    return "Clinica parceira"


def _linked_clinic_by_id(db: Session, clinica_ids: list[int]) -> dict[int, Clinica]:
    if not clinica_ids:
        return {}
    clinicas = db.query(Clinica).filter(Clinica.id.in_(clinica_ids)).all()
    return {clinica.id: clinica for clinica in clinicas}


def _active_clinic_or_404(db: Session, clinica_id: int) -> Clinica:
    clinica = db.query(Clinica).filter(Clinica.id == clinica_id).first()
    if clinica is None or getattr(clinica, "ativo", False) in (False, 0, "0"):
        raise HTTPException(status_code=404, detail="Clinica ativa nao encontrada.")
    return clinica


def _ensure_unique_active_email(
    db: Session,
    *,
    email_login: str | None,
    ativo: bool,
    exclude_partner_id: int | None = None,
) -> None:
    normalized_email = _normalize_email(email_login)
    if not normalized_email or not ativo:
        return

    query = db.query(PortalPartnerProfile).filter(
        PortalPartnerProfile.ativo.is_(True),
        func.lower(PortalPartnerProfile.email_login) == normalized_email,
    )
    if exclude_partner_id is not None:
        query = query.filter(PortalPartnerProfile.id != exclude_partner_id)

    existing = query.first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Ja existe um parceiro externo ativo usando este email de login.",
        )


def _validated_clinic_links(
    db: Session,
    *,
    tipo: str,
    payload_links: list[PortalPartnerClinicLinkPayload] | None,
) -> list[PortalPartnerClinicLinkPayload] | None:
    """Normaliza `clinicas_vinculadas`. `None` significa 'nao mexer nos vinculos'."""
    if payload_links is None:
        return None
    if tipo == PORTAL_PARTNER_TYPE_CLINICA:
        raise HTTPException(
            status_code=422,
            detail="clinicas_vinculadas se aplica somente ao veterinario parceiro.",
        )

    normalized: list[PortalPartnerClinicLinkPayload] = []
    seen: set[int] = set()
    for link in payload_links:
        clinica_id = int(link.clinica_id)
        if clinica_id in seen:
            raise HTTPException(
                status_code=422,
                detail="A mesma clinica foi informada mais de uma vez nos vinculos do veterinario.",
            )
        seen.add(clinica_id)
        _active_clinic_or_404(db, clinica_id)
        normalized.append(
            PortalPartnerClinicLinkPayload(
                clinica_id=clinica_id,
                receber_todos_laudos=bool(link.receber_todos_laudos),
            )
        )
    return normalized


def _replace_clinic_links(
    db: Session,
    *,
    partner_id: int,
    links: list[PortalPartnerClinicLinkPayload],
) -> None:
    """Substitui o conjunto de vinculos do parceiro pelo informado (RF-005)."""
    existing = (
        db.query(PortalPartnerClinicLink)
        .filter(PortalPartnerClinicLink.partner_id == partner_id)
        .all()
    )
    existing_by_clinic = {int(item.clinica_id): item for item in existing}
    desired_by_clinic = {int(link.clinica_id): link for link in links}

    for clinica_id, current in existing_by_clinic.items():
        desired = desired_by_clinic.get(clinica_id)
        if desired is None:
            db.delete(current)
        elif bool(current.receber_todos_laudos) != bool(desired.receber_todos_laudos):
            current.receber_todos_laudos = bool(desired.receber_todos_laudos)

    for clinica_id, desired in desired_by_clinic.items():
        if clinica_id in existing_by_clinic:
            continue
        db.add(
            PortalPartnerClinicLink(
                partner_id=partner_id,
                clinica_id=clinica_id,
                receber_todos_laudos=bool(desired.receber_todos_laudos),
            )
        )


def _clinic_links_by_partner_id(
    db: Session,
    partner_ids: list[int],
) -> dict[int, list[PortalPartnerClinicLink]]:
    """Carrega os vinculos de varios parceiros em uma consulta so (NFR-003)."""
    unique_ids = sorted({int(item) for item in partner_ids if item})
    if not unique_ids:
        return {}

    links = (
        db.query(PortalPartnerClinicLink)
        .filter(PortalPartnerClinicLink.partner_id.in_(unique_ids))
        .all()
    )
    grouped: dict[int, list[PortalPartnerClinicLink]] = {}
    for link in links:
        grouped.setdefault(int(link.partner_id), []).append(link)
    return grouped


def _serialize_partner(
    partner: PortalPartnerProfile,
    *,
    clinicas_by_id: dict[int, Clinica],
    links_by_partner_id: dict[int, list[PortalPartnerClinicLink]] | None = None,
) -> PortalPartnerProfileResponse:
    clinica = clinicas_by_id.get(partner.clinica_id) if partner.clinica_id else None
    links = (links_by_partner_id or {}).get(int(partner.id), [])
    clinicas_vinculadas = [
        PortalPartnerClinicLinkResponse(
            clinica_id=int(link.clinica_id),
            clinica_nome=getattr(clinicas_by_id.get(int(link.clinica_id)), "nome", None),
            receber_todos_laudos=bool(link.receber_todos_laudos),
        )
        for link in sorted(
            links,
            key=lambda item: (
                str(getattr(clinicas_by_id.get(int(item.clinica_id)), "nome", "") or "").lower(),
                int(item.clinica_id),
            ),
        )
    ]
    return PortalPartnerProfileResponse(
        id=partner.id,
        tipo=partner.tipo,
        tipo_label=_partner_type_label(partner.tipo),
        clinica_id=partner.clinica_id,
        clinica_nome=getattr(clinica, "nome", None),
        clinicas_vinculadas=clinicas_vinculadas,
        nome_exibicao=partner.nome_exibicao,
        email_login=partner.email_login,
        telefone=partner.telefone,
        whatsapp=partner.whatsapp,
        cidade_base=partner.cidade_base,
        estado_base=partner.estado_base,
        crmv=partner.crmv,
        cpf_documento=partner.cpf_documento,
        area_atuacao=partner.area_atuacao,
        observacoes=partner.observacoes,
        ativo=bool(partner.ativo),
        created_at=partner.created_at,
        updated_at=partner.updated_at,
    )


def _resolve_create_payload(
    db: Session,
    payload: PortalPartnerProfileCreateRequest,
) -> tuple[dict[str, object], list[PortalPartnerClinicLinkPayload] | None]:
    tipo = payload.tipo
    nome_exibicao = _clean_text(payload.nome_exibicao)
    email_login = _normalize_email(payload.email_login)
    telefone = _clean_text(payload.telefone)
    whatsapp = _clean_text(payload.whatsapp)
    cidade_base = _clean_text(payload.cidade_base)
    estado_base = _clean_text(payload.estado_base)
    crmv = _clean_text(payload.crmv)
    cpf_documento = _clean_text(payload.cpf_documento)
    area_atuacao = _clean_text(payload.area_atuacao)
    observacoes = _clean_text(payload.observacoes)
    ativo = bool(payload.ativo)
    clinica_id = payload.clinica_id

    if tipo == PORTAL_PARTNER_TYPE_CLINICA:
        if clinica_id is None:
            raise HTTPException(status_code=422, detail="clinica_id e obrigatorio para parceiro do tipo clinica.")
        if db.query(PortalPartnerProfile).filter(PortalPartnerProfile.clinica_id == clinica_id).first():
            raise HTTPException(
                status_code=409,
                detail="Esta clinica ja possui um parceiro externo vinculado.",
            )

        clinica = _active_clinic_or_404(db, clinica_id)
        nome_exibicao = nome_exibicao or clinica.nome
        email_login = email_login or _normalize_email(getattr(clinica, "email", None))
        telefone = telefone or _clean_text(getattr(clinica, "telefone", None))
        whatsapp = whatsapp or _first_clinic_whatsapp(clinica)
        cidade_base = cidade_base or _clean_text(getattr(clinica, "cidade", None))
        estado_base = estado_base or _clean_text(getattr(clinica, "estado", None))
        observacoes = observacoes or _clean_text(getattr(clinica, "observacoes", None))
    else:
        if clinica_id is not None:
            raise HTTPException(status_code=422, detail="clinica_id nao se aplica ao tipo veterinario.")
        if not nome_exibicao:
            raise HTTPException(status_code=422, detail="nome_exibicao e obrigatorio para veterinario parceiro.")
        if not email_login:
            raise HTTPException(status_code=422, detail="email_login e obrigatorio para veterinario parceiro.")
        if not cidade_base or not estado_base:
            raise HTTPException(
                status_code=422,
                detail="cidade_base e estado_base sao obrigatorios para veterinario parceiro.",
            )
        if not telefone and not whatsapp:
            raise HTTPException(
                status_code=422,
                detail="Informe ao menos telefone ou whatsapp para veterinario parceiro.",
            )

    clinic_links = _validated_clinic_links(db, tipo=tipo, payload_links=payload.clinicas_vinculadas)
    _ensure_unique_active_email(db, email_login=email_login, ativo=ativo)
    columns = {
        "tipo": tipo,
        "clinica_id": clinica_id,
        "nome_exibicao": nome_exibicao,
        "email_login": email_login,
        "telefone": telefone,
        "whatsapp": whatsapp,
        "cidade_base": cidade_base,
        "estado_base": estado_base,
        "crmv": crmv,
        "cpf_documento": cpf_documento,
        "area_atuacao": area_atuacao,
        "observacoes": observacoes,
        "ativo": ativo,
    }
    return columns, clinic_links


def _resolve_update_payload(
    db: Session,
    partner: PortalPartnerProfile,
    payload: PortalPartnerProfileUpdateRequest,
) -> tuple[dict[str, object], list[PortalPartnerClinicLinkPayload] | None]:
    fields = payload.model_fields_set
    linked_clinic = (
        db.query(Clinica).filter(Clinica.id == partner.clinica_id).first()
        if partner.clinica_id
        else None
    )

    nome_exibicao = partner.nome_exibicao
    if "nome_exibicao" in fields:
        nome_exibicao = _clean_text(payload.nome_exibicao)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            nome_exibicao = nome_exibicao or getattr(linked_clinic, "nome", None)

    email_login = partner.email_login
    if "email_login" in fields:
        email_login = _normalize_email(payload.email_login)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            email_login = email_login or _normalize_email(getattr(linked_clinic, "email", None))

    telefone = partner.telefone
    if "telefone" in fields:
        telefone = _clean_text(payload.telefone)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            telefone = telefone or _clean_text(getattr(linked_clinic, "telefone", None))

    whatsapp = partner.whatsapp
    if "whatsapp" in fields:
        whatsapp = _clean_text(payload.whatsapp)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            whatsapp = whatsapp or _first_clinic_whatsapp(linked_clinic)

    cidade_base = partner.cidade_base
    if "cidade_base" in fields:
        cidade_base = _clean_text(payload.cidade_base)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            cidade_base = cidade_base or _clean_text(getattr(linked_clinic, "cidade", None))

    estado_base = partner.estado_base
    if "estado_base" in fields:
        estado_base = _clean_text(payload.estado_base)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            estado_base = estado_base or _clean_text(getattr(linked_clinic, "estado", None))

    crmv = partner.crmv if "crmv" not in fields else _clean_text(payload.crmv)
    cpf_documento = partner.cpf_documento if "cpf_documento" not in fields else _clean_text(payload.cpf_documento)
    area_atuacao = partner.area_atuacao if "area_atuacao" not in fields else _clean_text(payload.area_atuacao)

    observacoes = partner.observacoes
    if "observacoes" in fields:
        observacoes = _clean_text(payload.observacoes)
        if partner.tipo == PORTAL_PARTNER_TYPE_CLINICA:
            observacoes = observacoes or _clean_text(getattr(linked_clinic, "observacoes", None))

    ativo = bool(partner.ativo if payload.ativo is None else payload.ativo)

    if partner.tipo == PORTAL_PARTNER_TYPE_VETERINARIO:
        if not nome_exibicao:
            raise HTTPException(status_code=422, detail="nome_exibicao e obrigatorio para veterinario parceiro.")
        if not email_login:
            raise HTTPException(status_code=422, detail="email_login e obrigatorio para veterinario parceiro.")
        if not cidade_base or not estado_base:
            raise HTTPException(
                status_code=422,
                detail="cidade_base e estado_base sao obrigatorios para veterinario parceiro.",
            )
        if not telefone and not whatsapp:
            raise HTTPException(
                status_code=422,
                detail="Informe ao menos telefone ou whatsapp para veterinario parceiro.",
            )

    clinic_links = (
        _validated_clinic_links(db, tipo=partner.tipo, payload_links=payload.clinicas_vinculadas)
        if "clinicas_vinculadas" in fields
        else None
    )
    _ensure_unique_active_email(
        db,
        email_login=email_login,
        ativo=ativo,
        exclude_partner_id=partner.id,
    )
    columns = {
        "nome_exibicao": nome_exibicao,
        "email_login": email_login,
        "telefone": telefone,
        "whatsapp": whatsapp,
        "cidade_base": cidade_base,
        "estado_base": estado_base,
        "crmv": crmv,
        "cpf_documento": cpf_documento,
        "area_atuacao": area_atuacao,
        "observacoes": observacoes,
        "ativo": ativo,
    }
    return columns, clinic_links


def _serialize_partner_after_write(
    db: Session,
    partner: PortalPartnerProfile,
) -> PortalPartnerProfileResponse:
    """Resposta de um parceiro so, com o nome da clinica do tipo e dos vinculos."""
    links_by_partner_id = _clinic_links_by_partner_id(db, [partner.id])
    clinica_ids = [int(link.clinica_id) for link in links_by_partner_id.get(int(partner.id), [])]
    if partner.clinica_id:
        clinica_ids.append(int(partner.clinica_id))
    clinicas_by_id = _linked_clinic_by_id(db, clinica_ids)
    return _serialize_partner(
        partner,
        clinicas_by_id=clinicas_by_id,
        links_by_partner_id=links_by_partner_id,
    )


@router.get("/parceiros", response_model=PortalPartnerProfileListResponse)
def listar_parceiros_externos(
    tipo: str | None = Query(default=None, pattern="^(clinica|veterinario)$"),
    ativo: bool | None = Query(default=None),
    clinica_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    del current_user
    query = db.query(PortalPartnerProfile)

    if tipo:
        query = query.filter(PortalPartnerProfile.tipo == tipo)
    if ativo is not None:
        query = query.filter(PortalPartnerProfile.ativo.is_(ativo))
    if clinica_id is not None:
        query = query.filter(PortalPartnerProfile.clinica_id == clinica_id)
    if q:
        search = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(PortalPartnerProfile.nome_exibicao, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.email_login, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.telefone, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.whatsapp, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.cidade_base, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.estado_base, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.area_atuacao, "")).like(search),
            )
        )

    partners = query.order_by(
        func.lower(PortalPartnerProfile.nome_exibicao).asc(),
        PortalPartnerProfile.id.asc(),
    ).all()

    links_by_partner_id = _clinic_links_by_partner_id(db, [partner.id for partner in partners])
    clinicas_by_id = _linked_clinic_by_id(
        db,
        [partner.clinica_id for partner in partners if partner.clinica_id is not None]
        + [int(link.clinica_id) for links in links_by_partner_id.values() for link in links],
    )
    return PortalPartnerProfileListResponse(
        total=len(partners),
        items=[
            _serialize_partner(
                partner,
                clinicas_by_id=clinicas_by_id,
                links_by_partner_id=links_by_partner_id,
            )
            for partner in partners
        ],
    )


@router.get("/parceiros/veterinarios/opcoes", response_model=PortalPartnerProfileListResponse)
def listar_veterinarios_parceiros_para_fluxo(
    q: str | None = Query(default=None, max_length=120),
    clinica_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_operational_user),
):
    del current_user
    query = db.query(PortalPartnerProfile).filter(
        PortalPartnerProfile.tipo == PORTAL_PARTNER_TYPE_VETERINARIO,
        PortalPartnerProfile.ativo.is_(True),
    )
    if q:
        search = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(PortalPartnerProfile.nome_exibicao, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.email_login, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.whatsapp, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.telefone, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.cidade_base, "")).like(search),
                func.lower(func.coalesce(PortalPartnerProfile.area_atuacao, "")).like(search),
            )
        )

    partners = (
        query.order_by(
            func.lower(PortalPartnerProfile.nome_exibicao).asc(),
            PortalPartnerProfile.id.asc(),
        )
        .limit(limit)
        .all()
    )

    if clinica_id is not None:
        # Quem atende na clinica do laudo aparece primeiro; quem difunde, antes
        # dos demais vinculados. Ninguem sai da lista (RF-015).
        vinculo_por_parceiro = {
            int(link.partner_id): bool(link.receber_todos_laudos)
            for link in db.query(PortalPartnerClinicLink)
            .filter(PortalPartnerClinicLink.clinica_id == int(clinica_id))
            .all()
        }
        partners.sort(
            key=lambda partner: (
                0 if int(partner.id) in vinculo_por_parceiro else 1,
                0 if vinculo_por_parceiro.get(int(partner.id)) else 1,
                str(partner.nome_exibicao or "").lower(),
                int(partner.id),
            )
        )

    links_by_partner_id = _clinic_links_by_partner_id(db, [partner.id for partner in partners])
    clinicas_by_id = _linked_clinic_by_id(
        db,
        [int(link.clinica_id) for links in links_by_partner_id.values() for link in links],
    )
    return PortalPartnerProfileListResponse(
        total=len(partners),
        items=[
            _serialize_partner(
                partner,
                clinicas_by_id=clinicas_by_id,
                links_by_partner_id=links_by_partner_id,
            )
            for partner in partners
        ],
    )


@router.post(
    "/parceiros/veterinarios/cadastro-rapido",
    response_model=PortalPartnerProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def criar_veterinario_parceiro_no_fluxo(
    payload: PortalPartnerProfileCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_operational_user),
):
    del current_user
    payload_data = payload.model_dump()
    payload_data["tipo"] = PORTAL_PARTNER_TYPE_VETERINARIO
    resolved, clinic_links = _resolve_create_payload(db, PortalPartnerProfileCreateRequest(**payload_data))
    partner = PortalPartnerProfile(**resolved)
    db.add(partner)
    db.flush()
    if clinic_links is not None:
        _replace_clinic_links(db, partner_id=partner.id, links=clinic_links)
    db.commit()
    db.refresh(partner)
    return _serialize_partner_after_write(db, partner)


@router.post("/parceiros", response_model=PortalPartnerProfileResponse, status_code=status.HTTP_201_CREATED)
def criar_parceiro_externo(
    payload: PortalPartnerProfileCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    del current_user
    resolved, clinic_links = _resolve_create_payload(db, payload)
    partner = PortalPartnerProfile(**resolved)
    db.add(partner)
    db.flush()
    if clinic_links is not None:
        _replace_clinic_links(db, partner_id=partner.id, links=clinic_links)
    db.commit()
    db.refresh(partner)

    return _serialize_partner_after_write(db, partner)


@router.patch("/parceiros/{partner_id}", response_model=PortalPartnerProfileResponse)
def atualizar_parceiro_externo(
    partner_id: int,
    payload: PortalPartnerProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_portal_admin),
):
    del current_user
    partner = db.query(PortalPartnerProfile).filter(PortalPartnerProfile.id == partner_id).first()
    if partner is None:
        raise HTTPException(status_code=404, detail="Parceiro externo nao encontrado.")

    resolved, clinic_links = _resolve_update_payload(db, partner, payload)
    for field_name, field_value in resolved.items():
        setattr(partner, field_name, field_value)

    db.add(partner)
    if clinic_links is not None:
        _replace_clinic_links(db, partner_id=partner.id, links=clinic_links)
    db.commit()
    db.refresh(partner)

    return _serialize_partner_after_write(db, partner)
