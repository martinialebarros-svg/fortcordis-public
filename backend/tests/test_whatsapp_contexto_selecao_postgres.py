"""Contratos PostgreSQL reais, apenas banco LOCAL de testes e schema descartavel."""
import os
import threading
import unittest
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from tests import test_whatsapp_conversation_context as context_fixture
from tests.test_whatsapp_contexto_selecao_migration import MIGRATION
from app.api.v1.endpoints import whatsapp_contexto as api
from app.models.auditoria_evento import AuditoriaEvento
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao, WhatsAppBotResposta
from app.services.whatsapp_contexto_selecao_service import lock_contexto, resposta_contexto_vigente


class WhatsAppContextoSelecaoPostgresTest(unittest.TestCase):
    def setUp(self):
        url = os.environ.get("WHATSAPP_BOT_TEST_DATABASE_URL")
        if not url:
            self.skipTest("Defina WHATSAPP_BOT_TEST_DATABASE_URL para banco PostgreSQL local descartavel")
        parsed = urlparse(url)
        if parsed.hostname != "127.0.0.1" or "test" not in parsed.path:
            raise AssertionError("O contrato so permite PostgreSQL LOCAL de testes")
        self.schema = "wa_context_test_" + uuid.uuid4().hex
        self.admin = create_engine(url)
        with self.admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(url, connect_args={"options": f"-csearch_path={self.schema}"})
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        self.user = SimpleNamespace(id=42, nome="Recepcao teste", email="test@example.invalid")

    def tearDown(self):
        self.engine.dispose()
        try:
            with self.admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        finally:
            self.admin.dispose()

    def _create_context_tables(self):
        for model in (
            context_fixture.Tutor, context_fixture.Paciente, context_fixture.Clinica,
            context_fixture.Servico, context_fixture.Agendamento, context_fixture.OrdemServico,
            WhatsAppBotResposta, AuditoriaEvento,
        ):
            model.__table__.create(self.engine)
        with self.engine.begin() as conn:
            MIGRATION.upgrade(conn, "postgresql")

    def _select(self, db, phone, match_type, cadastro_id, version=0):
        return api.atualizar_contexto_selecao(
            phone,
            api.WhatsAppContextoSelecaoRequest(match_type=match_type, cadastro_id=cadastro_id, versao_esperada=version),
            db=db, current_user=self.user,
        )

    def test_postgres_migration_preserves_legacy_and_enforces_constraints(self):
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE whatsapp_bot_respostas (id INTEGER PRIMARY KEY, texto_gerado TEXT)"))
            conn.execute(text("INSERT INTO whatsapp_bot_respostas VALUES (1, 'rascunho legado')"))
            MIGRATION.upgrade(conn, "postgresql")
            MIGRATION.upgrade(conn, "postgresql")
            self.assertEqual(conn.execute(text("SELECT texto_gerado, contexto_chave FROM whatsapp_bot_respostas")).one(), ("rascunho legado", None))
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM whatsapp_bot_contexto_selecao")).scalar(), 0)
            columns = {column["name"] for column in inspect(conn).get_columns("whatsapp_bot_contexto_selecao")}
            self.assertIn("versao", columns)
            timestamp_column = next(column for column in inspect(conn).get_columns("whatsapp_bot_contexto_selecao") if column["name"] == "updated_at")
            self.assertTrue(timestamp_column["type"].timezone)
            # A session fora de UTC mantem o instante; o retorno e aware.
            conn.execute(text("SET TIME ZONE 'America/Fortaleza'"))
            conn.execute(text("INSERT INTO whatsapp_bot_contexto_selecao (wa_identity) VALUES ('558599990009')"))
            value, elapsed = conn.execute(text(
                "SELECT updated_at, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at)) "
                "FROM whatsapp_bot_contexto_selecao WHERE wa_identity='558599990009'"
            )).one()
            self.assertIsNotNone(value.tzinfo)
            self.assertEqual(elapsed, 0)
        for invalid in ("NULL, 1, 1", "'clinica', NULL, 1", "'tutor', 1, 0"):
            with self.subTest(invalid=invalid), self.assertRaises(IntegrityError), self.engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO whatsapp_bot_contexto_selecao (wa_identity, match_type, cadastro_id, versao) "
                    f"VALUES ('558599990001', {invalid})"
                ))

    def test_postgres_lock_serializes_same_identity_alias_and_cas(self):
        self._create_context_tables()
        with self.factory() as db:
            clinic = context_fixture.Clinica(nome="Clinica teste", telefone="85999990001", ativo=True)
            tutor = context_fixture.Tutor(nome="Tutor teste", whatsapp="85999990001", ativo=1)
            db.add_all([clinic, tutor])
            db.commit()
            clinic_id, tutor_id = clinic.id, tutor.id
        entering, completed = threading.Event(), threading.Event()
        outcomes = []
        def choose_concurrently():
            try:
                with self.factory() as db:
                    entering.set()
                    self._select(db, "558599990001", "tutor", tutor_id)
                    outcomes.append("unexpected_success")
            except HTTPException as exc:
                outcomes.append(exc.status_code)
            except Exception as exc:
                outcomes.append(type(exc).__name__)
            finally:
                completed.set()
        with self.factory() as holder:
            lock_contexto(holder, "85999990001")
            thread = threading.Thread(target=choose_concurrently)
            thread.start()
            self.assertTrue(entering.wait(1))
            try:
                self.assertFalse(completed.wait(.15), "second session bypassed transaction lock")
                selected = self._select(holder, "85999990001", "clinica", clinic_id)
                self.assertEqual(selected["selecao"]["versao"], 1)
            finally:
                holder.rollback()
                thread.join(5)
            self.assertTrue(completed.is_set())
            self.assertEqual(outcomes, [409])
        with self.factory() as check:
            self.assertEqual(check.query(WhatsAppBotContextoSelecao).count(), 1)
            self.assertEqual(check.query(AuditoriaEvento).count(), 1)
            reset = self._select(check, "558599990001", None, None, 1)
            self.assertEqual(reset["selecao"]["versao"], 2)
            self.assertEqual(reset["resolution"], "ambiguous")

    def test_postgres_refreshes_cached_candidate_after_concurrent_phone_change(self):
        self._create_context_tables()
        with self.factory() as cached:
            clinic = context_fixture.Clinica(nome="Clinica teste", telefone="85999990001", ativo=True)
            tutor = context_fixture.Tutor(nome="Tutor teste", whatsapp="85999990001", ativo=1)
            cached.add_all([clinic, tutor])
            cached.commit()
            phone = "85999990001"
            for match_type, entity in (("clinica", clinic), ("tutor", tutor)):
                with self.subTest(match_type=match_type):
                    initial = api.resolve_whatsapp_context(cached, phone)
                    draft = SimpleNamespace(wa_identity=phone, contexto_chave=initial["contexto_chave"])
                    model = context_fixture.Clinica if match_type == "clinica" else context_fixture.Tutor
                    with self.factory() as writer:
                        changed = writer.get(model, entity.id)
                        if match_type == "clinica":
                            changed.telefone = "8532224455"
                        else:
                            changed.whatsapp = "8532224466"
                        writer.commit()
                    self.assertEqual(entity.telefone if match_type == "clinica" else entity.whatsapp, phone)
                    self.assertFalse(resposta_contexto_vigente(cached, draft))
