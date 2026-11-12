"""Reações não substituem pedidos nem criam pausas; testes sem rede."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from tests import test_whatsapp_bot_process_job as cases
from app.api.v1.endpoints import whatsapp_agenda
from app.models.alerta_interno import AlertaInterno
from app.models.whatsapp_bot import WhatsAppBotJob, WhatsAppBotResposta, WhatsAppBotConversaEstado
from app.services import whatsapp_bot_worker_service as worker
from app.services.whatsapp_bot_queue_service import enqueue_job_for_inbound_message


@pytest.fixture
def db(tmp_path):
    factory, engine = cases.WhatsAppBotProcessJobTest()._build_session_factory(str(tmp_path))
    with factory() as session:
        yield session
    engine.dispose()


def test_reacao_no_webhook_preserva_pergunta_pendente_e_push(db):
    enqueue_job_for_inbound_message(db, wa_identity="test", conversation_id="49",
                                   wa_message_id="pergunta", message_type="text")
    pending = db.query(WhatsAppBotJob).one()
    scheduled = pending.scheduled_for
    payload = whatsapp_agenda.WhatsAppInboundMessageNotificationRequest(
        conversation_id="49", contact_label="Clínica teste", body_preview="Reagiu com 👍",
        wa_phone_number="test", wa_message_id="reacao", message_type="reaction",
    )
    with patch.object(whatsapp_agenda, "send_whatsapp_message_push_notification",
                      return_value={"sent": 0, "failed": 0, "deactivated": 0}) as push:
        result = whatsapp_agenda.notify_whatsapp_inbound_message(payload, None, db=db)
    assert not result["bot_job_enqueued"]
    push.assert_called_once()
    db.refresh(pending)
    assert pending.status == "pending" and pending.scheduled_for == scheduled
    assert db.query(WhatsAppBotJob).count() == 1
    assert not enqueue_job_for_inbound_message(db, wa_identity="test", conversation_id="49",
                                               wa_message_id="reacao", message_type="reaction")
    # Uma nova pergunta continua invalidando a anterior, como antes.
    assert enqueue_job_for_inbound_message(db, wa_identity="test", conversation_id="49",
                                           wa_message_id="outra-pergunta", message_type="text")
    db.refresh(pending)
    assert pending.status == "superseded"


@pytest.mark.parametrize("paused,assigned", [(False, False), (True, False), (False, True)])
def test_job_antigo_de_reacao_nao_cria_nem_renova_pausa(db, paused, assigned):
    helper = cases.WhatsAppBotProcessJobTest()
    job = helper._make_job(db)
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    if paused:
        db.add(WhatsAppBotConversaEstado(wa_identity=job.wa_identity, pausado_ate=until))
        db.commit()
    message = {"wa_message_id": job.wa_message_id, "type": "reaction",
               "from_me": False, "body": "Reagiu com 👍"}
    with ExitStack() as stack:
        stack.enter_context(patch.object(worker, "is_whatsapp_bot_enabled", return_value=True))
        stack.enter_context(patch.object(worker, "resolve_conversation_mode", return_value="auto"))
        stack.enter_context(patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)))
        stack.enter_context(patch.object(worker, "_fetch_conversation_by_phone", return_value={
            "id": job.conversation_id, "last_agent_id": 1 if assigned else None}))
        stack.enter_context(patch.object(worker, "_last_message_from_conversation", return_value=message))
        history = stack.enter_context(patch.object(worker, "_fetch_historico"))
        handoff = stack.enter_context(patch.object(worker, "trigger_active_handoff"))
        generator = stack.enter_context(patch.object(worker, "gerar_resposta"))
        pause = stack.enter_context(patch.object(worker, "pause_conversation"))
        assert worker._process_job(db, job) == "done"
        db.flush()
    response = db.query(WhatsAppBotResposta).one()
    assert (response.decisao, response.motivo) == ("suppressed", "sem_pergunta")
    for call in (history, handoff, generator, pause):
        call.assert_not_called()
    assert db.query(AlertaInterno).count() == 0
    states = db.query(WhatsAppBotConversaEstado).all()
    assert len(states) == int(paused)
    if paused:
        assert states[0].pausado_ate.replace(tzinfo=timezone.utc) == until


def test_visao_vazia_de_reacoes_encerra_job_legado_sem_erro(db):
    job = cases.WhatsAppBotProcessJobTest()._make_job(db)
    with patch.object(worker, "is_whatsapp_bot_enabled", return_value=True), \
            patch.object(worker, "resolve_conversation_mode", return_value="auto"), \
            patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)), \
            patch.object(worker, "_fetch_conversation_by_phone", return_value={"id": job.conversation_id}), \
            patch.object(worker, "_fetch_historico") as history:
        assert worker._process_job(db, job) == "done"
        db.flush()
    history.assert_not_called()
    assert db.query(WhatsAppBotResposta).one().motivo == "conversa_atualizada"
    assert db.query(WhatsAppBotConversaEstado).count() == db.query(AlertaInterno).count() == 0


def test_reconciliacao_legada_nao_enfileira_reacao(db):
    with patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)), \
            patch.object(worker, "_fetch_recently_active_conversations", return_value=[
                {"id": "49", "wa_phone_number": "test"}]), \
            patch.object(worker, "_fetch_last_message", return_value={
                "wa_message_id": "reaction", "type": "reaction", "from_me": False,
                "created_at": datetime.now(timezone.utc).isoformat()}):
        assert worker.run_reconciliation_sweep(db) == {"checked": 1, "enqueued": 0}
    assert db.query(WhatsAppBotJob).count() == 0


@pytest.mark.parametrize("minutes,expected", [(1, 1), (3 * 24 * 60, 0)])
def test_reconciliacao_usa_idade_da_pergunta_nao_da_reacao(db, minutes, expected):
    now = datetime.now(timezone.utc)
    with patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)), \
            patch.object(worker, "_fetch_recently_active_conversations", return_value=[
                {"id": "49", "wa_phone_number": "test", "last_inbound_at": now.isoformat()}]), \
            patch.object(worker, "_fetch_last_message", return_value={
                "wa_message_id": "question", "type": "text", "from_me": False,
                "created_at": (now-timedelta(minutes=minutes)).isoformat()}):
        assert worker.run_reconciliation_sweep(db) == {"checked": 1, "enqueued": expected}
    assert db.query(WhatsAppBotJob).count() == expected


def test_node_legado_adia_pergunta_sem_consumir_tentativas(db):
    job = cases.WhatsAppBotProcessJobTest()._make_job(db)
    with patch.object(worker, "is_whatsapp_bot_enabled", return_value=True), \
            patch.object(worker, "resolve_conversation_mode", return_value="auto"), \
            patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)), \
            patch.object(worker, "_fetch_conversation_by_phone", return_value={"id": job.conversation_id}), \
            patch.object(worker, "_last_message_from_conversation", return_value={
                "wa_message_id": "later-reaction", "type": "reaction", "from_me": False}), \
            patch.object(worker, "_fetch_historico") as history:
        for _ in range(5):
            assert worker._process_job(db, job) == "deferred"
            db.flush()
            assert job.status == "pending" and job.attempts == 0
            assert job.scheduled_for > datetime.now(timezone.utc)
    history.assert_not_called()
    assert db.query(WhatsAppBotResposta).count() == 0
    assert db.query(WhatsAppBotConversaEstado).count() == db.query(AlertaInterno).count() == 0


def test_ciclos_do_worker_preservam_pergunta_durante_atualizacao_do_node(db):
    job = cases.WhatsAppBotProcessJobTest()._make_job(db)
    job.status = "pending"
    db.commit()
    job_id = job.id
    now = datetime.now(timezone.utc)
    factory = sessionmaker(bind=db.get_bind())
    with patch.object(worker, "SessionLocal", factory), \
            patch.object(worker, "_distributed_lock_enabled", return_value=False), \
            patch.object(worker, "is_whatsapp_bot_enabled", return_value=True), \
            patch.object(worker, "resolve_conversation_mode", return_value="auto"), \
            patch.object(worker, "_bot_internal_client_config", return_value=("local", {}, 1)), \
            patch.object(worker, "_fetch_conversation_by_phone", return_value={"id": job.conversation_id}), \
            patch.object(worker, "_last_message_from_conversation", return_value={
                "wa_message_id": "later-reaction", "type": "reaction", "from_me": False}):
        for cycle in range(5):
            tick = now + timedelta(minutes=cycle)
            with patch.object(worker, "_utc_now", return_value=tick):
                assert worker.run_whatsapp_bot_worker_due_once(limit=1) == {
                    "processed": 1, "done": 0, "errors": 0}
            db.expire_all()
            current = db.get(WhatsAppBotJob, job_id)
            assert current.status == "pending" and current.attempts == 0
            assert current.scheduled_for.replace(tzinfo=timezone.utc) > tick
    assert db.query(WhatsAppBotResposta).count() == 0
    assert db.query(WhatsAppBotConversaEstado).count() == db.query(AlertaInterno).count() == 0
