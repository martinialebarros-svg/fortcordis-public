import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-bot-handoff-test-secret-key-1234567890")

from app.models.alerta_interno import AlertaInterno
from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotConversaEstado
from app.services import whatsapp_bot_handoff_service as handoff_service

LOCAL_TZ = ZoneInfo("America/Fortaleza")


def _next_weekday(base: datetime, target_isoweekday: int) -> datetime:
    delta = (target_isoweekday - base.isoweekday()) % 7
    return base + timedelta(days=delta)


class WhatsAppBotHandoffServiceTest(unittest.TestCase):
    def _build_session_factory(self, tmpdir: str):
        db_path = Path(tmpdir) / "whatsapp-bot-handoff-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Configuracao.__table__.create(engine, checkfirst=True)
        WhatsAppBotConversaEstado.__table__.create(engine, checkfirst=True)
        AlertaInterno.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine

    def test_is_within_operating_window_dentro_do_horario_padrao_de_segunda(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    monday_10am = _next_weekday(datetime.now(LOCAL_TZ), 1).replace(
                        hour=10, minute=0, second=0, microsecond=0
                    )
                    self.assertTrue(handoff_service.is_within_operating_window(db, now=monday_10am))
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_is_within_operating_window_fora_do_horario_padrao_de_segunda_a_noite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    monday_8pm = _next_weekday(datetime.now(LOCAL_TZ), 1).replace(
                        hour=20, minute=0, second=0, microsecond=0
                    )
                    self.assertFalse(handoff_service.is_within_operating_window(db, now=monday_8pm))
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_is_within_operating_window_domingo_fechado_por_padrao(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    sunday_11am = _next_weekday(datetime.now(LOCAL_TZ), 7).replace(
                        hour=11, minute=0, second=0, microsecond=0
                    )
                    self.assertFalse(handoff_service.is_within_operating_window(db, now=sunday_11am))
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_build_handoff_message_dentro_do_expediente_informa_transferencia(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    monday_10am = _next_weekday(datetime.now(LOCAL_TZ), 1).replace(
                        hour=10, minute=0, second=0, microsecond=0
                    )
                    mensagem = handoff_service.build_handoff_message(db, now=monday_10am)
                    self.assertIn("passada para a nossa equipe", mensagem)
                    self.assertNotIn("proximo", mensagem.lower())
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_build_handoff_message_fora_do_expediente_informa_proximo_horario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    sunday_11am = _next_weekday(datetime.now(LOCAL_TZ), 7).replace(
                        hour=11, minute=0, second=0, microsecond=0
                    )
                    mensagem = handoff_service.build_handoff_message(db, now=sunday_11am)
                    self.assertIn("amanha as 08:00", mensagem)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_build_handoff_message_tarde_de_sabado_aponta_segunda(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    db.add(Configuracao())
                    db.commit()
                    saturday_6pm = _next_weekday(datetime.now(LOCAL_TZ), 6).replace(
                        hour=18, minute=0, second=0, microsecond=0
                    )
                    mensagem = handoff_service.build_handoff_message(db, now=saturday_6pm)
                    self.assertIn("segunda-feira as 08:00", mensagem)
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_trigger_active_handoff_cria_alerta_marca_estado_e_chama_patch_e_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    with patch.object(handoff_service.settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"):
                        with patch.object(handoff_service.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "segredo"):
                            with patch.object(handoff_service, "send_whatsapp_message_push_notification") as push_mock:
                                patch_response = Mock()
                                patch_response.raise_for_status = Mock()
                                with patch.object(handoff_service.httpx, "patch", return_value=patch_response) as patch_mock:
                                    handoff_service.trigger_active_handoff(
                                        db,
                                        wa_identity="558588018899",
                                        conversation_id="conv-1",
                                        motivo="emergencia",
                                        nivel="critico",
                                        titulo="Possivel emergencia recebida no WhatsApp",
                                        mensagem_alerta="Verifique com urgencia.",
                                    )
                    db.commit()

                    patch_mock.assert_called_once()
                    called_url = patch_mock.call_args.args[0]
                    self.assertIn("/conversations/conv-1/status", called_url)
                    self.assertEqual(patch_mock.call_args.kwargs["json"], {"status": "pending"})
                    push_mock.assert_called_once()

                    alerta = db.query(AlertaInterno).first()
                    self.assertEqual(alerta.nivel, "critico")
                    self.assertEqual(alerta.tipo, "whatsapp_bot_emergencia")

                    estado = (
                        db.query(WhatsAppBotConversaEstado)
                        .filter(WhatsAppBotConversaEstado.wa_identity == "558588018899")
                        .first()
                    )
                    self.assertEqual(estado.handoff_motivo, "emergencia")
                finally:
                    db.close()
            finally:
                engine.dispose()

    def test_trigger_active_handoff_sem_config_do_node_nao_quebra(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            SessionFactory, engine = self._build_session_factory(tmpdir)
            try:
                db = SessionFactory()
                try:
                    with patch.object(handoff_service.settings, "WHATSAPP_AGENDA_SERVICE_URL", ""):
                        with patch.object(handoff_service.settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", ""):
                            with patch.object(handoff_service, "send_whatsapp_message_push_notification"):
                                handoff_service.trigger_active_handoff(
                                    db,
                                    wa_identity="558588018899",
                                    conversation_id="conv-1",
                                    motivo="pedido_humano",
                                    nivel="aviso",
                                    titulo="Cliente pediu atendimento humano",
                                    mensagem_alerta="Pedido de humano.",
                                )
                    db.commit()
                    self.assertIsNotNone(db.query(AlertaInterno).first())
                finally:
                    db.close()
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
