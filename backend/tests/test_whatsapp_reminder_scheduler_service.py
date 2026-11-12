import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-reminder-scheduler-test-secret-key-1234567890")

from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.services import whatsapp_reminder_scheduler_service as scheduler


class WhatsAppReminderSchedulerServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-reminder-scheduler-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Agendamento.__table__.create(engine, checkfirst=True)
        Clinica.__table__.create(engine, checkfirst=True)
        Configuracao.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_fetch_next_due_agendamento_respeita_janela_status_e_tentativas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now = datetime.now(timezone.utc)
                db = SessionFactory()
                try:
                    elegivel = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=10),
                        whatsapp_reminder_attempts=0,
                    )
                    status_invalido = Agendamento(
                        status="Cancelado", inicio=now + timedelta(hours=10),
                        whatsapp_reminder_attempts=0,
                    )
                    cedo_demais = Agendamento(
                        status="Agendado", inicio=now + timedelta(minutes=10),
                        whatsapp_reminder_attempts=0,
                    )
                    tarde_demais = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=30),
                        whatsapp_reminder_attempts=0,
                    )
                    ja_enviado = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=10),
                        whatsapp_reminder_attempts=0, whatsapp_reminder_sent_at=now - timedelta(hours=1),
                    )
                    tentativas_esgotadas = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=10),
                        whatsapp_reminder_attempts=3,
                    )
                    db.add_all([
                        status_invalido, cedo_demais, tarde_demais,
                        ja_enviado, tentativas_esgotadas, elegivel,
                    ])
                    db.commit()

                    found = scheduler._fetch_next_due_agendamento(db, now=now)
                    self.assertIsNotNone(found)
                    self.assertEqual(found.id, elegivel.id)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_list_eligible_agendamentos_preview_nao_envia_nada_e_mascara_destino(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now = datetime.now(timezone.utc)
                db = SessionFactory()
                try:
                    clinica = Clinica(nome="Clinica Preview", whatsapps=["5585999998888"], telefone=None)
                    db.add(clinica)
                    db.commit()

                    elegivel = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=10),
                        clinica_id=clinica.id, whatsapp_reminder_attempts=0,
                    )
                    fora_da_janela = Agendamento(
                        status="Agendado", inicio=now + timedelta(hours=30),
                        clinica_id=clinica.id, whatsapp_reminder_attempts=0,
                    )
                    db.add_all([elegivel, fora_da_janela])
                    db.commit()

                    preview = scheduler.list_eligible_agendamentos_preview(db, now=now)

                    self.assertEqual(len(preview), 1)
                    item = preview[0]
                    self.assertEqual(item["agendamento_id"], elegivel.id)
                    self.assertEqual(item["recipient_nome"], "Clinica Preview")
                    self.assertTrue(item["has_valid_destination"])
                    self.assertEqual(item["destination_last4"], "8888")

                    verify = db.query(Agendamento).filter(Agendamento.id == elegivel.id).first()
                    self.assertIsNone(verify.whatsapp_reminder_sent_at)
                    self.assertEqual(verify.whatsapp_reminder_attempts, 0)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_list_clinicas_prontidao_whatsapp_lembrete_classifica_por_motivo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    pronta = Clinica(nome="Clinica Pronta", whatsapps=["5585999998888"], telefone=None, ativo=True)
                    sem_numero = Clinica(nome="Clinica Sem Numero", whatsapps=[], telefone=None, ativo=True)
                    numero_invalido = Clinica(nome="Clinica Numero Invalido", whatsapps=["123"], telefone=None, ativo=True)
                    inativa_sem_numero = Clinica(nome="Clinica Inativa", whatsapps=[], telefone=None, ativo=False)
                    db.add_all([pronta, sem_numero, numero_invalido, inativa_sem_numero])
                    db.commit()

                    resultado = scheduler.list_clinicas_prontidao_whatsapp_lembrete(db)

                    self.assertEqual(resultado["total_clinicas_ativas"], 3)
                    self.assertEqual(resultado["total_prontas"], 1)
                    self.assertEqual(resultado["total_com_problema"], 2)

                    motivos_por_clinica = {p["clinica_nome"]: p["motivo"] for p in resultado["problemas"]}
                    self.assertEqual(motivos_por_clinica["Clinica Sem Numero"], "sem_numero")
                    self.assertEqual(motivos_por_clinica["Clinica Numero Invalido"], "numero_invalido")
                    self.assertNotIn("Clinica Inativa", motivos_por_clinica)
                    self.assertNotIn("Clinica Pronta", motivos_por_clinica)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_list_clinicas_prontidao_whatsapp_lembrete_usa_telefone_como_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    clinica = Clinica(nome="Clinica Fallback", whatsapps=[""], telefone="5585999997777", ativo=True)
                    db.add(clinica)
                    db.commit()

                    resultado = scheduler.list_clinicas_prontidao_whatsapp_lembrete(db)

                    self.assertEqual(resultado["total_prontas"], 1)
                    self.assertEqual(resultado["total_com_problema"], 0)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_list_clinicas_prontidao_whatsapp_lembrete_conta_e_ordena_por_agendamentos_60_dias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now = datetime.now(timezone.utc)
                db = SessionFactory()
                try:
                    movimentada = Clinica(nome="Clinica Movimentada", whatsapps=["5585999998888"], telefone=None, ativo=True)
                    tranquila = Clinica(nome="Clinica Tranquila", whatsapps=["5585999997777"], telefone=None, ativo=True)
                    sem_movimento = Clinica(nome="Clinica Sem Movimento", whatsapps=["5585999996666"], telefone=None, ativo=True)
                    db.add_all([movimentada, tranquila, sem_movimento])
                    db.commit()

                    for _ in range(5):
                        db.add(Agendamento(
                            status="Realizado", inicio=now, clinica_id=movimentada.id,
                            created_at=now - timedelta(days=10),
                        ))
                    db.add(Agendamento(
                        status="Realizado", inicio=now, clinica_id=tranquila.id,
                        created_at=now - timedelta(days=10),
                    ))
                    # Fora da janela de 60 dias - nao deve contar.
                    db.add(Agendamento(
                        status="Realizado", inicio=now, clinica_id=sem_movimento.id,
                        created_at=now - timedelta(days=90),
                    ))
                    db.commit()

                    resultado = scheduler.list_clinicas_prontidao_whatsapp_lembrete(db, janela_dias=60)

                    contagens = {c["clinica_nome"]: c["agendamentos_60_dias"] for c in resultado["clinicas"]}
                    self.assertEqual(contagens["Clinica Movimentada"], 5)
                    self.assertEqual(contagens["Clinica Tranquila"], 1)
                    self.assertEqual(contagens["Clinica Sem Movimento"], 0)

                    nomes_em_ordem = [c["clinica_nome"] for c in resultado["clinicas"]]
                    self.assertEqual(nomes_em_ordem, ["Clinica Movimentada", "Clinica Tranquila", "Clinica Sem Movimento"])
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_is_reminder_scheduler_enabled_in_db_reflete_configuracoes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                with patch.object(scheduler, "SessionLocal", SessionFactory):
                    self.assertFalse(scheduler.is_reminder_scheduler_enabled_in_db())

                    db = SessionFactory()
                    try:
                        db.add(Configuracao(whatsapp_lembrete_automatico_habilitado=True))
                        db.commit()
                    finally:
                        db.close()

                    self.assertTrue(scheduler.is_reminder_scheduler_enabled_in_db())
            finally:
                engine.dispose()

    def test_scheduler_worker_main_so_processa_quando_habilitado_no_banco(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao(whatsapp_lembrete_automatico_habilitado=False))
                    db.commit()
                finally:
                    db.close()

                calls = []

                def _fake_stop_wait(_seconds):
                    calls.append(1)
                    return len(calls) >= 1  # para apos a 1a iteracao

                with patch.object(scheduler, "SessionLocal", SessionFactory):
                    with patch.object(scheduler, "run_whatsapp_reminder_scheduler_due_once") as due_once_mock:
                        with patch.object(scheduler._SCHEDULER_STOP_EVENT, "is_set", side_effect=[False, True]):
                            with patch.object(scheduler._SCHEDULER_STOP_EVENT, "wait", side_effect=_fake_stop_wait):
                                scheduler._scheduler_worker_main()

                due_once_mock.assert_not_called()
            finally:
                engine.dispose()

    def test_resolve_destination_usa_primeiro_whatsapp_da_clinica(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    clinica = Clinica(nome="Clinica Teste", whatsapps=["", "5585999990000"], telefone="5585333330000")
                    db.add(clinica)
                    db.commit()

                    agendamento = Agendamento(status="Agendado", inicio=datetime.now(timezone.utc), clinica_id=clinica.id)

                    destino = scheduler._resolve_destination(db, agendamento, "clinica")
                    self.assertEqual(destino, "5585999990000")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_resolve_destination_none_quando_clinica_sem_whatsapp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    clinica = Clinica(nome="Clinica Sem WhatsApp", whatsapps=[], telefone=None)
                    db.add(clinica)
                    db.commit()

                    agendamento = Agendamento(status="Agendado", inicio=datetime.now(timezone.utc), clinica_id=clinica.id)

                    destino = scheduler._resolve_destination(db, agendamento, "clinica")
                    self.assertIsNone(destino)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_process_agendamento_marca_erro_quando_clinica_sem_whatsapp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    clinica = Clinica(nome="Clinica Sem WhatsApp", whatsapps=[], telefone=None)
                    db.add(clinica)
                    db.commit()

                    agendamento = Agendamento(status="Agendado", inicio=datetime.now(timezone.utc), clinica_id=clinica.id)
                    db.add(agendamento)
                    db.commit()

                    result = scheduler._process_agendamento(db, agendamento)

                    self.assertEqual(result, "error")
                    self.assertIsNone(agendamento.whatsapp_reminder_sent_at)
                    self.assertEqual(agendamento.whatsapp_reminder_attempts, 1)
                    self.assertIn("WhatsApp", agendamento.whatsapp_reminder_last_error or "")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_run_due_once_processes_up_to_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                now = datetime.now(timezone.utc)
                db = SessionFactory()
                try:
                    for _ in range(3):
                        db.add(Agendamento(status="Agendado", inicio=now + timedelta(hours=5), whatsapp_reminder_attempts=0))
                    db.commit()
                finally:
                    db.close()

                def _mark_sent(_db, agendamento):
                    agendamento.whatsapp_reminder_sent_at = scheduler._utc_now()
                    return "sent"

                with patch.object(scheduler, "SessionLocal", SessionFactory):
                    with patch.object(scheduler, "_distributed_lock_enabled", return_value=False):
                        with patch.object(scheduler, "_process_agendamento", side_effect=_mark_sent):
                            payload = scheduler.run_whatsapp_reminder_scheduler_due_once(limit=2)

                self.assertEqual(payload["processed"], 2)
                self.assertEqual(payload["sent"], 2)
                self.assertEqual(payload["errors"], 0)

                verify = SessionFactory()
                try:
                    sent_count = verify.query(Agendamento).filter(Agendamento.whatsapp_reminder_sent_at.isnot(None)).count()
                    pending_count = verify.query(Agendamento).filter(Agendamento.whatsapp_reminder_sent_at.is_(None)).count()
                    self.assertEqual(sent_count, 2)
                    self.assertEqual(pending_count, 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()

    def test_run_due_once_skips_cycle_when_distributed_lock_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Agendamento(
                        status="Agendado",
                        inicio=datetime.now(timezone.utc) + timedelta(hours=5),
                        whatsapp_reminder_attempts=0,
                    ))
                    db.commit()
                finally:
                    db.close()

                with patch.object(scheduler, "SessionLocal", SessionFactory):
                    with patch.object(scheduler, "_distributed_lock_enabled", return_value=True):
                        with patch.object(scheduler, "_is_postgres", return_value=True):
                            with patch.object(scheduler, "_try_acquire_pg_lock", return_value=False) as acquire_mock:
                                payload = scheduler.run_whatsapp_reminder_scheduler_due_once(limit=50)

                self.assertEqual(payload, {"processed": 0, "sent": 0, "errors": 0})
                acquire_mock.assert_called_once()

                verify = SessionFactory()
                try:
                    pending_count = verify.query(Agendamento).filter(Agendamento.whatsapp_reminder_sent_at.is_(None)).count()
                    self.assertEqual(pending_count, 1)
                finally:
                    verify.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
