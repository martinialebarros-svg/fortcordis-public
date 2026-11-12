"""Authenticated, draft-only assistance; no endpoint writes a clinical record."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.atendimento_clinico import AtendimentoClinico
from app.utils.paciente_idade import dados_idade_paciente
from app.models.paciente import Paciente
from app.models.user import User
from app.services.atendimento_audio import transcrever_gravacao
from app.services.atendimento_assistente import (
    ARQUIVO_MAX_BYTES,
    ARQUIVOS_MAX_BYTES,
    ARQUIVOS_MAX_COUNT,
    AUDIO_MAX_BYTES,
    TRANSCRICAO_MAX_CHARS,
    AssistenteError,
    OpenAIAtendimentoProvider,
    feature_status,
    require_enabled,
    validar_arquivo,
    validar_audio,
)
from app.services.auditoria_service import registrar_auditoria

router = APIRouter()


def _contexto(db: Session, atendimento_id: int) -> dict:
    atendimento = db.query(AtendimentoClinico).filter(AtendimentoClinico.id == atendimento_id).first()
    if not atendimento:
        raise HTTPException(404, "Atendimento não encontrado.")
    paciente = db.query(Paciente).filter(Paciente.id == atendimento.paciente_id).first()
    if not paciente:
        raise HTTPException(409, "O paciente do atendimento precisa ser conferido antes da análise.")
    return {
        "atendimento_id": atendimento.id,
        "data_atendimento": atendimento.data_atendimento.isoformat() if atendimento.data_atendimento else None,
        "paciente": {"id": paciente.id, "nome": paciente.nome, "especie": atendimento.especie or paciente.especie, "raca": paciente.raca, "sexo": paciente.sexo, "nascimento": paciente.nascimento, **dados_idade_paciente(paciente, data_referencia=atendimento.data_atendimento)},
        "triagem": {name: getattr(atendimento, name) for name in ("peso", "temperatura", "frequencia_cardiaca", "frequencia_respiratoria", "pressao_arterial", "saturacao_oxigenio", "mucosas", "hidratacao", "triagem_observacoes")},
        "consulta": {name: getattr(atendimento, name) for name in ("queixa_principal", "anamnese", "exame_fisico", "dados_clinicos", "diagnostico_principal", "diagnostico_secundario", "diagnostico_diferencial", "plano_terapeutico", "observacoes")},
    }


def _preparar(db: Session, atendimento_id: int, consentimento: bool, current_user: User) -> tuple[dict, SimpleNamespace]:
    if not consentimento:
        raise HTTPException(422, "Confirme a autorização para enviar o material à IA e revisar o resultado.")
    try:
        require_enabled()
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    context = _contexto(db, atendimento_id)
    actor = SimpleNamespace(id=current_user.id, nome=current_user.nome, email=current_user.email)
    # Do not hold a database connection for the duration of an external AI call.
    db.rollback()
    return context, actor


def _auditar(request: Request, actor: SimpleNamespace, atendimento_id: int, action: str, details: dict) -> None:
    registrar_auditoria(
        current_user=actor,
        modulo="atendimento_clinico",
        entidade="atendimento_assistente",
        entidade_id=atendimento_id,
        acao=action,
        descricao="Processamento assistido solicitado com revisão veterinária obrigatória; prontuário não alterado.",
        detalhes={**details, "consentimento": True, "revisao_obrigatoria": True},
        request=request,
    )


@router.get("/{atendimento_id}/assistente/status")
def status_assistente(atendimento_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    _ = current_user.id
    context = _contexto(db, atendimento_id)
    return {**feature_status(), "usuario_id": current_user.id, "paciente_id": context["paciente"]["id"]}


@router.post("/{atendimento_id}/assistente/transcrever")
async def transcrever_atendimento(
    atendimento_id: int,
    request: Request,
    audio: UploadFile | None = File(None),
    consentimento: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        context, actor = _preparar(db, atendimento_id, consentimento, current_user)
        if audio is None:
            raise AssistenteError("Nenhum arquivo de áudio chegou ao servidor. Selecione o original novamente.")
        content = await audio.read(AUDIO_MAX_BYTES + 1)
        nome, mime = validar_audio(audio.filename, audio.content_type, content)
        result = await run_in_threadpool(
            transcrever_gravacao,
            nome=nome, mime=mime, content=content,
            paciente_nome=context["paciente"]["nome"],
            provider_factory=OpenAIAtendimentoProvider,
        )
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    finally:
        if audio is not None:
            await audio.close()
    await run_in_threadpool(_auditar, request, actor, atendimento_id, "ATENDIMENTO_IA_TRANSCRICAO", {"modelo": result["modelo"], "audio_bytes": len(content)})
    return result


@router.post("/{atendimento_id}/assistente/analisar")
async def analisar_atendimento(
    atendimento_id: int,
    request: Request,
    transcricao: str = Form(""),
    arquivos: list[UploadFile] = File(default=[]),
    consentimento: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    context, actor = _preparar(db, atendimento_id, consentimento, current_user)
    uploads = arquivos or []
    try:
        transcript = transcricao.strip()
        if not transcript and not uploads:
            raise AssistenteError("Envie uma transcrição ou ao menos um exame para analisar.")
        if len(transcript) > TRANSCRICAO_MAX_CHARS:
            raise AssistenteError("A transcrição excede o limite de 80.000 caracteres.", 413)
        if len(uploads) > ARQUIVOS_MAX_COUNT:
            raise AssistenteError("Envie até 5 exames por análise.", 413)
        files = []
        total = 0
        for index, upload in enumerate(uploads, start=1):
            content = await upload.read(ARQUIVO_MAX_BYTES + 1)
            total += len(content)
            if total > ARQUIVOS_MAX_BYTES:
                raise AssistenteError("Os exames excedem o limite conjunto de 20 MB.", 413)
            files.append(await run_in_threadpool(validar_arquivo, upload.filename, upload.content_type, content, index))
        result = await run_in_threadpool(OpenAIAtendimentoProvider().analisar, transcript=transcript, context=context, files=files, user_id=actor.id)
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    finally:
        for upload in uploads:
            await upload.close()
    await run_in_threadpool(_auditar, request, actor, atendimento_id, "ATENDIMENTO_IA_ANALISE", {"modelo": result["modelo"], "esforco": result["esforco"], "arquivos": len(files), "bloqueado_integracao": result["bloqueado_integracao"]})
    return result
