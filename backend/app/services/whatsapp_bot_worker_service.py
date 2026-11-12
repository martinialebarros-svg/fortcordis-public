from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta
from app.services.whatsapp_bot_prompt import MAX_HISTORICO_MENSAGENS
from app.services.whatsapp_bot_gates import (
    detecta_cortesia,
    detecta_emergencia,
    detecta_pedido_humano,
    is_customer_service_window_open,
    is_locally_paused,
    is_supported_message_type,
    is_whatsapp_bot_enabled,
    pause_conversation,
    resolve_conversation_mode,
    resolve_conversation_state,
)
from app.services.whatsapp_bot_generation import gerar_resposta, IDENTITY_HANDOFF_REASONS, _historico_do_contexto
from app.services.whatsapp_bot_delivery_service import deliver_automatic_reply
from app.services.whatsapp_bot_handoff_service import (
    EMERGENCY_FIXED_MESSAGE,
    build_handoff_message,
    trigger_active_handoff,
)
from app.services.whatsapp_bot_queue_service import enqueue_job_for_inbound_message
from app.services.whatsapp_contexto_selecao_service import lock_contexto, resposta_contexto_vigente, carregar_selecao

logger = logging.getLogger(__name__)

_SENSITIVE_QUERY_RE = re.compile(r"([?&](?:phone|telefone|wa_identity)=)[^&\s]+", re.IGNORECASE)
_PHONE_LIKE_RE = re.compile(r"(?<!\d)\+?\d{8,15}(?!\d)")

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()
_WORKER_STOP_EVENT = threading.Event()
_WORKER_RUN_LOCK = threading.Lock()
_CYCLE_COUNT = 0
_LAST_CYCLE_AT: Optional[datetime] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_job_error(exc: Exception) -> str:
    """Mensagem operacional sem telefone completo nem query string sensivel."""
    message = str(exc or "Erro inesperado.")
    message = _SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]", message)
    message = _PHONE_LIKE_RE.sub("[REDACTED]", message)
    return message[:800]


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _distributed_lock_enabled() -> bool:
    return bool(settings.WHATSAPP_BOT_SCHEDULER_DISTRIBUTED_LOCK_ENABLED)


def _distributed_lock_key() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_SCHEDULER_DISTRIBUTED_LOCK_KEY, 80433003)
    return parsed if parsed > 0 else 80433003


def _try_acquire_pg_lock(db: Session, *, lock_key: int) -> bool:
    row = db.execute(
        text("SELECT pg_try_advisory_lock(:lock_key) AS locked"),
        {"lock_key": lock_key},
    ).fetchone()
    if not row:
        return False
    if hasattr(row, "_mapping"):
        return bool(row._mapping.get("locked"))
    return bool(row[0])


def _release_pg_lock(db: Session, *, lock_key: int) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})


def _max_attempts() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_MAX_ATTEMPTS, 3)
    return parsed if parsed > 0 else 3


def _worker_poll_seconds() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_SCHEDULER_POLL_SECONDS, 5)
    if parsed < 1:
        return 1
    if parsed > 300:
        return 300
    return parsed


def _reconcile_every_cycles() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_RECONCILE_EVERY_CYCLES, 60)
    return parsed if parsed > 0 else 60


def _reconcile_window_minutes() -> int:
    parsed = _safe_int(settings.WHATSAPP_BOT_RECONCILE_WINDOW_MINUTES, 30)
    return parsed if parsed > 0 else 30


def _fetch_next_due_job(db: Session, *, now: datetime) -> Optional[WhatsAppBotJob]:
    query = (
        db.query(WhatsAppBotJob)
        .filter(
            WhatsAppBotJob.status == "pending",
            WhatsAppBotJob.scheduled_for <= now,
            WhatsAppBotJob.attempts < _max_attempts(),
        )
        .order_by(WhatsAppBotJob.scheduled_for.asc(), WhatsAppBotJob.id.asc())
    )
    if _is_postgres(db):
        query = query.with_for_update(skip_locked=True)
    return query.first()


def _record_resposta(
    db: Session,
    job: WhatsAppBotJob,
    *,
    decisao: str,
    motivo: str,
    texto_gerado: Optional[str] = None,
    modelo: Optional[str] = None,
    prompt_version: Optional[str] = None,
    tools_usadas: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    latencia_ms: Optional[int] = None,
    resolution: Optional[str] = None,
    match_type: Optional[str] = None,
    clinica_id: Optional[int] = None,
    contexto_chave: Optional[str] = None,
) -> WhatsAppBotResposta:
    resposta = WhatsAppBotResposta(
        job_id=job.id,
        wa_identity=job.wa_identity,
        conversation_id=job.conversation_id,
        decisao=decisao,
        motivo=motivo,
        texto_gerado=texto_gerado,
        modelo=modelo,
        prompt_version=prompt_version,
        tools_usadas=tools_usadas,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latencia_ms=latencia_ms,
        resolution=resolution,
        match_type=match_type,
        clinica_id=clinica_id,
        contexto_chave=contexto_chave,
    )
    db.add(resposta)
    return resposta


def _process_job(db: Session, job: WhatsAppBotJob) -> str:
    """Decide, persiste e entrega apenas respostas elegiveis e liberadas."""
    anterior = db.query(WhatsAppBotResposta).filter(
        WhatsAppBotResposta.job_id == job.id
    ).order_by(WhatsAppBotResposta.id.desc()).first()
    if anterior is not None:
        if anterior.decisao in ("auto_pending", "sending"):
            deliver_automatic_reply(db, job, anterior)
        if anterior.motivo in IDENTITY_HANDOFF_REASONS:
            estado_handoff = resolve_conversation_state(db, job.wa_identity)
            if not estado_handoff or estado_handoff.handoff_motivo != anterior.motivo:
                _handoff_operacional(db, job, anterior.motivo)
        from app.services.whatsapp_bot_agendamento import encaminhar
        encaminhar(db, anterior)
        job.status = "done"
        return "done"

    if not is_whatsapp_bot_enabled():
        _record_resposta(db, job, decisao="suppressed", motivo="bot_desabilitado")
        job.status = "done"
        return "done"

    estado = resolve_conversation_state(db, job.wa_identity)
    modo = resolve_conversation_mode(db, job.wa_identity, estado=estado)
    if modo == "off":
        _record_resposta(db, job, decisao="suppressed", motivo="modo_off")
        job.status = "done"
        return "done"

    client_config = _bot_internal_client_config()
    if client_config is None:
        raise RuntimeError("Servico interno do WhatsApp nao configurado (URL/token ausentes).")
    base_url, headers, timeout = client_config

    conversation = _fetch_conversation_by_phone(
        base_url=base_url, headers=headers, timeout=timeout, wa_identity=job.wa_identity
    )
    if conversation is None:
        raise RuntimeError(f"Conversa nao encontrada no servico WhatsApp para o job {job.id}.")

    # A busca e por telefone e o job carrega a conversa que o originou. Se as
    # duas divergirem, o estado lido (claim, janela, ultima mensagem) e de
    # OUTRA conversa - responder com base nisso seria pior do que nao
    # responder. Termina aqui, sem retry: o proximo job reavalia do zero.
    conversa_encontrada = str(conversation.get("id") or "").strip()
    if conversa_encontrada and conversa_encontrada != str(job.conversation_id or "").strip():
        _record_resposta(db, job, decisao="suppressed", motivo="conversa_divergente")
        job.status = "done"
        return "done"

    last_message = _last_message_from_conversation(conversation)
    if last_message is None:
        # A visão do bot pode ficar vazia numa conversa só com reações
        # recebidas. Encerra também jobs antigos desses eventos sem handoff.
        _record_resposta(db, job, decisao="suppressed", motivo="conversa_atualizada")
        job.status = "done"
        return "done"
    if last_message.get("type") == "reaction" and not last_message.get("from_me"):
        # Node anterior ainda pode ignorar bot_context durante uma publicação.
        # Não perder a pergunta nem gastar retries enquanto ele é atualizado.
        if last_message.get("wa_message_id") != job.wa_message_id:
            job.status = "pending"
            job.scheduled_for = _utc_now() + timedelta(seconds=max(30, _worker_poll_seconds()))
            job.last_error = "Aguardando contexto do WhatsApp sem reacoes recebidas."
            return "deferred"
        # Um job legado da própria reação não representa uma solicitação.
        _record_resposta(db, job, decisao="suppressed", motivo="sem_pergunta")
        job.status = "done"
        return "done"

    # Usa apenas textos recentes e contíguos. Emergência de um fragmento
    # anterior deve continuar prioritária mesmo com o bot pausado.
    historico = _fetch_historico(base_url=base_url, headers=headers, timeout=timeout,
        conversation_id=job.conversation_id, quantidade=_historico_mensagens() + 1)[:-1]
    from app.services.whatsapp_bot_continuidade import agrupar_fragmentos
    from app.services.whatsapp_bot_mensagens_automaticas import mensagem_automatica, sem_aviso_automatico
    historico_bruto = historico
    corpo, historico = agrupar_fragmentos(
        [sem_aviso_automatico(item) for item in historico],
        sem_aviso_automatico(last_message),
    )
    if mensagem_automatica(last_message) and not corpo.strip():
        _record_resposta(db, job, decisao="suppressed", motivo="mensagem_automatica")
        job.status = "done"
        return "done"

    # RF-023 (emergencia): prioridade maxima, nao passa pelo gerador e ignora
    # pausa/janela - e o unico handoff que se mantem em qualquer horario.
    if not last_message.get("from_me") and detecta_emergencia(corpo):
        trigger_active_handoff(
            db,
            wa_identity=job.wa_identity,
            conversation_id=job.conversation_id,
            motivo="emergencia",
            nivel="critico",
            titulo="Possivel emergencia recebida no WhatsApp",
            mensagem_alerta=(
                f"Mensagem com termos de emergencia detectada na conversa {job.conversation_id}. "
                "Verifique com urgencia."
            ),
        )
        _record_resposta(
            db, job, decisao="handoff", motivo="emergencia", texto_gerado=EMERGENCY_FIXED_MESSAGE
        )
        job.status = "done"
        return "done"

    from app.services.whatsapp_bot_continuidade import pedido_assumido
    if is_locally_paused(estado) or pedido_assumido(db, job.wa_identity, job.conversation_id):
        _record_resposta(db, job, decisao="suppressed", motivo="pausado")
        job.status = "done"
        return "done"

    # RF-010: mensagem humana (from_me=true) ou claim de atendente pausa o
    # bot - reavaliado a cada job, entao uma pausa comecada depois deste job
    # ter sido enfileirado ainda e pega antes de qualquer resposta.
    if last_message.get("from_me") and last_message.get("origem") == "bot":
        _record_resposta(db, job, decisao="suppressed", motivo="conversa_atualizada")
        job.status = "done"
        return "done"

    if conversation.get("last_agent_id") or last_message.get("from_me"):
        pause_conversation(db, job.wa_identity)
        _record_resposta(db, job, decisao="suppressed", motivo="pausado")
        job.status = "done"
        return "done"

    mensagem_id = last_message.get("wa_message_id")
    if mensagem_id and mensagem_id != job.wa_message_id:
        _record_resposta(db, job, decisao="suppressed", motivo="conversa_atualizada")
        job.status = "done"
        return "done"

    from app.services.whatsapp_bot_agenda_receipts import confirmacao_agenda_processada
    if confirmacao_agenda_processada(
        db, wa_identity=job.wa_identity, wa_message_id=str(mensagem_id or ""),
        message_type=last_message.get("type"),
    ):
        # Abrange jobs legados e reconciliação após o callback. O clique
        # continua na fronteira da conversa: não ressuscita textos anteriores.
        _record_resposta(db, job, decisao="suppressed", motivo="confirmacao_agenda_processada")
        job.status = "done"
        return "done"

    if not is_supported_message_type(last_message.get("type")):
        _handoff_operacional(db, job, "tipo_nao_suportado")
        _record_resposta(db, job, decisao="handoff", motivo="tipo_nao_suportado")
        job.status = "done"
        return "done"

    selecao = carregar_selecao(db, job.wa_identity)
    if selecao is not None:
        limite = {"selecao": {"versao": selecao.versao, "updated_at": selecao.updated_at}}
        if not _historico_do_contexto([last_message], limite):
            _record_resposta(db, job, decisao="suppressed", motivo="contexto_alterado")
            job.status = "done"
            return "done"
        # Emergencia ja foi triada sobre todos os fragmentos. Handoff comum e
        # cortesia consideram apenas mensagens posteriores a escolha da equipe.
        corpo, historico = agrupar_fragmentos(
            [sem_aviso_automatico(item) for item in _historico_do_contexto(historico_bruto, limite) or []],
            sem_aviso_automatico(last_message),
        )

    if detecta_pedido_humano(corpo):
        texto_handoff = build_handoff_message(db)
        trigger_active_handoff(
            db,
            wa_identity=job.wa_identity,
            conversation_id=job.conversation_id,
            motivo="pedido_humano",
            nivel="aviso",
            titulo="Cliente pediu atendimento humano no WhatsApp",
            mensagem_alerta=f"Pedido de atendimento humano na conversa {job.conversation_id}.",
        )
        _record_resposta(db, job, decisao="handoff", motivo="pedido_humano", texto_gerado=texto_handoff)
        job.status = "done"
        return "done"

    if not is_customer_service_window_open(_parse_conversation_timestamp(conversation.get("last_inbound_at"))):
        _record_resposta(db, job, decisao="suppressed", motivo="janela_fechada")
        job.status = "done"
        return "done"

    # RF-P11: cortesia nao pede resposta. Fica imediatamente antes da geracao
    # de proposito - e o unico ponto onde este portao economiza algo, e os
    # portoes anteriores (emergencia, pedido de humano, janela) continuam
    # vencendo. Um "obrigada" nao pode consumir LLM para depois ser barrado por
    # `sem_fonte`: alem do custo, isso poluiria a taxa de bloqueio, que existe
    # para medir problema de qualidade e e insumo da decisao de `auto`.
    from app.services.whatsapp_bot_agendamento import confirmacao_de_coleta_ativa, saudacao_inicial
    from app.services.whatsapp_bot_disponibilidade import resposta_ao_convite_pendente
    if (detecta_cortesia(corpo)
            and not confirmacao_de_coleta_ativa(db, job.wa_identity, corpo)
            and not resposta_ao_convite_pendente(db, job.wa_identity, corpo, job.conversation_id)
            and not saudacao_inicial(db, job.wa_identity, corpo)):
        _record_resposta(db, job, decisao="suppressed", motivo="sem_pergunta")
        job.status = "done"
        return "done"

    resultado = gerar_resposta(
        db,
        conversation_id=str(job.conversation_id),
        wa_identity=job.wa_identity,
        corpo_mensagem=corpo,
        modo=modo,
        estado=estado,
        historico=historico,
        historico_bruto=historico_bruto,
        mensagem_atual=last_message,
    )
    resposta = _record_resposta(
        db,
        job,
        decisao=resultado.decisao,
        motivo=resultado.motivo,
        texto_gerado=resultado.texto_gerado,
        modelo=resultado.modelo,
        prompt_version=resultado.prompt_version,
        tools_usadas=resultado.tools_usadas,
        input_tokens=resultado.input_tokens,
        output_tokens=resultado.output_tokens,
        latencia_ms=resultado.latencia_ms,
        resolution=resultado.resolution,
        match_type=resultado.match_type,
        clinica_id=resultado.clinica_id,
        contexto_chave=resultado.contexto_chave,
    )
    if resultado.contexto_chave is not None:
        # Nenhum complemento/coleta/handoff do contexto antigo pode ser aplicado.
        lock_contexto(db, job.wa_identity)
        if not resposta_contexto_vigente(db, resposta):
            resposta.decisao = "suppressed"
            resposta.motivo = "contexto_alterado"
            job.status = "done"
            return "done"
    from app.services.whatsapp_bot_continuidade import registrar_complemento
    registrar_complemento(db, resposta)
    aviso_identidade = resultado.decisao == "handoff" and resultado.motivo in IDENTITY_HANDOFF_REASONS
    if resultado.decisao in ("handoff", "blocked") and not aviso_identidade:
        _handoff_operacional(db, job, resultado.motivo)
    if (resultado.decisao == "draft" or aviso_identidade) and resultado.auto_elegivel and settings.WHATSAPP_BOT_AUTO_SEND_ENABLED:
        resposta.decisao = "auto_pending"
        db.commit()
        deliver_automatic_reply(db, job, resposta)
    if aviso_identidade and resposta.motivo in IDENTITY_HANDOFF_REASONS:
        # Depois do aviso neutro, mantem atendimento humano e pausa explicita.
        _handoff_operacional(db, job, resultado.motivo)
    from app.services.whatsapp_bot_agendamento import encaminhar
    encaminhar(db, resposta)
    job.status = "done"
    return "done"


def _handoff_operacional(db: Session, job: WhatsAppBotJob, motivo: str) -> None:
    trigger_active_handoff(
        db, wa_identity=job.wa_identity, conversation_id=job.conversation_id,
        motivo=motivo[:50], nivel="aviso", titulo="Atendimento WhatsApp precisa da equipe",
        mensagem_alerta=f"Continue o atendimento na conversa {job.conversation_id}.",
    )


def _recover_interrupted_jobs(db: Session) -> None:
    cutoff = _utc_now() - timedelta(seconds=max(300, settings.WHATSAPP_BOT_PROCESSING_LEASE_SECONDS))
    rows = db.query(WhatsAppBotJob).filter(
        WhatsAppBotJob.status == "processing", WhatsAppBotJob.updated_at < cutoff,
    ).all()
    for job in rows:
        job.attempts = int(job.attempts or 0) + 1
        job.status = "pending" if job.attempts < _max_attempts() else "error"
        job.scheduled_for = _utc_now()
        job.last_error = "Processamento interrompido; recuperado pelo worker."
        if job.status == "error":
            _handoff_operacional(db, job, "processamento_interrompido")
    db.commit()


def run_whatsapp_bot_worker_due_once(*, limit: int = 50) -> dict[str, int]:
    if not _WORKER_RUN_LOCK.acquire(blocking=False):
        return {"processed": 0, "done": 0, "errors": 0}

    db = SessionLocal()
    lock_connection = None
    lock_db = db
    pg_lock_key: Optional[int] = None
    pg_lock_acquired = False
    done = 0
    errors = 0
    processed = 0
    try:
        if _distributed_lock_enabled() and _is_postgres(db):
            # O lock de sessao precisa da MESMA conexao ate a liberacao.
            # Session.commit() pode devolver a conexao ao pool.
            lock_connection = db.get_bind().connect()
            lock_db = Session(bind=lock_connection)
            pg_lock_key = _distributed_lock_key()
            pg_lock_acquired = _try_acquire_pg_lock(lock_db, lock_key=pg_lock_key)
            lock_db.commit()  # Mantem o lock de sessao sem transacao ociosa.
            if not pg_lock_acquired:
                logger.info(
                    "Worker do bot de atendimento WhatsApp ignorou ciclo: lock distribuido ocupado (key=%s).",
                    pg_lock_key,
                )
                return {"processed": 0, "done": 0, "errors": 0}

        _recover_interrupted_jobs(db)
        max_rows = max(1, int(limit))
        while processed < max_rows:
            job = _fetch_next_due_job(db, now=_utc_now())
            if job is None:
                break
            processed += 1
            job.status = "processing"
            db.commit()

            try:
                # Stable run identity is shared by all retries. The lazy scope
                # consults Maps policy only if this job actually needs Google.
                from app.services.google_maps_cost_control import automatic_action

                with automatic_action("whatsapp_agenda", str(job.id)):
                    result = _process_job(db, job)
            except Exception as exc:
                db.rollback()
                safe_error = _safe_job_error(exc)
                # Nao use `logger.exception`: o traceback de HTTPStatusError
                # inclui a URL completa com `phone=` e vazaria o numero.
                logger.error(
                    "Falha inesperada ao processar job do bot de atendimento WhatsApp id=%s erro=%s",
                    job.id,
                    safe_error,
                )
                job.attempts = int(job.attempts or 0) + 1
                job.last_error = safe_error
                if job.attempts >= _max_attempts():
                    job.status = "error"
                    _handoff_operacional(db, job, "falha_processamento")
                else:
                    # Retry no proximo ciclo do worker, nao dentro desta mesma
                    # chamada - senao o job devido reentraria no `while` e
                    # queimaria todas as tentativas de uma vez.
                    job.status = "pending"
                    job.scheduled_for = _utc_now() + timedelta(seconds=_worker_poll_seconds())
                result = "error"

            if result == "done":
                done += 1
            elif result == "error":
                errors += 1

            db.commit()

        return {"processed": processed, "done": done, "errors": errors}
    finally:
        if pg_lock_key is not None and pg_lock_acquired:
            try:
                _release_pg_lock(lock_db, lock_key=pg_lock_key)
            except Exception:
                logger.exception("Falha ao liberar lock distribuido do worker do bot de atendimento WhatsApp.")
        if lock_connection is not None:
            lock_db.close()
            lock_connection.close()
        db.close()
        _WORKER_RUN_LOCK.release()


def _bot_internal_client_config() -> Optional[tuple[str, dict[str, str], int]]:
    base_url = str(settings.WHATSAPP_AGENDA_SERVICE_URL or "").strip().rstrip("/")
    token = str(settings.WHATSAPP_AGENDA_INTERNAL_TOKEN or "").strip()
    if not base_url or not token:
        return None
    timeout = max(1, int(settings.WHATSAPP_AGENDA_TIMEOUT_SECONDS or 15))
    return base_url, {"x-whatsapp-internal-token": token}, timeout


def _parse_conversation_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fetch_recently_active_conversations(
    *, base_url: str, headers: dict[str, str], timeout: int, window_minutes: int
) -> list[dict[str, Any]]:
    cutoff = _utc_now() - timedelta(minutes=window_minutes)
    try:
        response = httpx.get(
            f"{base_url}/conversations",
            params={"limit": 100, "bot_context": "true"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.exception("Falha ao consultar conversas do WhatsApp para reconciliacao do bot.")
        return []

    candidates: list[dict[str, Any]] = []
    for row in payload.get("data") or []:
        last_inbound_at = _parse_conversation_timestamp(row.get("last_inbound_at"))
        if last_inbound_at is not None and last_inbound_at >= cutoff:
            candidates.append(row)
    return candidates


def _fetch_last_message(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout: int,
    conversation_id: str,
    raise_on_error: bool = False,
) -> Optional[dict[str, Any]]:
    def _pagina(page: int) -> dict[str, Any]:
        response = httpx.get(
            f"{base_url}/conversations/{conversation_id}/messages",
            params={"limit": 1, "page": page, "bot_context": "true"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    try:
        # O endpoint e ASC paginado e nao aceita ordem: a ultima mensagem esta
        # na ULTIMA pagina, nao na primeira. Com `limit=1` a ultima pagina e
        # exatamente `total`, entao sao duas requisicoes minusculas em vez de
        # uma trazendo 200 linhas - e, ao contrario da versao anterior, esta
        # devolve a mensagem certa.
        payload = _pagina(1)
        total = int((payload.get("pagination") or {}).get("total") or 0)
        if total > 1:
            payload = _pagina(total)
    except Exception:
        if raise_on_error:
            raise
        logger.exception(
            "Falha ao consultar mensagens da conversa %s para reconciliacao do bot.", conversation_id
        )
        return None

    rows = payload.get("data") or []
    return rows[-1] if rows else None


def _last_message_from_conversation(conversation: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A ultima mensagem ja vem no payload da conversa, e na ordem certa.

    `GET /conversations` monta `last_message_*` por LATERAL com
    `ORDER BY created_at DESC, id DESC LIMIT 1`
    (`conversationsController.ts:128`). Buscar de novo em
    `/conversations/:id/messages` gastava uma chamada HTTP e trazia a
    mensagem ERRADA: aquele endpoint e ASC paginado, entao `page=1&limit=200`
    devolvia a 200a mais ANTIGA em conversa com mais de 200 mensagens.

    `last_message_at` e o discriminador de "existe mensagem": `body` pode
    ser vazio de forma legitima (imagem sem legenda).
    """
    if conversation.get("last_message_at") is None:
        return None
    return {
        "body": conversation.get("last_message_body"),
        "wa_message_id": conversation.get("last_message_wa_message_id"),
        "origem": conversation.get("last_message_origem"),
        "from_me": conversation.get("last_message_from_me"),
        "type": conversation.get("last_message_type"),
        "created_at": conversation.get("last_message_at"),
    }




def _historico_mensagens() -> int:
    """Quantas mensagens anteriores vao ao prompt. `0` desliga a memoria.

    Configuravel para poder ser desligada sem deploy se o custo por turno ou
    a qualidade da resposta piorarem no piloto.
    """
    parsed = _safe_int(settings.WHATSAPP_BOT_HISTORICO_MENSAGENS, 8)
    return max(0, min(parsed, MAX_HISTORICO_MENSAGENS))


def _fetch_historico(
    *, base_url: str, headers: dict[str, str], timeout: int, conversation_id: str, quantidade: int
) -> list[dict[str, Any]]:
    """Ultimas `quantidade` mensagens da conversa, em ordem cronologica.

    Mesma armadilha de `_fetch_last_message`: o endpoint e ASC paginado e nao
    aceita ordem, entao as mensagens recentes estao na ULTIMA pagina, nao na
    primeira. Com `limit=N` a ultima pagina costuma vir INCOMPLETA (total=25,
    limit=10 -> pagina 3 tem 5 itens), entao buscar so ela devolveria menos
    contexto do que o pedido; nesse caso a anterior tambem e lida e as duas
    sao concatenadas. No maximo tres requisicoes.

    Falha de rede aqui NAO derruba o turno: historico e apoio, nao fonte. Sem
    ele o bot responde como respondia antes desta feature.
    """
    if quantidade <= 0:
        return []

    def _pagina(page: int) -> dict[str, Any]:
        response = httpx.get(
            f"{base_url}/conversations/{conversation_id}/messages",
            params={"limit": quantidade, "page": page, "bot_context": "true"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    try:
        primeira = _pagina(1)
        total = int((primeira.get("pagination") or {}).get("total") or 0)
        if total <= quantidade:
            linhas = list(primeira.get("data") or [])
        else:
            ultima = -(-total // quantidade)  # teto da divisao
            linhas = list(_pagina(ultima).get("data") or [])
            if len(linhas) < quantidade and ultima > 1:
                linhas = list(_pagina(ultima - 1).get("data") or []) + linhas
    except Exception:
        logger.exception(
            "Falha ao buscar historico da conversa %s; o turno segue sem ele.", conversation_id
        )
        return []

    return linhas[-quantidade:]


def _fetch_conversation_by_phone(
    *, base_url: str, headers: dict[str, str], timeout: int, wa_identity: str
) -> Optional[dict[str, Any]]:
    """Usada pelos portoes (RF-010/RF-012): uma unica conversa, pelo telefone

    canonico, para saber se esta reivindicada por um atendente (`last_agent_id`)
    e qual o `last_inbound_at` real (fonte da janela de 24h).
    """
    try:
        response = httpx.get(
            f"{base_url}/conversations",
            params={"phone": wa_identity, "limit": 1, "bot_context": "true"},
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Falha ao consultar conversa no servico WhatsApp ({type(exc).__name__})."
        ) from None
    rows = payload.get("data") or []
    return rows[0] if rows else None


def run_reconciliation_sweep(db: Session) -> dict[str, int]:
    """RF-006: cobre o caso do backend principal estar fora do ar no momento

    do webhook. So enfileira a ultima mensagem inbound de conversas ativas
    dentro da janela configurada, quando ainda nao existe job para ela -
    `enqueue_job_for_inbound_message` ja cuida do dedupe por wa_message_id.
    """
    client_config = _bot_internal_client_config()
    if client_config is None:
        return {"checked": 0, "enqueued": 0}
    base_url, headers, timeout = client_config

    candidates = _fetch_recently_active_conversations(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        window_minutes=_reconcile_window_minutes(),
    )

    enqueued = 0
    for conversation in candidates:
        conversation_id = str(conversation.get("id") or "").strip()
        wa_identity = str(conversation.get("wa_phone_number") or "").strip()
        if not conversation_id or not wa_identity:
            continue

        last_message = _fetch_last_message(
            base_url=base_url, headers=headers, timeout=timeout, conversation_id=conversation_id
        )
        if not last_message or last_message.get("from_me"):
            continue

        # Uma reação pode atualizar a atividade da conversa, mas não deve
        # ressuscitar uma pergunta antiga na visão filtrada do bot.
        message_time = _parse_conversation_timestamp(last_message.get("created_at"))
        cutoff = _utc_now() - timedelta(minutes=_reconcile_window_minutes())
        if message_time is None or message_time < cutoff:
            continue

        wa_message_id = str(last_message.get("wa_message_id") or "").strip()
        if not wa_message_id:
            continue

        if enqueue_job_for_inbound_message(
            db,
            wa_identity=wa_identity,
            conversation_id=conversation_id,
            wa_message_id=wa_message_id,
            message_type=last_message.get("type"),
        ):
            enqueued += 1

    return {"checked": len(candidates), "enqueued": enqueued}


def _run_reconciliation_cycle() -> None:
    db = SessionLocal()
    try:
        result = run_reconciliation_sweep(db)
        if result.get("enqueued"):
            logger.info(
                "Reconciliacao do bot de atendimento WhatsApp enfileirou %s job(s) de %s conversa(s) verificada(s).",
                result.get("enqueued"),
                result.get("checked"),
            )
    except Exception:
        logger.exception("Falha na reconciliacao do bot de atendimento WhatsApp.")
    finally:
        db.close()


def _count_pending_jobs() -> int:
    db = SessionLocal()
    try:
        return db.query(WhatsAppBotJob).filter(WhatsAppBotJob.status == "pending").count()
    except Exception:
        logger.exception("Falha ao contar jobs pendentes do bot de atendimento WhatsApp.")
        return 0
    finally:
        db.close()


def _worker_main() -> None:
    global _CYCLE_COUNT, _LAST_CYCLE_AT
    while not _WORKER_STOP_EVENT.is_set():
        try:
            run_whatsapp_bot_worker_due_once(limit=50)
            _CYCLE_COUNT += 1
            if _CYCLE_COUNT % _reconcile_every_cycles() == 0:
                _run_reconciliation_cycle()
        except Exception:
            logger.exception("Falha no worker do bot de atendimento do WhatsApp.")
        finally:
            _LAST_CYCLE_AT = _utc_now()
        if _WORKER_STOP_EVENT.wait(_worker_poll_seconds()):
            break


def get_whatsapp_bot_worker_runtime_state() -> dict[str, Any]:
    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        thread_alive = bool(thread and thread.is_alive())
        worker_started = thread is not None
        stop_signal_set = _WORKER_STOP_EVENT.is_set()
        last_cycle_at = _LAST_CYCLE_AT

    enabled = is_whatsapp_bot_enabled()
    if not thread_alive:
        status = "stopped"
    elif enabled:
        status = "running"
    else:
        status = "idle"

    return {
        "enabled": enabled,
        "status": status,
        "thread_alive": thread_alive,
        "worker_started": worker_started,
        "stop_signal_set": stop_signal_set,
        "poll_seconds": _worker_poll_seconds(),
        "pending_jobs": _count_pending_jobs(),
        "last_cycle_at": last_cycle_at.isoformat() if last_cycle_at else None,
    }


def start_whatsapp_bot_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_STOP_EVENT.clear()
        _WORKER_THREAD = threading.Thread(
            target=_worker_main,
            name="whatsapp-bot-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()


def shutdown_whatsapp_bot_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        thread = _WORKER_THREAD
        if not thread:
            return
        _WORKER_STOP_EVENT.set()
    thread.join(timeout=5)
    with _WORKER_LOCK:
        _WORKER_THREAD = None
