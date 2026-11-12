import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests import test_whatsapp_conversation_context as existing
from app.api.v1.endpoints import whatsapp_contexto as api
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.auditoria_evento import AuditoriaEvento
from app.models.whatsapp_bot import WhatsAppBotConversaEstado, WhatsAppBotContextoSelecao, WhatsAppBotResposta
from app.services.whatsapp_contexto_selecao_service import (
    canonical_context_identity,
    lock_contexto,
    resposta_contexto_vigente,
)


class WhatsAppContextoSelecaoTest(existing.WhatsappConversationContextTest):
    def setUp(self):
        super().setUp()
        for table in (AuditoriaEvento.__table__, WhatsAppBotResposta.__table__, WhatsAppBotConversaEstado.__table__):
            table.create(self._engine)
        self.user = SimpleNamespace(id=42, nome="Recepcao teste", email="teste@example.invalid")

    def _mixed(self, db):
        clinic, tutor, patient, appointment, order = self._seed_context(db)
        clinic.telefone = tutor.whatsapp
        db.commit()
        return clinic, tutor, patient, appointment, order

    def _select(self, db, phone, match_type, cadastro_id, version=0):
        return api.atualizar_contexto_selecao(
            phone,
            api.WhatsAppContextoSelecaoRequest(
                match_type=match_type, cadastro_id=cadastro_id, versao_esperada=version,
            ),
            db=db,
            current_user=self.user,
        )

    def test_candidates_are_direct_only_not_related_people(self):
        with self._session_factory() as db:
            clinic, tutor, patient, appointment, order = self._seed_context(db)
            result = api.resolve_whatsapp_context(db, tutor.whatsapp)
            self.assertEqual(result["candidatos"]["clinicas"], [])
            self.assertEqual([row["id"] for row in result["candidatos"]["tutores"]], [tutor.id])
            self.assertEqual(result["clinicas"][0]["id"], clinic.id)
            with self.assertRaises(HTTPException) as exc:
                self._select(db, tutor.whatsapp, "clinica", clinic.id)
            self.assertEqual(exc.exception.status_code, 422)

    def test_mixed_number_can_select_either_persona_without_changing_phone(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            phone = tutor.whatsapp
            initial = api.resolve_whatsapp_context(db, phone)
            self.assertEqual(initial["resolution"], "ambiguous")
            clinic_result = self._select(db, phone, "clinica", clinic.id)
            self.assertEqual((clinic_result["resolution"], clinic_result["match_type"]), ("matched", "clinica"))
            tutor_result = self._select(db, phone, "tutor", tutor.id, 1)
            self.assertEqual((tutor_result["resolution"], tutor_result["match_type"]), ("matched", "tutor"))
            self.assertNotEqual(clinic_result["contexto_chave"], tutor_result["contexto_chave"])
            db.refresh(clinic)
            db.refresh(tutor)
            self.assertEqual(clinic.telefone, phone)
            self.assertEqual(tutor.whatsapp, phone)
            self.assertEqual(len(tutor_result["candidatos"]["clinicas"]), 1)
            self.assertEqual(len(tutor_result["candidatos"]["tutores"]), 1)

    def test_select_one_of_multiple_clinics_excludes_other_clinic_records(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._seed_context(db)
            duplicate = existing.Clinica(nome="Outra clinica", telefone=clinic.telefone, ativo=True)
            db.add(duplicate)
            db.commit()
            result = self._select(db, clinic.telefone, "clinica", duplicate.id)
            self.assertEqual([row["id"] for row in result["clinicas"]], [duplicate.id])
            self.assertEqual(result["agendamentos"], [])
            self.assertEqual(result["pets"], [])
            self.assertEqual(result["tutores"], [])

    def test_select_one_of_multiple_tutors_excludes_other_tutor_records(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._seed_context(db)
            duplicate = existing.Tutor(nome="Outro tutor", whatsapp=tutor.whatsapp, ativo=1)
            db.add(duplicate)
            db.commit()
            result = self._select(db, tutor.whatsapp, "tutor", duplicate.id)
            self.assertEqual([row["id"] for row in result["tutores"]], [duplicate.id])
            self.assertEqual(result["agendamentos"], [])
            self.assertEqual(result["pets"], [])

    def test_removed_phone_or_inactive_or_deleted_choice_never_falls_back(self):
        for change in ("telefone", "inativo", "removido"):
            with self.subTest(change=change), self._session_factory() as db:
                clinic, tutor, *_ = self._mixed(db)
                phone = tutor.whatsapp
                old = self._select(db, phone, "clinica", clinic.id)
                if change == "telefone":
                    clinic.telefone = "8532224455"
                elif change == "inativo":
                    clinic.ativo = False
                else:
                    db.delete(clinic)
                db.commit()
                result = api.resolve_whatsapp_context(db, phone)
                self.assertEqual(result["resolution"], "selection_invalid")
                self.assertFalse(result["selecao"]["valida"])
                for key in ("clinicas", "tutores", "pets", "agendamentos", "ordens_servico"):
                    self.assertEqual(result[key], [])
                self.assertNotEqual(result["contexto_chave"], old["contexto_chave"])
                # Independent scenario, retaining unrelated tables safely.
                db.query(WhatsAppBotContextoSelecao).delete()
                db.query(existing.OrdemServico).delete()
                db.query(existing.Agendamento).delete()
                db.query(existing.Paciente).delete()
                db.query(existing.Clinica).delete()
                db.query(existing.Tutor).delete()
                db.query(existing.Servico).delete()
                db.commit()

    def test_invalid_or_inactive_candidates_cannot_be_selected(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._seed_context(db)
            for match_type, entity in (("clinica", clinic), ("tutor", tutor)):
                phone = entity.telefone if match_type == "clinica" else entity.whatsapp
                entity.ativo = False
                db.commit()
                with self.assertRaises(HTTPException) as exc:
                    self._select(db, phone, match_type, entity.id)
                self.assertEqual(exc.exception.status_code, 422)
                db.rollback()
            self.assertEqual(db.query(WhatsAppBotContextoSelecao).count(), 0)
            self.assertEqual(db.query(AuditoriaEvento).count(), 0)

    def test_stale_version_cannot_overwrite_selection_or_reset(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            self._select(db, tutor.whatsapp, "clinica", clinic.id)
            for match_type, entity_id in (("tutor", tutor.id), (None, None)):
                with self.assertRaises(HTTPException) as exc:
                    self._select(db, tutor.whatsapp, match_type, entity_id, 0)
                self.assertEqual(exc.exception.status_code, 409)
            current = api.resolve_whatsapp_context(db, tutor.whatsapp)
            self.assertEqual(current["match_type"], "clinica")
            self.assertEqual(current["selecao"]["versao"], 1)
            self.assertEqual(db.query(AuditoriaEvento).count(), 1)

    def test_reset_preserves_version_and_restores_ambiguous_resolution(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            self._select(db, tutor.whatsapp, "clinica", clinic.id)
            result = self._select(db, tutor.whatsapp, None, None, 1)
            self.assertEqual(result["resolution"], "ambiguous")
            self.assertIsNone(result["selecao"]["match_type"])
            self.assertIsNone(result["selecao"]["cadastro_id"])
            self.assertEqual(result["selecao"]["versao"], 2)
            self.assertTrue(result["selecao"]["valida"])
            self.assertEqual(db.query(WhatsAppBotContextoSelecao).count(), 1)

    def test_ninth_digit_aliases_share_choice_version_and_fingerprint(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            selected = self._select(db, tutor.whatsapp, "clinica", clinic.id)
            alias = canonical_context_identity(tutor.whatsapp)
            resolved = api.resolve_whatsapp_context(db, alias)
            self.assertEqual(selected["contexto_chave"], resolved["contexto_chave"])
            self.assertEqual(resolved["selecao"]["versao"], 1)
            self.assertEqual(db.query(WhatsAppBotContextoSelecao).one().wa_identity, alias)
            changed = self._select(db, alias, "tutor", tutor.id, 1)
            self.assertEqual(changed["selecao"]["versao"], 2)

    def test_audit_is_atomic_and_contains_actor_and_before_after(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            self._select(db, tutor.whatsapp, "clinica", clinic.id)
            audit = db.query(AuditoriaEvento).one()
            self.assertEqual(audit.usuario_id, 42)
            details = json.loads(audit.detalhes_json)
            self.assertIsNone(details["anterior"])
            self.assertEqual(details["atual"], {"match_type": "clinica", "cadastro_id": clinic.id, "versao": 1})
            with patch.object(api, "registrar_auditoria", side_effect=RuntimeError("audit unavailable")):
                with self.assertRaises(RuntimeError):
                    self._select(db, tutor.whatsapp, "tutor", tutor.id, 1)
            self.assertEqual(api.resolve_whatsapp_context(db, tutor.whatsapp)["match_type"], "clinica")
            self.assertEqual(db.query(AuditoriaEvento).count(), 1)

    def test_selection_suppresses_drafts_but_preserves_pause_mode_and_sending(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            identity = canonical_context_identity(tutor.whatsapp)
            pause = datetime.now(timezone.utc) + timedelta(hours=2)
            db.add(WhatsAppBotConversaEstado(wa_identity=identity, modo="suggest", pausado_ate=pause))
            for idx, status in enumerate(("draft", "sending", "sent")):
                db.add(WhatsAppBotResposta(job_id=idx+1, wa_identity=identity, conversation_id="test", decisao=status))
            db.commit()
            self._select(db, identity, "clinica", clinic.id)
            replies = db.query(WhatsAppBotResposta).order_by(WhatsAppBotResposta.id).all()
            self.assertEqual([row.decisao for row in replies], ["suppressed", "sending", "sent"])
            self.assertEqual(replies[0].motivo, "contexto_alterado")
            state = db.query(WhatsAppBotConversaEstado).one()
            self.assertEqual(state.modo, "suggest")
            self.assertEqual(state.pausado_ate.replace(tzinfo=timezone.utc), pause)

    def test_draft_guard_rejects_old_missing_or_changed_selection_and_new_candidate(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            result = self._select(db, tutor.whatsapp, "clinica", clinic.id)
            draft = SimpleNamespace(wa_identity=tutor.whatsapp, contexto_chave=result["contexto_chave"])
            self.assertTrue(resposta_contexto_vigente(db, draft))
            self.assertFalse(resposta_contexto_vigente(db, SimpleNamespace(wa_identity=tutor.whatsapp, contexto_chave=None)))
            db.add(existing.Clinica(nome="Novo vinculo", telefone=tutor.whatsapp, ativo=True))
            db.commit()
            self.assertFalse(resposta_contexto_vigente(db, draft))
            current = api.resolve_whatsapp_context(db, tutor.whatsapp)
            draft.contexto_chave = current["contexto_chave"]
            self._select(db, tutor.whatsapp, "tutor", tutor.id, 1)
            self.assertFalse(resposta_contexto_vigente(db, draft))

    def test_cached_candidates_refresh_after_another_session_changes_phone(self):
        with self._session_factory() as cached:
            clinic, tutor, *_ = self._mixed(cached)
            phone = tutor.whatsapp
            for match_type, entity in (("clinica", clinic), ("tutor", tutor)):
                with self.subTest(match_type=match_type):
                    initial = api.resolve_whatsapp_context(cached, phone)
                    draft = SimpleNamespace(wa_identity=phone, contexto_chave=initial["contexto_chave"])
                    model = existing.Clinica if match_type == "clinica" else existing.Tutor
                    # Retain the ORM instance and transaction in session1. A
                    # query without populate_existing would use this old phone.
                    with self._session_factory() as writer:
                        changed = writer.get(model, entity.id)
                        if match_type == "clinica":
                            changed.telefone = "8532224455"
                        else:
                            changed.whatsapp = "8532224466"
                        writer.commit()
                    previous_phone = entity.telefone if match_type == "clinica" else entity.whatsapp
                    self.assertEqual(previous_phone, phone)
                    self.assertFalse(resposta_contexto_vigente(cached, draft))

    def test_sqlite_lock_serializes_selection_until_transport_transaction_finishes(self):
        with self._session_factory() as db:
            clinic, tutor, *_ = self._mixed(db)
            phone, clinic_id, tutor_id = tutor.whatsapp, clinic.id, tutor.id
        acquired = threading.Event()
        completed = threading.Event()
        failures = []
        def choose():
            try:
                with self._session_factory() as db:
                    acquired.set()
                    self._select(db, phone, "tutor", tutor_id, 0)
            except HTTPException as exc:
                failures.append(exc.status_code)
            finally:
                completed.set()
        with self._session_factory() as holder:
            lock_contexto(holder, phone)
            thread = threading.Thread(target=choose)
            thread.start()
            self.assertTrue(acquired.wait(1))
            try:
                self.assertFalse(completed.wait(.1), "second transaction bypassed context lock")
                self._select(holder, phone, "clinica", clinic_id, 0)
            finally:
                holder.rollback()
                thread.join(5)
            self.assertTrue(completed.is_set())
            self.assertEqual(failures, [409])

    def test_postgresql_lock_is_transaction_scoped_and_canonical(self):
        db = Mock()
        db.get_bind.return_value.dialect.name = "postgresql"
        lock_contexto(db, "85999990001")
        lock_contexto(db, "558599990001")
        first, second = db.execute.call_args_list
        self.assertIn("pg_advisory_xact_lock", str(first.args[0]))
        self.assertEqual(first.args[1], second.args[1])
        db.commit.assert_not_called()

    def test_http_route_enforces_auth_roles_and_payload(self):
        app = FastAPI()
        app.include_router(api.router, prefix="/api/v1/whatsapp-contexto")
        def session():
            with self._session_factory() as db:
                yield db
        app.dependency_overrides[get_db] = session
        with TestClient(app) as client:
            url = "/api/v1/whatsapp-contexto/558599990001/selecao"
            body = {"match_type": None, "cadastro_id": None, "versao_esperada": 0}
            self.assertEqual(client.patch(url, json=body).status_code, 401)
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tem_papel=lambda role: False)
            self.assertEqual(client.patch(url, json=body).status_code, 403)
            self.user.tem_papel = lambda role: role == "recepcao"
            app.dependency_overrides[get_current_user] = lambda: self.user
            self.assertEqual(client.patch(url, json={**body, "versao_esperada": -1}).status_code, 422)
            self.assertEqual(client.patch(url, json={**body, "match_type": "clinica"}).status_code, 422)
            response = client.patch(url, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["selecao"]["versao"], 1)

    def test_payload_rejects_coerced_ids_and_invalid_type(self):
        for body in (
            {"match_type": "admin", "cadastro_id": 1, "versao_esperada": 0},
            {"match_type": "tutor", "cadastro_id": True, "versao_esperada": 0},
            {"match_type": "tutor", "cadastro_id": 1, "versao_esperada": "0"},
        ):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                api.WhatsAppContextoSelecaoRequest(**body)
