"""One explicit echo update, including image and demographic edits, in one commit."""
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.security import _user_has_matrix_permission
from app.models.clinica import Clinica
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria
from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest
from app.models.tutor import Tutor
from app.services.echo_editor_source import SOURCE_CONFLICT, existing_snapshot_source, load_echo_editor_source
from app.services.laudo_editor_draft_service import _canonical, _is_write_collision, validate_snapshot
from app.utils.paciente_idade import referencia_documento, AGE_INPUT_FIELDS, alteracoes_idade
from app.utils.paciente_helpers import normalizar_sexo_paciente

REPORT_FIELDS = {
    "titulo", "descricao", "diagnostico", "observacoes", "status", "data_exame", "tipo", "tipo_laudo",
    "pressao_arterial", "ecocardiograma_cabecalho", "ecocardiograma_estruturado",
    "aplicar_qualitativa_estruturada", "aplicar_conclusao_estruturada", "clinic_id",
    "veterinario_parceiro_id", "medico_solicitante",
}


def _require_edit(db, user, module):
    if not user.tem_papel("admin") and not _user_has_matrix_permission(db, user, module, "editar"):
        raise HTTPException(403, f"Acesso negado: sem permissao de editar em {module}.")


def _conflict(message=SOURCE_CONFLICT, *, code="SOURCE_CHANGED"):
    raise HTTPException(409, {"code": code, "message": message})


def _patient_changes(source, patch, *, data_referencia=None):
    if patch is None:
        return {}
    if source.paciente is None:
        raise HTTPException(404, "Paciente do laudo não encontrado.")
    changes = patch.model_dump(exclude_unset=True)
    age_changes = alteracoes_idade(source.paciente, changes, data_referencia=data_referencia or referencia_documento(source.laudo.data_exame, source.laudo.data_laudo))
    changes = {key: value for key, value in changes.items() if key not in AGE_INPUT_FIELDS}
    changes.update(age_changes)
    if "sexo" in changes:
        changes["sexo"] = normalizar_sexo_paciente(changes["sexo"])
    if "nome" in changes and not str(changes["nome"] or "").strip():
        raise HTTPException(422, "Nome do paciente não pode ser vazio.")
    return {key: value for key, value in changes.items()
            if value != (normalizar_sexo_paciente(source.paciente.sexo) if key == "sexo"
                         else getattr(source.paciente, key))}


def _tutor_changes(source, patch):
    if patch is None:
        return {}, False
    if source.paciente is None:
        raise HTTPException(404, "Paciente do laudo não encontrado.")
    if source.paciente.tutor_id:
        if patch.criar_novo or (patch.id is not None and patch.id != source.paciente.tutor_id):
            _conflict("O tutor não corresponde ao vínculo atual do paciente.", code="BINDING_CHANGED")
        if source.tutor is None or source.tutor.mesclado_em_id is not None:
            _conflict("Confira o vínculo do tutor no cadastro antes de continuar.", code="BINDING_CHANGED")
        values = patch.model_dump(exclude_unset=True, exclude={"id", "criar_novo"})
        if "nome" in values and not str(values["nome"] or "").strip():
            raise HTTPException(422, "Nome do tutor não pode ser vazio.")
        return {key: value for key, value in values.items() if value != getattr(source.tutor, key)}, False
    if patch.id is not None or not patch.criar_novo or not str(patch.nome or "").strip():
        raise HTTPException(422, "Vincule o tutor no cadastro ou confirme explicitamente a criação de um novo tutor.")
    return {"nome": patch.nome, "telefone": patch.telefone}, True


def _validate_images(db, source, payload, snapshot):
    descriptors = snapshot.get("imagens", [])
    if not isinstance(descriptors, list):
        _conflict("Confira as imagens salvas no rascunho.", code="TEMP_IMAGES_UNAVAILABLE")
    saved_ids = []
    for image in descriptors:
        if (not isinstance(image, dict) or image.get("uploaded") is not True
                or image.get("requerReenvio") is True
                or type(image.get("tempId")) is not int or image["tempId"] <= 0):
            _conflict("Reenvie ou remova as imagens pendentes antes de atualizar.", code="TEMP_IMAGES_UNAVAILABLE")
        saved_ids.append(image["tempId"])
    requested_ids = [item.id for item in payload.temp_config] if payload else []
    if len(saved_ids) != len(set(saved_ids)) or set(saved_ids) != set(requested_ids):
        _conflict("As imagens não correspondem à cópia salva do rascunho.", code="TEMP_IMAGES_UNAVAILABLE")
    if payload and payload.temp_session_id is not None and payload.temp_session_id != snapshot["sessionId"]:
        _conflict("A sessão das imagens não corresponde ao rascunho.", code="TEMP_IMAGES_UNAVAILABLE")
    if payload is None:
        return [], []
    active = {image.id for image in source.imagens if image.ativo == 1}
    configured = [item.id for item in payload.persistidas]
    removed = payload.removidas_ids
    if (len(configured) != len(set(configured)) or len(removed) != len(set(removed))
            or set(configured).intersection(removed)):
        raise HTTPException(422, "IDs de imagem duplicados ou conflitantes.")
    if set(configured).union(removed) != active:
        _conflict("As imagens do laudo mudaram. Confira o conjunto atual antes de atualizar.", code="IMAGES_CHANGED")
    temp_ids = [item.id for item in payload.temp_config]
    if len(temp_ids) != len(set(temp_ids)):
        raise HTTPException(422, "IDs de imagem temporária duplicados.")
    if temp_ids and not payload.temp_session_id:
        raise HTTPException(422, "Sessão de imagens temporárias obrigatória.")
    temps = db.query(ImagemTemporaria).populate_existing().filter(
        ImagemTemporaria.session_id == payload.temp_session_id,
        ImagemTemporaria.expira_em > datetime.utcnow(),
    ).order_by(ImagemTemporaria.id).with_for_update().all() if payload.temp_session_id else []
    if {image.id for image in temps} != set(temp_ids):
        _conflict("Imagens temporárias ausentes, expiradas ou alteradas. Confira o envio antes de atualizar.", code="TEMP_IMAGES_UNAVAILABLE")
    return temps, {item.id: item for item in payload.temp_config}


def apply_echo_editor_update(db, user, laudo_id, data):
    # Imported lazily to share the existing report normalization/PDF contract.
    from app.api.v1.endpoints import laudos

    source = load_echo_editor_source(db, laudo_id, lock=True)
    draft = db.query(LaudoEditorDraft).populate_existing().filter(
        LaudoEditorDraft.owner_id == user.id,
        LaudoEditorDraft.draft_id == str(data.editor_draft_id),
    ).with_for_update().first()
    if draft is None:
        raise HTTPException(404, "Rascunho não encontrado.")
    snapshot = json.loads(draft.snapshot_json)
    bound = existing_snapshot_source(snapshot, draft.context_key)
    if bound is None or bound["laudo_id"] != laudo_id:
        _conflict("O rascunho não corresponde a este laudo.", code="BINDING_CHANGED")
    # Omitted demographic fields differ from an explicit null/clear request.
    raw = data.model_dump(mode="json", exclude_unset=True)
    validate_snapshot({"schema_version": 1, "editor": "new-echo", "update": raw})
    fingerprint = hashlib.sha256(_canonical(raw).encode("utf-8")).hexdigest()
    request_id = str(data.request_id)
    receipt = db.query(LaudoEditorDraftRequest).filter(
        LaudoEditorDraftRequest.draft_row_id == draft.id,
        LaudoEditorDraftRequest.request_id == request_id,
    ).first()
    result = {"id": laudo_id, "request_id": request_id, "updated": True}
    if receipt:
        if receipt.operation != "apply" or receipt.payload_hash != fingerprint:
            _conflict("Esta operação já foi usada com outro conteúdo.", code="OPERATION_CONFLICT")
        return result
    if draft.closed_at is not None or draft.revision != data.expected_draft_revision:
        _conflict("O rascunho mudou ou já foi encerrado. Confira a cópia salva.", code="WORKSPACE_CHANGED")
    if bound["editor_revision"] != data.expected_editor_revision:
        _conflict("A origem informada não corresponde ao rascunho salvo.", code="BINDING_CHANGED")
    if source.revision != data.expected_editor_revision:
        _conflict()

    report = dict(data.payload_laudo)
    if set(report).difference(REPORT_FIELDS):
        raise HTTPException(422, "Campo não permitido na atualização do laudo.")
    for key in ("tipo", "tipo_laudo"):
        if key in report and report[key] != "ecocardiograma":
            raise HTTPException(422, "O tipo do ecocardiograma não pode ser alterado neste editor.")
    for key in ("titulo", "descricao", "diagnostico", "observacoes", "status", "medico_solicitante"):
        if key in report and report[key] is not None and not isinstance(report[key], str):
            raise HTTPException(422, "Texto do laudo inválido.")
    if "status" in report and report["status"] not in {"Rascunho", "Finalizado", "Arquivado", laudos.PORTAL_RELEASED_STATUS}:
        raise HTTPException(422, "Status do laudo inválido.")
    if report.get("data_exame") and laudos._parse_data_exame(report["data_exame"]) is None:
        raise HTTPException(422, "Data do exame inválida.")
    if report.get("clinic_id") is not None:
        clinic_id = report["clinic_id"]
        if type(clinic_id) is not int or not db.query(Clinica).filter(Clinica.id == clinic_id).first():
            raise HTTPException(422, "Clínica inválida.")
    if report.get("veterinario_parceiro_id") is not None:
        if type(report["veterinario_parceiro_id"]) is not int:
            raise HTTPException(422, "Veterinário parceiro inválido.")
        laudos._load_veterinario_parceiro_or_422(db, report["veterinario_parceiro_id"])
    patient_changes = _patient_changes(source, data.paciente, data_referencia=referencia_documento(report.get("data_exame", source.laudo.data_exame), source.laudo.data_laudo))
    tutor_changes, create_tutor = _tutor_changes(source, data.tutor)
    if patient_changes or create_tutor:
        _require_edit(db, user, "pacientes")
    if tutor_changes or create_tutor:
        _require_edit(db, user, "tutores")
    temps, temp_configs = _validate_images(db, source, data.imagens, snapshot)

    new_portal_path = old_portal_path = None
    now = datetime.now(timezone.utc)
    try:
        claimed = db.execute(update(LaudoEditorDraft).where(
            LaudoEditorDraft.id == draft.id,
            LaudoEditorDraft.revision == data.expected_draft_revision,
            LaudoEditorDraft.closed_at.is_(None),
        ).values(revision=draft.revision + 1, closed_at=now, updated_at=now)
            .execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            _conflict("O rascunho mudou em outra requisição.", code="WORKSPACE_CHANGED")
        for key, value in patient_changes.items():
            setattr(source.paciente, key, value)
        if "nome" in patient_changes:
            source.paciente.nome_key = laudos._gerar_nome_key(source.paciente.nome)
        if create_tutor:
            new_tutor = Tutor(**tutor_changes, nome_key=laudos._gerar_nome_key(tutor_changes["nome"]),
                              identificacao_pendente=True, origem_cadastro="Cadastro explícito pela edição do laudo", ativo=1)
            db.add(new_tutor)
            db.flush()
            source.paciente.tutor_id = new_tutor.id
        elif tutor_changes:
            for key, value in tutor_changes.items():
                setattr(source.tutor, key, value)
            if "nome" in tutor_changes:
                source.tutor.nome_key = laudos._gerar_nome_key(source.tutor.nome)
        if data.imagens:
            images_by_id = {image.id: image for image in source.imagens}
            for config in data.imagens.persistidas:
                image = images_by_id[config.id]
                image.ordem, image.incluir_no_pdf, image.descricao = config.ordem, config.incluir_no_pdf, config.descricao
            for image_id in data.imagens.removidas_ids:
                images_by_id[image_id].ativo = 0
            for temp in temps:
                config = temp_configs[temp.id]
                db.add(ImagemLaudo(laudo_id=laudo_id, nome_arquivo=temp.nome_arquivo, tipo_mime=temp.tipo_mime,
                                  tamanho_bytes=temp.tamanho_bytes, conteudo=temp.conteudo,
                                  ordem=config.ordem, descricao=config.descricao, incluir_no_pdf=config.incluir_no_pdf, ativo=1))
                db.delete(temp)
        # Flush all images and demographics BEFORE the report/portal PDF is rendered.
        db.flush()
        _, _, old_portal_path, new_portal_path = laudos._atualizar_laudo_transacional(
            source.laudo, report, db, user, commit=False)
        db.add(LaudoEditorDraftRequest(draft_row_id=draft.id, request_id=request_id,
                                      operation="apply", payload_hash=fingerprint,
                                      revision=data.expected_draft_revision + 1, updated_at=now))
        db.commit()
    except Exception as error:
        db.rollback()
        laudos.remove_atendimento_attachment_file(new_portal_path)
        if isinstance(error, (IntegrityError, OperationalError)):
            if _is_write_collision(error):
                _conflict("Outra requisição alterou o rascunho. Confira a cópia salva.", code="WORKSPACE_CHANGED")
            raise HTTPException(503, "Não foi possível confirmar a atualização. Confira o rascunho antes de tentar novamente.") from None
        raise
    if old_portal_path and old_portal_path != new_portal_path:
        laudos.remove_atendimento_attachment_file(old_portal_path)
    return result
