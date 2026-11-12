from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_papel
from app.db.database import get_db
from app.models.user import User
from app.schemas.assistente_ia import (
    AssistenteIAAcaoDecisaoRequest,
    AssistenteIAAprendizadoCreateRequest,
    AssistenteIAAprendizadoDecisaoRequest,
    AssistenteIAChatRequest,
    AssistenteIAConhecimentoCreateRequest,
    AssistenteIAFeedbackCreateRequest,
    AssistenteIAMemoriaCreateRequest,
    AssistenteIAMemoriaDecisaoRequest,
    AssistenteIAMemoriaRollbackRequest,
    AssistenteIAMissaoCreateRequest,
    AssistenteIAMissaoUpdateRequest,
)
from app.services.assistente_ia_autonomy import (
    create_mission,
    enqueue_execution,
    enqueue_knowledge_index,
    enqueue_mission_now,
    latest_radar,
    list_executions,
    list_missions,
    run_radar_now,
    serialize_execution,
    update_mission,
)
from app.services.assistente_ia_clinics360 import (
    clinic_360_profile,
    compare_clinics_360,
    list_clinics_360,
)
from app.services.assistente_ia_management import (
    archive_document,
    assistant_metrics,
    create_document,
    create_feedback,
    create_learning,
    create_memory,
    decide_memory,
    decide_learning,
    executive_summary,
    list_clinical_drafts,
    list_documents,
    list_learnings,
    list_memories,
    list_memory_versions,
    list_pending_actions,
    list_regression_cases,
    rollback_memory,
)
from app.services.assistente_ia_service import (
    AssistenteIAProviderError,
    conversation_detail,
    create_conversation,
    get_owned_conversation,
    list_conversations,
    run_assistant_turn,
    serialize_conversation,
)
from app.services.assistente_ia_tools import decide_pending_action
from app.services.assistente_ia_voice import transcribe_voice_command
from app.services.auditoria_service import registrar_auditoria

router = APIRouter()


@router.get("/status")
def assistente_ia_status(
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "enabled": bool(settings.ASSISTENTE_IA_ENABLED),
        "configured": bool(str(settings.OPENAI_API_KEY or "").strip()),
        "model": str(settings.ASSISTENTE_IA_MODEL),
        "admin_only": True,
        "capabilities": [
            "resumo_executivo_diario",
            "faturamento",
            "agenda",
            "disponibilidade",
            "excecao_de_funcionamento_com_confirmacao",
            "criacao_de_horario_com_confirmacao",
            "reserva_com_confirmacao",
            "mensagem_whatsapp_manual",
            "debitos_pendentes",
            "exclusao_com_confirmacao",
            "remarcacao_e_cancelamento_com_confirmacao",
            "bloqueio_de_slots_com_confirmacao",
            "contatos_de_clinica_com_confirmacao",
            "memoria_supervisionada",
            "base_de_conhecimento_interna",
            "rascunhos_clinicos_sem_finalizacao_automatica",
            "caixa_central_de_aprovacoes",
            "feedback_e_metricas",
            "radar_proativo_somente_leitura",
            "missoes_recorrentes_somente_leitura",
            "memoria_semantica_com_fontes",
            "laboratorio_automatico_sem_execucao_de_ferramentas",
            "aprendizado_continuo_supervisionado",
            "versionamento_e_reversao_de_memorias",
            "regressoes_automaticas_de_memoria",
            "clinicas_360_somente_leitura",
            "planos_de_acao_360_com_aprovacao",
            "comandos_de_voz_com_revisao",
        ],
        "voice": {
            "enabled": True,
            "model": str(settings.ASSISTENTE_IA_VOICE_TRANSCRIPTION_MODEL),
            "max_seconds": int(settings.ASSISTENTE_IA_VOICE_MAX_SECONDS),
            "review_before_send": True,
            "audio_persisted": False,
        },
    }


@router.get("/clinicas-360")
def listar_clinicas_360_assistente_ia(
    periodo_dias: int = Query(90, ge=30, le=365),
    incluir_inativas: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return list_clinics_360(
        db,
        period_days=periodo_dias,
        include_inactive=incluir_inativas,
        limit=limit,
    )


@router.get("/clinicas-360/comparar")
def comparar_clinicas_360_assistente_ia(
    clinica_ids: list[int] = Query(..., min_length=2, max_length=10),
    periodo_dias: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    result = compare_clinics_360(db, clinica_ids, period_days=periodo_dias)
    if result.get("ok") is False:
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/clinicas-360/{clinic_id}")
def obter_clinica_360_assistente_ia(
    clinic_id: int,
    periodo_dias: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    result = clinic_360_profile(db, clinic_id, period_days=periodo_dias)
    if result.get("ok") is False:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.get("/radar")
def obter_radar_assistente_ia(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"execution": latest_radar(db, current_user)}


@router.post("/radar/executar")
def executar_radar_assistente_ia(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    execution = run_radar_now(db, current_user)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="radar",
        entidade_id=execution["id"],
        acao="ASSISTENTE_IA_RADAR_EXECUTADO",
        descricao="Administrador atualizou o radar proativo somente de leitura.",
        detalhes={"alertas": len((execution.get("output") or {}).get("alerts") or [])},
        request=request,
    )
    return {"execution": execution}


@router.get("/missoes")
def listar_missoes_assistente_ia(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_missions(db, current_user)}


@router.post("/missoes")
def criar_missao_assistente_ia(
    payload: AssistenteIAMissaoCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    mission = create_mission(
        db,
        current_user,
        title=payload.titulo,
        kind=payload.tipo,
        config=payload.configuracao,
        recurrence=payload.recorrencia,
        local_time=payload.horario_local,
        weekdays=payload.dias_semana,
        enabled=payload.enabled,
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="missao",
        entidade_id=mission["id"],
        acao="ASSISTENTE_IA_MISSAO_CRIADA",
        descricao="Administrador criou uma missao recorrente somente de leitura.",
        detalhes={"tipo": mission["type"], "recorrencia": mission["recurrence"]},
        request=request,
    )
    return {"mission": mission}


@router.patch("/missoes/{mission_id}")
def atualizar_missao_assistente_ia(
    mission_id: str,
    payload: AssistenteIAMissaoUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    raw = payload.model_dump(exclude_unset=True)
    changes = {
        "title": raw.get("titulo"),
        "config": raw.get("configuracao"),
        "recurrence": raw.get("recorrencia"),
        "local_time": raw.get("horario_local"),
        "weekdays": raw.get("dias_semana"),
        "enabled": raw.get("enabled"),
    }
    mission = update_mission(db, current_user, mission_id=mission_id, changes=changes)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="missao",
        entidade_id=mission["id"],
        acao="ASSISTENTE_IA_MISSAO_ATUALIZADA",
        descricao="Administrador atualizou uma missao recorrente da Mente.",
        detalhes={"tipo": mission["type"], "enabled": mission["enabled"]},
        request=request,
    )
    return {"mission": mission}


@router.post("/missoes/{mission_id}/executar")
def executar_missao_agora_assistente_ia(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    execution = enqueue_mission_now(db, current_user, mission_id=mission_id)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="missao_execucao",
        entidade_id=execution["id"],
        acao="ASSISTENTE_IA_MISSAO_ENFILEIRADA",
        descricao="Administrador solicitou execucao imediata de missao somente de leitura.",
        detalhes={"missao_id": mission_id, "tipo": execution["type"]},
        request=request,
    )
    return {"execution": execution}


@router.get("/execucoes")
def listar_execucoes_assistente_ia(
    tipo: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_executions(db, current_user, kind=tipo, limit=limit)}


@router.get("/avaliacoes")
def listar_avaliacoes_assistente_ia(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_executions(db, current_user, kind="eval_lab", limit=limit)}


@router.post("/avaliacoes/executar")
def executar_avaliacao_assistente_ia(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    execution = enqueue_execution(
        db,
        current_user,
        kind="eval_lab",
        input_data={"dataset": "assistente_ia_admin_cases.json"},
        source="manual",
    )
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="avaliacao",
        entidade_id=execution.id,
        acao="ASSISTENTE_IA_AVALIACAO_ENFILEIRADA",
        descricao="Administrador iniciou laboratorio seguro de roteamento da Mente.",
        detalhes={"modelo": str(settings.ASSISTENTE_IA_MODEL)},
        request=request,
    )
    return {"execution": serialize_execution(execution)}


@router.get("/resumo-executivo")
def obter_resumo_executivo_assistente_ia(
    data: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    try:
        reference = date.fromisoformat(data) if data else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Data invalida. Use YYYY-MM-DD.") from exc
    return executive_summary(db, current_user, reference=reference)


@router.get("/acoes")
def listar_aprovacoes_assistente_ia(
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_pending_actions(db, current_user, limit=limit)}


@router.get("/memorias")
def listar_memorias_assistente_ia(
    status: str | None = Query(default=None, max_length=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_memories(db, status=status)}


@router.post("/memorias")
def criar_memoria_assistente_ia(
    payload: AssistenteIAMemoriaCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    memory = create_memory(
            db,
            current_user,
            title=payload.titulo,
            content=payload.conteudo,
            category=payload.categoria,
            approve_immediately=True,
        )
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="memoria",
        entidade_id=memory["id"],
        acao="ASSISTENTE_IA_MEMORIA_CRIADA",
        descricao="Administrador criou uma memoria aprovada para a Mente FortCordis.",
        detalhes={"titulo": memory["title"], "categoria": memory["category"]},
        request=request,
    )
    return {"memory": memory}


@router.post("/memorias/{memory_id}/decisao")
def decidir_memoria_assistente_ia(
    memory_id: str,
    payload: AssistenteIAMemoriaDecisaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "memory": decide_memory(
            db,
            current_user,
            request,
            memory_id=memory_id,
            decision=payload.decisao,
        )
    }


@router.get("/memorias/{memory_id}/versoes")
def listar_versoes_memoria_assistente_ia(
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_memory_versions(db, memory_id=memory_id)}


@router.post("/memorias/{memory_id}/reverter")
def reverter_memoria_assistente_ia(
    memory_id: str,
    payload: AssistenteIAMemoriaRollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "memory": rollback_memory(
            db,
            current_user,
            request,
            memory_id=memory_id,
            target_version=payload.versao,
        )
    }


@router.get("/aprendizados")
def listar_aprendizados_assistente_ia(
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return list_learnings(db, current_user, status=status, limit=limit)


@router.post("/aprendizados")
def criar_aprendizado_assistente_ia(
    payload: AssistenteIAAprendizadoCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "learning": create_learning(
            db,
            current_user,
            request,
            title=payload.titulo,
            content=payload.conteudo,
            category=payload.categoria,
            target_memory_id=payload.memoria_alvo_id,
        )
    }


@router.post("/aprendizados/{learning_id}/decisao")
def decidir_aprendizado_assistente_ia(
    learning_id: str,
    payload: AssistenteIAAprendizadoDecisaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "learning": decide_learning(
            db,
            current_user,
            request,
            learning_id=learning_id,
            decision=payload.decisao,
            title=payload.titulo,
            content=payload.conteudo,
            category=payload.categoria,
        )
    }


@router.get("/aprendizados/regressoes")
def listar_regressoes_aprendizado_assistente_ia(
    incluir_arquivados: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_regression_cases(db, include_archived=incluir_arquivados, limit=limit)}


@router.get("/conhecimento")
def listar_conhecimento_assistente_ia(
    incluir_arquivados: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_documents(db, include_archived=incluir_arquivados)}


@router.post("/conhecimento")
def criar_conhecimento_assistente_ia(
    payload: AssistenteIAConhecimentoCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    if payload.indexar_semanticamente and not bool(settings.ASSISTENTE_IA_SEMANTIC_SEARCH_ENABLED):
        raise HTTPException(status_code=503, detail="A busca semantica esta desabilitada neste ambiente.")
    if payload.indexar_semanticamente and not str(settings.OPENAI_API_KEY or "").strip():
        raise HTTPException(status_code=503, detail="A credencial da OpenAI e necessaria para indexacao semantica.")
    document = create_document(
            db,
            current_user,
            title=payload.titulo,
            content=payload.conteudo,
            category=payload.categoria,
            source=payload.fonte,
            semantic_index=payload.indexar_semanticamente,
        )
    indexing = None
    if payload.indexar_semanticamente:
        indexing = enqueue_knowledge_index(db, current_user, document_id=document["id"])
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="conhecimento_documento",
        entidade_id=document["id"],
        acao="ASSISTENTE_IA_CONHECIMENTO_ADICIONADO",
        descricao="Administrador adicionou conteudo a base interna da Mente FortCordis.",
        detalhes={
            "titulo": document["title"],
            "categoria": document["category"],
            "indexacao_semantica": bool(payload.indexar_semanticamente),
        },
        request=request,
    )
    return {"document": document, "indexing": indexing}


@router.post("/conhecimento/{document_id}/reindexar")
def reindexar_conhecimento_assistente_ia(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    execution = enqueue_knowledge_index(db, current_user, document_id=document_id)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="conhecimento_documento",
        entidade_id=document_id,
        acao="ASSISTENTE_IA_CONHECIMENTO_REINDEXADO",
        descricao="Administrador solicitou reindexacao semantica de documento explicito.",
        detalhes={"execucao_id": execution["id"]},
        request=request,
    )
    return {"execution": execution}


@router.post("/conhecimento/{document_id}/arquivar")
def arquivar_conhecimento_assistente_ia(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    document = archive_document(db, document_id=document_id)
    registrar_auditoria(
        current_user=current_user,
        modulo="assistente_ia",
        entidade="conhecimento_documento",
        entidade_id=document["id"],
        acao="ASSISTENTE_IA_CONHECIMENTO_ARQUIVADO",
        descricao="Administrador arquivou conteudo da base interna da Mente FortCordis.",
        detalhes={"titulo": document["title"]},
        request=request,
    )
    return {"document": document}


@router.post("/feedbacks")
def registrar_feedback_assistente_ia(
    payload: AssistenteIAFeedbackCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {
        "feedback": create_feedback(
            db,
            current_user,
            message_id=payload.mensagem_id,
            rating=payload.avaliacao,
            category=payload.categoria,
            comment=payload.comentario,
            expected_correction=payload.correcao_esperada,
            request=request,
        )
    }


@router.get("/rascunhos-clinicos")
def listar_rascunhos_clinicos_assistente_ia(
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_clinical_drafts(db, current_user, limit=limit)}


@router.get("/metricas")
def obter_metricas_assistente_ia(
    dias: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return assistant_metrics(db, current_user, days=dias)


@router.get("/conversas")
def listar_conversas_assistente_ia(
    limit: int = Query(default=40, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return {"items": list_conversations(db, current_user, limit=limit)}


@router.post("/conversas")
def criar_conversa_assistente_ia(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return serialize_conversation(create_conversation(db, current_user))


@router.get("/conversas/{conversation_id}")
def obter_conversa_assistente_ia(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    return conversation_detail(db, current_user, conversation_id)


@router.post("/chat")
def conversar_com_assistente_ia(
    payload: AssistenteIAChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    conversation = (
        get_owned_conversation(db, current_user, payload.conversa_id)
        if payload.conversa_id
        else create_conversation(db, current_user)
    )
    try:
        return run_assistant_turn(
            db=db,
            current_user=current_user,
            request=request,
            message=payload.mensagem,
            conversation=conversation,
        )
    except AssistenteIAProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
            headers={"X-Assistente-Conversation-Id": str(conversation.id)},
        ) from exc


@router.post("/voz/transcrever")
async def transcrever_comando_voz_assistente_ia(
    request: Request,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    max_bytes = max(1, int(settings.ASSISTENTE_IA_VOICE_MAX_BYTES))
    file_name = arquivo.filename
    content_type = arquivo.content_type
    try:
        audio_bytes = await arquivo.read(max_bytes + 1)
    finally:
        await arquivo.close()
    try:
        return transcribe_voice_command(
            db=db,
            current_user=current_user,
            request=request,
            file_name=file_name,
            content_type=content_type,
            audio_bytes=audio_bytes,
        )
    except AssistenteIAProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/acoes/{action_id}/decisao")
def decidir_acao_assistente_ia(
    action_id: str,
    payload: AssistenteIAAcaoDecisaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_papel("admin")),
):
    action = decide_pending_action(
        db=db,
        current_user=current_user,
        request=request,
        action_id=action_id,
        decision=payload.decisao,
        observation=payload.observacao,
    )
    return {"action": action}
