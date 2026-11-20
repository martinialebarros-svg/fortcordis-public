import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "configuration-projections-test-secret-key-1234567890")

from app.models.configuracao import Configuracao
from app.models.whatsapp_bot import WhatsAppBotConversaEstado
from app.services import whatsapp_bot_gates as gates
from app.services import whatsapp_reminder_scheduler_service as scheduler


class WhatsAppConfigurationProjectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Configuracao.__table__.create(self.engine)
        WhatsAppBotConversaEstado.__table__.create(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        self.statements = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select ") and " from configuracoes " in normalized:
                self.statements.append(normalized)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        self.addCleanup(self.engine.dispose)

    def _seed(self, **values) -> None:
        with self.factory() as db:
            db.add(Configuracao(
                logomarca_dados=b"synthetic-logo" * 1024,
                assinatura_dados=b"synthetic-signature" * 1024,
                **values,
            ))
            db.commit()

    def _update(self, **values) -> None:
        with self.factory() as db:
            db.execute(update(Configuracao).values(**values))
            db.commit()

    def test_recurring_reads_emit_only_the_required_config_column(self) -> None:
        self._seed(
            whatsapp_bot_atendimento_habilitado=True,
            whatsapp_lembrete_automatico_habilitado=True,
            whatsapp_bot_modo="auto",
            whatsapp_bot_participacao="piloto",
        )
        with patch.object(gates, "SessionLocal", self.factory), \
             patch.object(scheduler, "SessionLocal", self.factory), \
             patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
            self.assertTrue(gates.is_whatsapp_bot_enabled())
            self.assertTrue(scheduler.is_reminder_scheduler_enabled_in_db())
            with self.factory() as db:
                self.assertEqual(gates.resolve_conversation_mode(db, "synthetic"), "auto")
                self.assertEqual(gates.resolve_participacao(db), "piloto")

        expected_columns = [
            "whatsapp_bot_atendimento_habilitado",
            "whatsapp_lembrete_automatico_habilitado",
            "whatsapp_bot_modo",
            "whatsapp_bot_participacao",
        ]
        self.assertEqual(len(self.statements), len(expected_columns))
        for statement, column in zip(self.statements, expected_columns):
            with self.subTest(column=column):
                self.assertRegex(
                    statement.split(" from ", 1)[0],
                    rf"^select configuracoes\.{column}(?: as \w+)?$",
                )
                self.assertNotIn("logomarca_dados", statement)
                self.assertNotIn("assinatura_dados", statement)
                self.assertIn(" limit ", statement)

    def test_missing_configuration_keeps_existing_defaults(self) -> None:
        with patch.object(gates, "SessionLocal", self.factory), \
             patch.object(scheduler, "SessionLocal", self.factory), \
             patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
            self.assertFalse(gates.is_whatsapp_bot_enabled())
            self.assertFalse(scheduler.is_reminder_scheduler_enabled_in_db())
            with self.factory() as db:
                self.assertEqual(gates.resolve_conversation_mode(db, "synthetic"), "suggest")
                self.assertEqual(gates.resolve_participacao(db), "todos")

    def test_disabled_environment_does_not_open_a_config_session(self) -> None:
        with patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", False), \
             patch.object(gates, "SessionLocal") as session:
            self.assertFalse(gates.is_whatsapp_bot_enabled())
        session.assert_not_called()
        self.assertEqual(self.statements, [])

    def test_flags_observe_committed_disable_on_the_next_read(self) -> None:
        self._seed(
            whatsapp_bot_atendimento_habilitado=True,
            whatsapp_lembrete_automatico_habilitado=True,
        )
        with patch.object(gates, "SessionLocal", self.factory), \
             patch.object(scheduler, "SessionLocal", self.factory), \
             patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True):
            self.assertTrue(gates.is_whatsapp_bot_enabled())
            self.assertTrue(scheduler.is_reminder_scheduler_enabled_in_db())
            self._update(
                whatsapp_bot_atendimento_habilitado=False,
                whatsapp_lembrete_automatico_habilitado=False,
            )
            self.assertFalse(gates.is_whatsapp_bot_enabled())
            self.assertFalse(scheduler.is_reminder_scheduler_enabled_in_db())

    def test_mode_and_participation_read_committed_changes_with_same_session(self) -> None:
        self._seed(whatsapp_bot_modo="auto", whatsapp_bot_participacao="todos")
        with self.factory() as db:
            retained_config = db.query(Configuracao).first()
            self.assertEqual(retained_config.whatsapp_bot_modo, "auto")
            self.assertEqual(gates.resolve_conversation_mode(db, "synthetic"), "auto")
            self.assertEqual(gates.resolve_participacao(db), "todos")
            self._update(whatsapp_bot_modo="off", whatsapp_bot_participacao="piloto")
            self.assertEqual(gates.resolve_conversation_mode(db, "synthetic"), "off")
            self.assertEqual(gates.resolve_participacao(db), "piloto")

    def test_null_empty_invalid_and_normalized_mode_defaults(self) -> None:
        self._seed()
        with self.factory() as db:
            for value, expected in [
                (None, "suggest"), ("", "suggest"), ("invalid", "suggest"),
                (" AUTO ", "auto"), ("off", "off"),
            ]:
                with self.subTest(mode=value):
                    self._update(whatsapp_bot_modo=value)
                    self.assertEqual(gates.resolve_conversation_mode(db, "synthetic"), expected)
            for value, expected in [
                (None, "todos"), ("", "todos"), ("invalid", "todos"),
                (" PILOTO ", "piloto"), ("todos", "todos"),
            ]:
                with self.subTest(participation=value):
                    self._update(whatsapp_bot_participacao=value)
                    self.assertEqual(gates.resolve_participacao(db), expected)

    def test_boolean_read_errors_still_fail_closed_and_close_sessions(self) -> None:
        for module, reader in [
            (gates, gates.is_whatsapp_bot_enabled),
            (scheduler, scheduler.is_reminder_scheduler_enabled_in_db),
        ]:
            with self.subTest(reader=reader.__name__), \
                 patch.object(gates.settings, "WHATSAPP_BOT_ENABLED", True), \
                 patch.object(module, "SessionLocal") as session, \
                 patch.object(module.logger, "exception"):
                session.return_value.query.side_effect = RuntimeError("synthetic unavailable database")
                self.assertFalse(reader())
                session.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
