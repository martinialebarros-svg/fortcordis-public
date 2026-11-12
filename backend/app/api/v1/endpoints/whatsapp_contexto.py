from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import String, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query as SqlAlchemyQuery
from sqlalchemy.orm import Session

from app.core.security import require_any_papel
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.user import User
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao, WhatsAppBotResposta
from app.services.auditoria_service import registrar_auditoria
from app.services.whatsapp_agenda_service import normalize_whatsapp_number
from app.services.whatsapp_contexto_selecao_service import (
    canonical_context_identity,
    carregar_selecao,
    criar_contexto_chave,
    lock_contexto,
    selecao_payload,
)


router = APIRouter()

MAX_RELATED_PEOPLE = 12
MAX_APPOINTMENTS = 6
MAX_SERVICE_ORDERS = 6


def _legacy_active(column):
    return func.lower(func.coalesce(cast(column, String), "1")).in_(["1", "true", "t"])


def _candidate_numbers(*values: Any) -> Iterable[Any]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            yield from value
            continue
        if isinstance(value, str) and value.lstrip().startswith("["):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, list):
                yield from decoded
                continue
        yield value


_BR_MOBILE_WITH_NINTH_DIGIT = re.compile(r"^55\d{2}9\d{8}$")
_BR_MOBILE_WITHOUT_NINTH_DIGIT = re.compile(r"^55\d{2}\d{8}$")


def _whatsapp_number_variants(normalized_phone: str) -> set[str]:
    """RF-015 (nono digito): `normalize_whatsapp_number` so prefixa "55" e

    nao mexe no nono digito de moveis BR, enquanto `canonicalWhatsAppIdentity`
    (Node) remove esse digito para usar como identidade da conversa. Sem
    isso, um cadastro em `55DD9XXXXXXXX` nunca casa com a conversa que chega
    do Node em `55DDXXXXXXXX`, e vice-versa.
    """
    variants = {normalized_phone}
    if _BR_MOBILE_WITH_NINTH_DIGIT.match(normalized_phone):
        variants.add(normalized_phone[:4] + normalized_phone[5:])
    elif _BR_MOBILE_WITHOUT_NINTH_DIGIT.match(normalized_phone):
        variants.add(normalized_phone[:4] + "9" + normalized_phone[4:])
    return variants


def _has_exact_phone(normalized_phone: str, *values: Any) -> bool:
    target_variants = _whatsapp_number_variants(normalized_phone)
    for value in _candidate_numbers(*values):
        try:
            candidate_normalized = normalize_whatsapp_number(value)
        except HTTPException:
            continue
        if candidate_normalized in target_variants:
            return True
    return False


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clinic_payload(clinic: Clinica) -> dict[str, Any]:
    return {
        "id": clinic.id,
        "nome": str(clinic.nome or "Clinica sem nome").strip(),
        "cidade": str(clinic.cidade or "").strip() or None,
        "estado": str(clinic.estado or "").strip() or None,
    }


def _tutor_payload(tutor: Tutor) -> dict[str, Any]:
    return {
        "id": tutor.id,
        "nome": str(tutor.nome or "Tutor sem nome").strip(),
    }


def _pet_payload(patient: Paciente) -> dict[str, Any]:
    return {
        "id": patient.id,
        "tutor_id": patient.tutor_id,
        "nome": str(patient.nome or "Pet sem nome").strip(),
        "especie": str(patient.especie or "").strip() or None,
        "raca": str(patient.raca or "").strip() or None,
    }


def _unique_payloads(items: Iterable[dict[str, Any]], *, limit: int = MAX_RELATED_PEOPLE) -> list[dict[str, Any]]:
    unique: dict[int, dict[str, Any]] = {}
    for item in items:
        item_id = int(item.get("id") or 0)
        if item_id > 0 and item_id not in unique:
            unique[item_id] = item
        if len(unique) >= limit:
            break
    return list(unique.values())


def _appointment_query(db: Session) -> SqlAlchemyQuery:
    return (
        db.query(Agendamento, Paciente, Tutor, Clinica, Servico)
        .outerjoin(Paciente, Agendamento.paciente_id == Paciente.id)
        .outerjoin(
            Tutor,
            Tutor.id == func.coalesce(Agendamento.tutor_id, Paciente.tutor_id),
        )
        .outerjoin(Clinica, Agendamento.clinica_id == Clinica.id)
        .outerjoin(Servico, Agendamento.servico_id == Servico.id)
    )


def _relevant_appointments(query: SqlAlchemyQuery) -> list[Any]:
    now = datetime.now(timezone.utc)
    future_limit = (MAX_APPOINTMENTS + 1) // 2
    future = (
        query.filter(Agendamento.inicio >= now)
        .order_by(Agendamento.inicio.asc(), Agendamento.id.asc())
        .limit(future_limit)
        .all()
    )
    remaining = MAX_APPOINTMENTS - len(future)
    past = []
    if remaining > 0:
        past = (
            query.filter(Agendamento.inicio < now)
            .order_by(Agendamento.inicio.desc(), Agendamento.id.desc())
            .limit(remaining)
            .all()
        )
    return [*future, *past]


def _appointment_payload(row: Any) -> dict[str, Any]:
    appointment, patient, tutor, clinic, service = row
    return {
        "id": appointment.id,
        "inicio": _to_iso(appointment.inicio),
        "fim": _to_iso(appointment.fim),
        "status": str(appointment.status or "Sem status").strip(),
        "clinica_id": clinic.id if clinic else appointment.clinica_id,
        "clinica_nome": str(clinic.nome or "").strip() if clinic else str(appointment.clinica or "").strip(),
        "tutor_id": tutor.id if tutor else appointment.tutor_id,
        "tutor_nome": str(tutor.nome or "").strip() if tutor else str(appointment.tutor or "").strip(),
        "pet_id": patient.id if patient else appointment.paciente_id,
        "pet_nome": str(patient.nome or "").strip() if patient else str(appointment.paciente or "").strip(),
        "servico_id": service.id if service else appointment.servico_id,
        "servico_nome": str(service.nome or "").strip() if service else str(appointment.servico or "").strip(),
    }


def _service_order_query(db: Session) -> SqlAlchemyQuery:
    return (
        db.query(OrdemServico, Paciente, Tutor, Clinica, Servico)
        .outerjoin(Paciente, OrdemServico.paciente_id == Paciente.id)
        .outerjoin(Tutor, Paciente.tutor_id == Tutor.id)
        .outerjoin(Clinica, OrdemServico.clinica_id == Clinica.id)
        .outerjoin(Servico, OrdemServico.servico_id == Servico.id)
    )


def _service_order_payload(row: Any) -> dict[str, Any]:
    service_order, patient, tutor, clinic, service = row
    return {
        "id": service_order.id,
        "numero_os": str(service_order.numero_os or service_order.id),
        "agendamento_id": service_order.agendamento_id,
        "data_atendimento": _to_iso(service_order.data_atendimento),
        "status": str(service_order.status or "Sem status").strip(),
        "valor_final": _to_float(service_order.valor_final),
        "clinica_id": clinic.id if clinic else service_order.clinica_id,
        "clinica_nome": str(clinic.nome or "").strip() if clinic else "",
        "tutor_id": tutor.id if tutor else None,
        "tutor_nome": str(tutor.nome or "").strip() if tutor else "",
        "pet_id": patient.id if patient else service_order.paciente_id,
        "pet_nome": str(patient.nome or "").strip() if patient else "",
        "servico_id": service.id if service else service_order.servico_id,
        "servico_nome": str(service.nome or "").strip() if service else "",
    }


def resolve_whatsapp_context(db: Session, phone: str) -> dict[str, Any]:
    normalized_phone = normalize_whatsapp_number(phone)

    active_clinics = (
        db.query(Clinica)
        .populate_existing()
        .filter(_legacy_active(Clinica.ativo))
        .order_by(Clinica.nome.asc(), Clinica.id.asc())
        .all()
    )
    clinic_matches = [
        clinic
        for clinic in active_clinics
        if _has_exact_phone(normalized_phone, clinic.whatsapps, clinic.telefone)
    ]

    active_tutors = (
        db.query(Tutor)
        .populate_existing()
        .filter(_legacy_active(Tutor.ativo))
        .order_by(Tutor.nome.asc(), Tutor.id.asc())
        .all()
    )
    tutor_matches = [
        tutor
        for tutor in active_tutors
        if _has_exact_phone(normalized_phone, tutor.whatsapp, tutor.telefone)
    ]

    candidatos = {
        "clinicas": [_clinic_payload(clinic) for clinic in clinic_matches],
        "tutores": [_tutor_payload(tutor) for tutor in tutor_matches],
    }
    selecao = selecao_payload(carregar_selecao(db, normalized_phone), candidatos)
    selection_invalid = bool(selecao and not selecao["valida"])
    if selecao and selecao["match_type"]:
        clinic_matches = [
            clinic for clinic in clinic_matches
            if selecao["match_type"] == "clinica" and clinic.id == selecao["cadastro_id"]
        ]
        tutor_matches = [
            tutor for tutor in tutor_matches
            if selecao["match_type"] == "tutor" and tutor.id == selecao["cadastro_id"]
        ]
    direct_matches = len(clinic_matches) + len(tutor_matches)
    base_response: dict[str, Any] = {
        "normalized_phone": normalized_phone,
        "resolution": "not_found",
        "match_type": None,
        "clinicas": [_clinic_payload(clinic) for clinic in clinic_matches],
        "tutores": [_tutor_payload(tutor) for tutor in tutor_matches],
        "pets": [],
        "agendamentos": [],
        "ordens_servico": [],
        "candidatos": candidatos,
        "selecao": selecao,
        "contexto_chave": criar_contexto_chave(normalized_phone, candidatos, selecao),
    }
    if selection_invalid:
        base_response.update(resolution="selection_invalid", clinicas=[], tutores=[])
        return base_response
    if direct_matches == 0:
        return base_response
    if direct_matches > 1:
        base_response["resolution"] = "ambiguous"
        return base_response

    matched_clinic = clinic_matches[0] if clinic_matches else None
    matched_tutor = tutor_matches[0] if tutor_matches else None
    base_response["resolution"] = "matched"
    base_response["match_type"] = "clinica" if matched_clinic else "tutor"

    related_patients: list[Paciente] = []
    if matched_tutor:
        related_patients = (
            db.query(Paciente)
            .filter(Paciente.tutor_id == matched_tutor.id, _legacy_active(Paciente.ativo))
            .order_by(Paciente.nome.asc(), Paciente.id.asc())
            .limit(MAX_RELATED_PEOPLE)
            .all()
        )
    patient_ids = [patient.id for patient in related_patients]

    appointment_query = _appointment_query(db)
    service_order_query = _service_order_query(db)
    if matched_clinic:
        appointment_query = appointment_query.filter(Agendamento.clinica_id == matched_clinic.id)
        service_order_query = service_order_query.filter(OrdemServico.clinica_id == matched_clinic.id)
    else:
        appointment_query = appointment_query.filter(
            or_(
                Agendamento.tutor_id == matched_tutor.id,
                Agendamento.paciente_id.in_(patient_ids),
            )
        )
        service_order_query = service_order_query.filter(OrdemServico.paciente_id.in_(patient_ids))

    appointment_rows = _relevant_appointments(appointment_query)
    service_order_rows = (
        service_order_query
        .order_by(OrdemServico.data_atendimento.desc(), OrdemServico.id.desc())
        .limit(MAX_SERVICE_ORDERS)
        .all()
    )

    clinics = [matched_clinic] if matched_clinic else []
    tutors = [matched_tutor] if matched_tutor else []
    patients = list(related_patients)
    for _appointment, patient, tutor, clinic, _service in appointment_rows:
        if clinic:
            clinics.append(clinic)
        if tutor:
            tutors.append(tutor)
        if patient:
            patients.append(patient)
    for _service_order, patient, tutor, clinic, _service in service_order_rows:
        if clinic:
            clinics.append(clinic)
        if tutor:
            tutors.append(tutor)
        if patient:
            patients.append(patient)

    base_response.update(
        {
            "clinicas": _unique_payloads(_clinic_payload(item) for item in clinics if item),
            "tutores": _unique_payloads(_tutor_payload(item) for item in tutors if item),
            "pets": _unique_payloads(_pet_payload(item) for item in patients if item),
            "agendamentos": [_appointment_payload(row) for row in appointment_rows],
            "ordens_servico": [_service_order_payload(row) for row in service_order_rows],
        }
    )
    return base_response


@router.get("")
def get_whatsapp_context(
    telefone: str = Query(..., min_length=10, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_any_papel("admin", "recepcao", "veterinario", "cardiologista")
    ),
):
    del current_user
    return resolve_whatsapp_context(db, telefone)


class WhatsAppContextoSelecaoRequest(BaseModel):
    match_type: Literal["clinica", "tutor"] | None
    cadastro_id: StrictInt | None = Field(..., gt=0)
    versao_esperada: StrictInt = Field(..., ge=0)


@router.patch("/{wa_identity}/selecao")
def atualizar_contexto_selecao(
    wa_identity: str,
    payload: WhatsAppContextoSelecaoRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_any_papel("admin", "recepcao", "veterinario", "cardiologista")
    ),
):
    if (payload.match_type is None) != (payload.cadastro_id is None):
        raise HTTPException(422, "Informe o tipo e o cadastro juntos, ou limpe ambos.")
    identity = canonical_context_identity(wa_identity)
    lock_contexto(db, identity)
    contexto = resolve_whatsapp_context(db, identity)
    anterior = contexto["selecao"]
    versao_atual = anterior["versao"] if anterior else 0
    if payload.versao_esperada != versao_atual:
        raise HTTPException(409, "O cadastro desta conversa mudou. Atualize a conversa antes de selecionar novamente.")
    if payload.match_type is not None:
        key = "clinicas" if payload.match_type == "clinica" else "tutores"
        if not any(item["id"] == payload.cadastro_id for item in contexto["candidatos"][key]):
            raise HTTPException(422, "Selecione um cadastro ativo vinculado ao telefone desta conversa.")

    now = datetime.now(timezone.utc)
    values = {
        "match_type": payload.match_type,
        "cadastro_id": payload.cadastro_id,
        "versao": versao_atual + 1,
        "atualizado_por_id": current_user.id,
        "updated_at": now,
    }
    try:
        if anterior is None:
            db.add(WhatsAppBotContextoSelecao(wa_identity=identity, **values))
            db.flush()
        else:
            changed = db.query(WhatsAppBotContextoSelecao).filter(
                WhatsAppBotContextoSelecao.wa_identity == identity,
                WhatsAppBotContextoSelecao.versao == payload.versao_esperada,
            ).update(values, synchronize_session=False)
            if changed != 1:
                db.rollback()
                raise HTTPException(409, "O cadastro desta conversa mudou. Atualize a conversa antes de selecionar novamente.")
        db.query(WhatsAppBotResposta).filter(
            WhatsAppBotResposta.wa_identity.in_(_whatsapp_number_variants(identity)),
            WhatsAppBotResposta.decisao == "draft",
        ).update(
            {"decisao": "suppressed", "motivo": "contexto_alterado"},
            synchronize_session=False,
        )
        registrar_auditoria(
            current_user=current_user,
            modulo="whatsapp",
            entidade="whatsapp_contexto_selecao",
            entidade_id=identity,
            acao="WHATSAPP_CONTEXTO_SELECAO_ALTERADA",
            descricao="Cadastro usado pelo bot nesta conversa atualizado pela equipe.",
            detalhes={
                "anterior": {key: anterior.get(key) for key in ("match_type", "cadastro_id", "versao")} if anterior else None,
                "atual": {key: values[key] for key in ("match_type", "cadastro_id", "versao")},
            },
            request=request,
            db=db,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "O cadastro desta conversa mudou. Atualize a conversa antes de selecionar novamente.")
    except Exception:
        db.rollback()
        raise
    return resolve_whatsapp_context(db, identity)
