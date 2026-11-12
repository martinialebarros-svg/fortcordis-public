"""Read-only PDF projection of an owned, saved echo editor intent.

Never use a clinical create/update followed by rollback for a preview: those
paths can publish portal files before committing. Only plain dictionaries are
overlaid here; no ORM entity is attached, changed, flushed or consumed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import math
import re
from typing import Any

from fastapi import HTTPException
from PIL import Image

from app.core.security import _user_has_matrix_permission
from app.models.clinica import Clinica
from app.models.imagem_laudo import ImagemTemporaria
from app.models.laudo_editor_draft import LaudoEditorDraft
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.schemas.echo_pdf_preview import EchoPdfPreviewRequest
from app.services.echo_editor_source import existing_snapshot_source, load_echo_editor_source
from app.services.echo_editor_update import REPORT_FIELDS, _patient_changes, _require_edit, _tutor_changes
from app.services.laudo_editor_draft_service import _canonical, validate_snapshot
from app.services.laudo_pdf_service import (
    GeneratedLaudoPdf, LAUDO_PDF_ECO_RENDERER_VERSION,
    load_laudo_pdf_configuration, render_echo_pdf_content,
)
from app.utils.ecocardiograma_medidas import extrair_medidas_ecocardiograma_da_descricao
from app.utils.ecocardiograma_qualitativa import extrair_qualitativa_ecocardiograma_da_descricao
from app.utils.paciente_idade import referencia_documento, AGE_FIELDS, idade_do_paciente, alteracoes_idade
from app.utils.paciente_helpers import (
    data_civil_referencia,
    normalizar_sexo_paciente,
)


_NEW_REPORT_FIELDS = {
    "paciente", "medidas", "qualitativa", "conteudo", "agendamento_id", "clinica",
    "veterinario", "data_exame", "tipo_laudo", "tipo", "status", "pressao_arterial",
    "ecocardiograma_cabecalho", "ecocardiograma_estruturado", "veterinario_parceiro_id", "anexos",
}
_PATIENT_FIELDS = ("nome", "especie", "raca", "sexo", "peso_kg", "nascimento", "observacoes", *AGE_FIELDS)


def _conflict(code: str, message: str) -> None:
    raise HTTPException(409, {"code": code, "message": message})


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(422, f"{label} inválido para a prévia.")
    return value


def _optional_id(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)) or int(value) <= 0:
        raise HTTPException(422, f"{label} inválido para a prévia.")
    return int(value)


def _record_patient(record: Any) -> dict[str, Any]:
    return {key: getattr(record, key, None) for key in _PATIENT_FIELDS}


def _date(raw: Any, fallback: Any, endpoint: Any) -> tuple[Any, str]:
    parsed = endpoint._parse_data_exame(raw) if raw else None
    if raw and parsed is None:
        raise HTTPException(422, "Data do exame inválida para a prévia.")
    value = parsed or fallback or datetime.now()
    civil = data_civil_referencia(value, data_calendario=bool(parsed))
    if civil is None:
        raise HTTPException(422, "Data do exame inválida para a prévia.")
    return value, civil.strftime("%d/%m/%Y")


def _clinic_name(db: Any, clinic_id: Any, requester: Any) -> str:
    if clinic_id is not None:
        clinic = db.query(Clinica).filter(Clinica.id == clinic_id).first()
        if clinic is None:
            raise HTTPException(422, "Clínica inválida para a prévia.")
        return clinic.nome or ""
    return str(requester or "")


def _patient_pdf(patient: dict, tutor_name: str, requester: str, exam_value: Any,
                 exam_text: str, has_exam_date: bool, header: dict) -> dict:
    weight = patient.get("peso_kg")
    return {
        "nome": patient.get("nome") or "N/A", "especie": patient.get("especie") or "Canina",
        "raca": patient.get("raca") or "", "sexo": normalizar_sexo_paciente(patient.get("sexo")),
        "idade": idade_do_paciente(patient,
                                        data_referencia=referencia_documento(exam_value if has_exam_date else None, exam_value), data_calendario=True),
        "peso": str(weight) if weight and weight > 0 else (f"{weight:.1f}" if weight else ""),
        "tutor": tutor_name, "solicitante": requester or "", "data_exame": exam_text,
        **{key: str(header.get(key) or "").strip() for key in ("ritmo", "estado", "fc")},
    }


def _project_new(db: Any, report: dict, endpoint: Any) -> dict:
    if set(report).difference(_NEW_REPORT_FIELDS):
        raise HTTPException(422, "Campo não permitido na prévia do novo ecocardiograma.")
    if (report.get("tipo_laudo") or report.get("tipo") or "ecocardiograma") != "ecocardiograma":
        raise HTTPException(422, "Esta prévia aceita somente ecocardiogramas.")
    payload = _mapping(report.get("paciente"), "Paciente")
    name = str(payload.get("nome") or "").strip()
    if not name:
        raise HTTPException(422, "Informe o nome do paciente antes de conferir o PDF.")
    patient_id = _optional_id(payload.get("id"), "Paciente")
    tutor_id = _optional_id(payload.get("tutor_id"), "Tutor")
    record = db.get(Paciente, patient_id) if patient_id else None
    if patient_id and record is None:
        raise HTTPException(404, "Paciente informado não encontrado.")
    if record is not None:
        if tutor_id and tutor_id != record.tutor_id:
            _conflict("BINDING_CHANGED", "O tutor não corresponde ao vínculo do paciente.")
        tutor_id = record.tutor_id
    tutor = db.get(Tutor, tutor_id) if tutor_id else None
    if tutor_id and (tutor is None or tutor.ativo != 1 or tutor.mesclado_em_id is not None):
        _conflict("BINDING_CHANGED", "Confira o tutor selecionado no cadastro antes de continuar.")
    tutor_name = tutor.nome if tutor is not None else str(payload.get("tutor") or "").strip()
    if not tutor_name:
        raise HTTPException(422, "Informe o tutor antes de conferir o PDF.")
    species = str(payload.get("especie") or "Canina").strip() or "Canina"
    # Match the identity resolver's read projection, never its writes or its
    # name-only tutor creation. A name is not a tutor identity selection.
    if record is None and tutor_id:
        record = db.query(Paciente).filter(
            Paciente.nome_key == endpoint._gerar_nome_key(name),
            Paciente.tutor_id == tutor_id, Paciente.especie.ilike(species),
        ).order_by(Paciente.id.desc()).first()
    patient = _record_patient(record) if record is not None else {
        "nome": name, "especie": species, "observacoes": "", "peso_kg": None,
    }
    for key in ("nome", "especie", "raca"):
        value = str(payload.get(key) or "").strip()
        if value:
            patient[key] = value
    sex = normalizar_sexo_paciente(payload.get("sexo"))
    if sex:
        patient["sexo"] = sex
    weight = endpoint._to_float_or_none(payload.get("peso"))
    if weight is not None:
        if not math.isfinite(weight):
            raise HTTPException(422, "Peso inválido para a prévia.")
        patient["peso_kg"] = weight
    patient.update(alteracoes_idade(patient, payload, data_referencia=payload.get("data_exame") or payload.get("data")))

    raw_date = payload.get("data_exame") or payload.get("data")
    exam_value, exam_text = _date(raw_date, None, endpoint)
    header = endpoint._normalizar_ecocardiograma_cabecalho(report.get("ecocardiograma_cabecalho")) or {}
    veterinarian = _mapping(report.get("veterinario") or {}, "Solicitante")
    requester = veterinarian.get("nome") or ""
    partner_id = _optional_id(report.get("veterinario_parceiro_id"), "Veterinário parceiro")
    if partner_id:
        _, partner = endpoint._load_veterinario_parceiro_or_422(db, partner_id)
        requester = requester or partner.nome_exibicao
    clinic_id = endpoint._extrair_clinic_id(report.get("clinica"))

    measures = _mapping(report.get("medidas") or {}, "Medidas")
    qualitative = _mapping(report.get("qualitativa") or {}, "Qualitativa")
    content = _mapping(report.get("conteudo") or {}, "Conteúdo")
    structured = endpoint._normalizar_ecocardiograma_estruturado(report.get("ecocardiograma_estruturado"))
    if structured and structured.get("usar_no_laudo"):
        legacy = endpoint._derivar_legado_de_ecocardiograma_estruturado(structured)
        qualitative = legacy["qualitativa"]
        content = dict(content)
        if legacy["conclusao"]:
            content["conclusao"] = legacy["conclusao"]
    description = endpoint._montar_descricao_ecocardiograma(measures, qualitative)
    return {
        "paciente": _patient_pdf(patient, tutor_name, requester, exam_value, exam_text, bool(raw_date), header),
        "medidas": extrair_medidas_ecocardiograma_da_descricao(description),
        "qualitativa": extrair_qualitativa_ecocardiograma_da_descricao(description),
        "conclusao": str(content.get("conclusao") or ""),
        "clinica": _clinic_name(db, clinic_id, requester),
        "pressao_arterial": endpoint._normalizar_pressao_arterial(report.get("pressao_arterial")),
    }


def _project_existing(db: Any, user: Any, source: Any, report: dict,
                      data: EchoPdfPreviewRequest, endpoint: Any) -> dict:
    if set(report).difference(REPORT_FIELDS):
        raise HTTPException(422, "Campo não permitido na prévia da edição.")
    for key in ("tipo", "tipo_laudo"):
        if key in report and report[key] != "ecocardiograma":
            raise HTTPException(422, "O tipo do ecocardiograma não pode ser alterado.")
    for key in ("titulo", "descricao", "diagnostico", "observacoes", "status", "medico_solicitante"):
        if key in report and report[key] is not None and not isinstance(report[key], str):
            raise HTTPException(422, "Texto do laudo inválido.")
    if "status" in report and report["status"] not in {"Rascunho", "Finalizado", "Arquivado", endpoint.PORTAL_RELEASED_STATUS}:
        raise HTTPException(422, "Status do laudo inválido.")
    for key in ("clinic_id", "veterinario_parceiro_id"):
        if report.get(key) is not None and type(report[key]) is not int:
            raise HTTPException(422, "Identificador do laudo inválido.")
    if source.paciente is None:
        raise HTTPException(404, "Paciente do laudo não encontrado.")
    patient = _record_patient(source.paciente)
    changes = _patient_changes(source, data.paciente, data_referencia=referencia_documento(report.get("data_exame", source.laudo.data_exame), source.laudo.data_laudo))
    tutor_changes, create_tutor = _tutor_changes(source, data.tutor)
    if changes or create_tutor:
        _require_edit(db, user, "pacientes")
    if tutor_changes or create_tutor:
        _require_edit(db, user, "tutores")
    patient.update(changes)
    tutor_name = source.tutor.nome if source.tutor else ""
    if "nome" in tutor_changes:
        tutor_name = tutor_changes["nome"] or ""

    report_date = report.get("data_exame", source.laudo.data_exame)
    exam_value, exam_text = _date(report_date, source.laudo.data_laudo, endpoint)
    requester = report.get("medico_solicitante", source.laudo.medico_solicitante) or ""
    if report.get("veterinario_parceiro_id") is not None:
        partner_id = _optional_id(report.get("veterinario_parceiro_id"), "Veterinário parceiro")
        _, partner = endpoint._load_veterinario_parceiro_or_422(db, partner_id)
        requester = requester or (partner.nome_exibicao if partner else "")
    clinic_id = report.get("clinic_id", source.laudo.clinic_id)
    if clinic_id is not None:
        clinic_id = _optional_id(clinic_id, "Clínica")
    header = (endpoint._normalizar_ecocardiograma_cabecalho(report["ecocardiograma_cabecalho"])
              if "ecocardiograma_cabecalho" in report
              else endpoint._extrair_ecocardiograma_cabecalho_de_anexos(source.laudo.anexos)) or {}
    pressure = (endpoint._normalizar_pressao_arterial(report["pressao_arterial"])
                if "pressao_arterial" in report
                else endpoint._extrair_pressao_arterial_de_anexos(source.laudo.anexos))
    description = report.get("descricao", source.laudo.descricao)
    conclusion = report.get("diagnostico", source.laudo.diagnostico) or ""
    # The flat update contract uses setdefault: explicit manual text wins.
    # Only a submitted structured field plus an explicit apply flag can supply
    # a missing flat field. Never reapply a preset merely because it exists.
    if "ecocardiograma_estruturado" in report:
        structured = endpoint._normalizar_ecocardiograma_estruturado(report["ecocardiograma_estruturado"])
        if structured and structured.get("usar_no_laudo"):
            legacy = endpoint._derivar_legado_de_ecocardiograma_estruturado(structured)
            if report.get("aplicar_qualitativa_estruturada") is True and "descricao" not in report:
                description = endpoint._montar_descricao_ecocardiograma(
                    extrair_medidas_ecocardiograma_da_descricao(source.laudo.descricao), legacy["qualitativa"])
            if report.get("aplicar_conclusao_estruturada") is True and "diagnostico" not in report:
                conclusion = legacy["conclusao"]
    return {
        "paciente": _patient_pdf(patient, tutor_name, requester, exam_value, exam_text, bool(report_date), header),
        "medidas": extrair_medidas_ecocardiograma_da_descricao(description),
        "qualitativa": extrair_qualitativa_ecocardiograma_da_descricao(description),
        "conclusao": conclusion, "clinica": _clinic_name(db, clinic_id, requester),
        "pressao_arterial": pressure,
    }


def _images(db: Any, source: Any, snapshot: dict, data: EchoPdfPreviewRequest) -> list[dict]:
    descriptors = snapshot.get("imagens", [])
    if not isinstance(descriptors, list):
        _conflict("TEMP_IMAGES_UNAVAILABLE", "Confira as imagens salvas no rascunho.")
    saved_ids = []
    for image in descriptors:
        if (not isinstance(image, dict) or image.get("uploaded") is not True
                or image.get("requerReenvio") is True
                or type(image.get("tempId")) is not int or image["tempId"] <= 0):
            _conflict("TEMP_IMAGES_UNAVAILABLE", "Reenvie ou remova as imagens pendentes antes da prévia.")
        saved_ids.append(image["tempId"])
    payload = data.imagens
    temp_ids = [item.id for item in payload.temp_config]
    if len(saved_ids) != len(set(saved_ids)) or len(temp_ids) != len(set(temp_ids)) or set(saved_ids) != set(temp_ids):
        _conflict("TEMP_IMAGES_UNAVAILABLE", "As imagens não correspondem à cópia salva do rascunho.")
    if payload.temp_session_id is not None and payload.temp_session_id != snapshot.get("sessionId"):
        _conflict("TEMP_IMAGES_UNAVAILABLE", "A sessão das imagens não corresponde ao rascunho.")
    if temp_ids and not payload.temp_session_id:
        raise HTTPException(422, "Sessão de imagens temporárias obrigatória.")
    configured_ids = [item.id for item in payload.persistidas]
    removed_ids = payload.removidas_ids
    if (len(configured_ids) != len(set(configured_ids)) or len(removed_ids) != len(set(removed_ids))
            or set(configured_ids).intersection(removed_ids)):
        raise HTTPException(422, "IDs de imagem duplicados ou conflitantes.")
    active = {image.id: image for image in source.imagens if image.ativo == 1} if source else {}
    if set(configured_ids).union(removed_ids) != set(active):
        _conflict("IMAGES_CHANGED", "As imagens não correspondem ao laudo em edição.")
    temps = db.query(ImagemTemporaria).filter(
        ImagemTemporaria.session_id == payload.temp_session_id,
        ImagemTemporaria.expira_em > datetime.utcnow(),
    ).order_by(ImagemTemporaria.id).all() if payload.temp_session_id else []
    if {image.id for image in temps} != set(temp_ids):
        _conflict("TEMP_IMAGES_UNAVAILABLE", "Imagens temporárias ausentes, expiradas ou alteradas. Confira o envio antes da prévia.")
    temps_by_id = {image.id: image for image in temps}
    projected = []
    for configs, available in ((payload.persistidas, active), (payload.temp_config, temps_by_id)):
        for config in configs:
            if not config.incluir_no_pdf:
                continue
            image = available[config.id]
            content = image.conteudo
            if not content and getattr(image, "caminho_arquivo", None):
                try:
                    with open(image.caminho_arquivo, "rb") as stream:
                        content = stream.read()
                except OSError:
                    _conflict("TEMP_IMAGES_UNAVAILABLE", "Uma imagem incluída não está disponível. Reenvie ou retire a imagem.")
            if not content:
                _conflict("TEMP_IMAGES_UNAVAILABLE", "Uma imagem incluída está sem conteúdo. Reenvie ou retire a imagem.")
            try:
                with Image.open(BytesIO(content)) as decoded:
                    decoded.verify()
            except Exception:
                _conflict("TEMP_IMAGES_UNAVAILABLE", "Uma imagem incluída não pôde ser lida. Reenvie ou retire a imagem.")
            projected.append((config.ordem, {"conteudo": content, "descricao": config.descricao}))
    return [item for _, item in sorted(projected, key=lambda pair: pair[0])]


def render_echo_editor_preview(db: Any, user: Any, draft_id: str,
                               data: EchoPdfPreviewRequest) -> GeneratedLaudoPdf:
    from app.api.v1.endpoints import laudos as endpoint

    # POST already requires laudos/editar through get_current_user. Rendering
    # reads official source/demographic data too, so preserve the GET/PDF gate
    # even for a custom role that can edit but cannot view this module.
    if not user.tem_papel("admin") and not _user_has_matrix_permission(db, user, "laudos", "visualizar"):
        raise HTTPException(403, "Acesso negado: sem permissao de visualizar em laudos.")
    with db.no_autoflush:
        draft = db.query(LaudoEditorDraft).filter(
            LaudoEditorDraft.owner_id == user.id, LaudoEditorDraft.draft_id == draft_id,
        ).first()
        if draft is None:
            raise HTTPException(404, "Rascunho não encontrado.")
        if draft.closed_at is not None or draft.revision != data.expected_revision:
            _conflict("WORKSPACE_CHANGED", "O rascunho mudou ou foi encerrado. Confira a cópia salva antes da prévia.")
        snapshot = json.loads(draft.snapshot_json)
        # Same bounds and credential/binary exclusions as private autosave.
        raw = data.model_dump(mode="json", exclude_unset=True)
        validate_snapshot({"schema_version": 1, "editor": "new-echo", "preview_intent": raw})
        bound = existing_snapshot_source(snapshot, draft.context_key)
        source = load_echo_editor_source(db, bound["laudo_id"]) if bound else None
        if source and source.revision != bound["editor_revision"]:
            _conflict("SOURCE_CHANGED", "O laudo original mudou. Confira a versão atual antes da prévia.")
        if not source and snapshot.get("editor") != "new-echo":
            raise HTTPException(422, "Editor de rascunho inválido para a prévia.")
        if not source and (data.paciente is not None or data.tutor is not None):
            raise HTTPException(422, "Dados do novo paciente devem acompanhar o conteúdo do novo laudo.")
        report = deepcopy(data.payload_laudo)
        projected = (_project_existing(db, user, source, report, data, endpoint) if source
                     else _project_new(db, report, endpoint))
        projected["imagens"] = _images(db, source, snapshot, data)
        config_system, config_user = load_laudo_pdf_configuration(db, user.id)
        content = render_echo_pdf_content(
            db, user, **projected, config_sistema=config_system, config_usuario=config_user, preview=True,
        )
        fingerprint = sha256(_canonical({
            "draft_id": draft_id, "revision": data.expected_revision,
            "source_revision": source.revision if source else None,
            "renderer_version": LAUDO_PDF_ECO_RENDERER_VERSION, "intent": raw,
        }).encode("utf-8")).hexdigest()
        return GeneratedLaudoPdf(content=content, filename="previa-ecocardiograma.pdf", cache_key=fingerprint)
