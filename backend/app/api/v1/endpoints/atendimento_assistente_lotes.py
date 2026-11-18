"""Private resumable uploads and draft-only batch analysis."""
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.endpoints.atendimento_assistente import _preparar, _auditar, _contexto
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.atendimento_assistente_lote import AtendimentoAssistenteLote as Lote, AtendimentoAssistenteLoteArquivo as Arquivo
from app.models.user import User
from app.schemas.atendimento_assistente_lote import LoteEntrada, RevisaoRacaEntrada, RevogacaoRevisaoRacaEntrada
from app.services import atendimento_assistente_lotes as service
from app.services.atendimento_assistente import AssistenteError
from app.schemas.atendimento_assistente_lote_limites import MAX_AUDIO_BYTES, MAX_AUDIO_PART_BYTES, MAX_EXAME_BYTES

def _private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(_private_response)])


@router.post("/{atendimento_id}/assistente/lotes", status_code=201)
def criar_lote(atendimento_id: int, payload: LoteEntrada, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    context, actor = _preparar(db, atendimento_id, payload.consentimento, current_user)
    job = service.create_job(db, context, actor.id, payload)
    result = service.serialize(db, job, current_user)
    db.rollback()
    _auditar(request, actor, atendimento_id, "ATENDIMENTO_IA_LOTE", {"lote_id": result["id"], "arquivos": len(payload.arquivos)})
    return result


@router.get("/{atendimento_id}/assistente/lotes/atual")
def lote_atual(atendimento_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    context = _contexto(db, atendimento_id)
    job = db.query(Lote).filter(Lote.usuario_id == current_user.id, Lote.atendimento_id == atendimento_id,
        Lote.paciente_id == context["paciente"]["id"],
        Lote.expires_at > service.datetime.utcnow()).order_by(Lote.created_at.desc()).first()
    if not job:
        return None
    try:
        service.get_job(db, atendimento_id, current_user.id, job.id)
    except HTTPException as exc:
        if exc.status_code in (409, 410):
            return None
        raise
    return service.serialize(db, job, current_user)


@router.get("/{atendimento_id}/assistente/lotes/{lote_id}")
def obter_lote(atendimento_id: int, lote_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return service.serialize(db, service.get_job(db, atendimento_id, current_user.id, str(lote_id)), current_user)


@router.put("/{atendimento_id}/assistente/lotes/{lote_id}/arquivos/{arquivo_id}")
async def enviar_arquivo(atendimento_id: int, lote_id: UUID, arquivo_id: UUID, arquivo: UploadFile = File(...), deslocamento: int | None = Query(None, ge=0), sha256: str | None = Header(None, alias="X-Audio-Sha256", pattern=r"^[a-f0-9]{64}$"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Authenticate before buffering bytes. Release the lookup transaction while receiving.
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id))
    item = db.get(Arquivo, (job.id, str(arquivo_id)))
    if not item:
        await arquivo.close()
        raise HTTPException(404, "Arquivo não encontrado neste conjunto.")
    if (deslocamento is None) != (sha256 is None) or (deslocamento is not None and item.tipo != "audio"):
        await arquivo.close()
        raise HTTPException(422, "Informe a posição e o identificador do áudio para enviar uma parte.")
    limite = min(item.tamanho, MAX_AUDIO_PART_BYTES if deslocamento is not None
                 else MAX_AUDIO_BYTES if item.tipo == "audio" else MAX_EXAME_BYTES)
    user_id = current_user.id
    db.rollback()
    try:
        content = await arquivo.read(limite + 1)
    finally:
        await arquivo.close()
    if len(content) > limite:
        raise HTTPException(413, "O arquivo excede o limite de envio.")
    def store():
        job = service.get_job(db, atendimento_id, user_id, str(lote_id), lock=True)
        if deslocamento is not None and sha256 is not None:
            job = service.upload_audio_part(db, job, str(arquivo_id), content, deslocamento, sha256)
        else:
            job = service.upload_file(db, job, str(arquivo_id), content)
        return service.serialize(db, job, current_user)
    return await run_in_threadpool(store)


@router.get("/{atendimento_id}/assistente/lotes/{lote_id}/arquivos/{arquivo_id}/original")
def original_arquivo(atendimento_id: int, lote_id: UUID, arquivo_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id))
    item = db.get(Arquivo, (job.id, str(arquivo_id)))
    if not item or not item.caminho or not Path(item.caminho).is_file():
        raise HTTPException(404, "Original indisponível. Confira o envio deste arquivo.")
    return FileResponse(item.caminho, filename=item.nome, media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{atendimento_id}/assistente/lotes/{lote_id}/iniciar")
def iniciar_lote(atendimento_id: int, lote_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id), lock=True)
    try:
        return service.serialize(db, service.start_job(db, job), current_user)
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/{atendimento_id}/assistente/lotes/{lote_id}/retomar")
def retomar_lote(atendimento_id: int, lote_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id), lock=True)
    try:
        return service.serialize(db, service.start_job(db, job, retry=True), current_user)
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc



def _review_race(atendimento_id, lote_id, payload, request, db, current_user, *, revoke=False):
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id), lock=True)
    try:
        job, event = service.review_race(db, job, payload, current_user, revoke=revoke)
        result = service.serialize(db, job, current_user)
        db.rollback()
    except AssistenteError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if event:
        _auditar(request, current_user, atendimento_id, "ATENDIMENTO_IA_REVISAO_RACA",
                 {"lote_id": str(lote_id), **event})
    return result


@router.post("/{atendimento_id}/assistente/lotes/{lote_id}/revisar-raca")
def revisar_raca_lote(atendimento_id: int, lote_id: UUID, payload: RevisaoRacaEntrada,
                      request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _review_race(atendimento_id, lote_id, payload, request, db, current_user)


@router.post("/{atendimento_id}/assistente/lotes/{lote_id}/revogar-revisao-raca")
def revogar_revisao_raca_lote(atendimento_id: int, lote_id: UUID, payload: RevogacaoRevisaoRacaEntrada,
                             request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _review_race(atendimento_id, lote_id, payload, request, db, current_user, revoke=True)


@router.delete("/{atendimento_id}/assistente/lotes/{lote_id}", status_code=204)
def apagar_lote(atendimento_id: int, lote_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = service.get_job(db, atendimento_id, current_user.id, str(lote_id), lock=True, validate_patient=False, allow_expired=True, allow_deleting=True)
    service.delete_job(db, job)
