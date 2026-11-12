"""Lembrete com serviço: fonte da agenda, modelo distinto e ativação explícita."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "whatsapp-service-reminder-tests-1234567890")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints import whatsapp_agenda
from app.api.v1.endpoints.whatsapp_agenda import AgendaUtilityTemplateSendRequest
from app.core.config import Settings, settings
from app.models.agendamento import Agendamento
from app.models.alerta_interno import AlertaInterno
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.services import whatsapp_reminder_scheduler_service as scheduler
from app.services.whatsapp_agenda_service import build_agenda_utility_template, process_button_response, send_agenda_utility_template
from app.services.whatsapp_template_delivery_service import WhatsAppTemplatePendingApproval, send_approved_utility_template


class WhatsAppReminderServiceTemplateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        for model in (Agendamento, Clinica, Paciente, Tutor, Servico, AlertaInterno, WhatsappAgendaResposta):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.clinica = Clinica(nome="Clínica teste", whatsapps=["5585987654321"], ativo=True)
        self.tutor = Tutor(nome="Tutor teste", ativo=1)
        self.servico = Servico(
            nome="Consulta + Eco + Eletro", ativo=True,
            descricao="Descrição interna não deve compor o lembrete",
        )
        self.db.add_all([self.clinica, self.tutor, self.servico])
        self.db.flush()
        self.paciente = Paciente(nome="Paciente teste", tutor_id=self.tutor.id, ativo=1)
        self.db.add(self.paciente)
        self.db.flush()
        now = datetime.now(timezone.utc)
        self.agendamento = Agendamento(
            clinica_id=self.clinica.id, tutor_id=self.tutor.id, paciente_id=self.paciente.id,
            servico_id=self.servico.id, servico="Ecocardiograma", status="Agendado",
            inicio=now + timedelta(hours=5), fim=now + timedelta(hours=6),
            observacoes="Observação interna não deve compor o lembrete",
        )
        self.db.add(self.agendamento)
        self.db.commit()
        disabled = patch.object(settings, "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED", False)
        disabled.start()
        self.addCleanup(disabled.stop)

    def build(self, key="appointmentReminderService"):
        return build_agenda_utility_template(
            self.db, agendamento=self.agendamento, destination="5585987654321",
            recipient_type="clinica", template_key=key,
        )

    def test_setting_defaults_to_disabled_without_reading_an_env_file(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Settings(_env_file=None, DATABASE_URL="sqlite://", SECRET_KEY="synthetic-test-secret")
        self.assertFalse(config.WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED)

    def test_explicit_variant_uses_complete_catalog_service_over_stale_snapshot(self):
        before = {column.name: getattr(self.agendamento, column.name) for column in Agendamento.__table__.columns}
        template = self.build()
        self.assertEqual(template.template_key, "appointmentReminderService")
        self.assertEqual(len(template.parameters), 5)
        self.assertEqual(template.parameters[:2], ("Clínica teste", "Paciente teste"))
        self.assertEqual(template.parameters[4], "Consulta + Eco + Eletro")
        self.assertNotIn(self.servico.descricao, template.parameters)
        self.assertNotIn(self.agendamento.observacoes, template.parameters)
        self.assertEqual({column.name: getattr(self.agendamento, column.name) for column in Agendamento.__table__.columns}, before)
        self.assertFalse(self.db.dirty)

    def test_legacy_default_stays_at_four_parameters_even_without_a_service(self):
        self.agendamento.servico_id = None
        self.agendamento.servico = None
        self.db.commit()
        template = self.build("appointmentReminder")
        self.assertEqual(template.template_key, "appointmentReminder")
        self.assertEqual(len(template.parameters), 4)
        self.assertEqual(template.parameters[1], "Paciente teste")

    def test_legacy_service_literal_is_used_only_when_no_catalog_link_resolves(self):
        for service_id in (None, 999):
            with self.subTest(servico_id=service_id):
                self.agendamento.servico_id = service_id
                self.agendamento.servico = "  Eco  +\n Eletro  "
                self.db.commit()
                self.assertEqual(self.build().parameters[4], "Eco + Eletro")

    def test_whitespace_is_normalized_without_truncating_full_catalog_label(self):
        self.servico.nome = "  Consulta  +\nEco\t+ Eletro  "
        self.db.commit()
        self.assertEqual(self.build().parameters[4], "Consulta + Eco + Eletro")
        full_name = "Serviço " + "A" * 247
        self.assertEqual(len(full_name), 255)
        self.servico.nome = full_name
        self.db.commit()
        self.assertEqual(self.build().parameters[4], full_name)

    def test_whitespace_catalog_name_falls_back_to_registered_service_literal(self):
        self.servico.nome = " \n\t "
        self.agendamento.servico = "  Eco  +\nEletro  "
        self.db.commit()
        self.assertEqual(self.build().parameters[4], "Eco + Eletro")

    def test_new_variant_rejects_reservation_before_related_queries_and_keeps_legacy(self):
        self.agendamento.status = "Reservado"
        self.db.commit()
        with patch.object(self.db, "query") as query:
            with self.assertRaises(HTTPException) as exc:
                self.build()
        self.assertEqual(exc.exception.status_code, 409)
        query.assert_not_called()
        legacy = self.build("appointmentReminder")
        self.assertEqual(legacy.template_key, "appointmentReminder")
        self.assertEqual(len(legacy.parameters), 4)

    def test_new_variant_requires_an_explicit_scheduled_or_confirmed_status(self):
        for status in (None, "", "Realizado", "Cancelado", "Expirado"):
            with self.subTest(status=status):
                self.agendamento.status = status
                self.db.commit()
                with self.assertRaises(HTTPException) as exc:
                    self.build()
                self.assertEqual(exc.exception.status_code, 409)
        self.agendamento.status = "Confirmado"
        self.db.commit()
        self.assertEqual(self.build().template_key, "appointmentReminderService")

    def test_service_scheduler_and_preview_skip_reservation_without_consuming_attempts(self):
        self.agendamento.status = "Reservado"
        self.db.commit()
        now = datetime.now(timezone.utc)
        with patch.object(settings, "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED", True), \
             patch.object(settings, "WHATSAPP_REMINDER_RECIPIENT_TYPE", "clinica"), \
             patch.object(scheduler, "SessionLocal", side_effect=lambda: Session(self.engine)), \
             patch.object(scheduler, "_distributed_lock_enabled", return_value=False), \
             patch.object(scheduler, "_process_agendamento") as process:
            self.assertIsNone(scheduler._fetch_next_due_agendamento(self.db, now=now))
            self.assertEqual(scheduler.list_eligible_agendamentos_preview(self.db, now=now), [])
            self.assertEqual(scheduler.run_whatsapp_reminder_scheduler_due_once(), {
                "processed": 0, "sent": 0, "errors": 0,
            })
        process.assert_not_called()
        self.db.refresh(self.agendamento)
        self.assertEqual(self.agendamento.status, "Reservado")
        self.assertEqual(self.agendamento.whatsapp_reminder_attempts, 0)
        self.assertIsNone(self.agendamento.whatsapp_reminder_sent_at)
        self.assertIsNone(self.agendamento.whatsapp_reminder_last_error)

    def test_legacy_scheduler_and_preview_keep_reservation_eligible(self):
        self.agendamento.status = "Reservado"
        self.db.commit()
        now = datetime.now(timezone.utc)
        with patch.object(settings, "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED", False), \
             patch.object(settings, "WHATSAPP_REMINDER_RECIPIENT_TYPE", "clinica"):
            self.assertEqual(scheduler._fetch_next_due_agendamento(self.db, now=now).id, self.agendamento.id)
            preview = scheduler.list_eligible_agendamentos_preview(self.db, now=now)
        self.assertEqual([item["agendamento_id"] for item in preview], [self.agendamento.id])
        self.assertEqual(preview[0]["status"], "Reservado")

    def test_missing_service_fails_before_delivery_instead_of_inventing_one(self):
        self.agendamento.servico_id = None
        for empty in (None, "", "  \n\t "):
            with self.subTest(service=empty):
                self.agendamento.servico = empty
                self.db.commit()
                with self.assertRaises(HTTPException) as exc:
                    self.build()
                self.assertEqual(exc.exception.status_code, 409)
                self.assertIn("serviço", exc.exception.detail)

    def test_overlong_legacy_name_is_rejected_instead_of_cutting_off_a_procedure(self):
        self.agendamento.servico_id = None
        self.agendamento.servico = "A" * 301
        self.db.commit()
        with self.assertRaises(HTTPException) as exc:
            self.build()
        self.assertEqual(exc.exception.status_code, 409)

    def test_flag_selects_scheduler_variant_while_manual_keys_stay_explicit(self):
        for enabled, key, parameter_count in ((False, "appointmentReminder", 4),
                                               (True, "appointmentReminderService", 5)):
            with self.subTest(enabled=enabled), \
                 patch.object(settings, "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED", enabled), \
                 patch.object(settings, "WHATSAPP_REMINDER_RECIPIENT_TYPE", "clinica"), \
                 patch("app.services.whatsapp_agenda_service.send_agenda_utility_template") as send:
                legacy_manual = self.build("appointmentReminder")
                self.assertEqual(legacy_manual.template_key, "appointmentReminder")
                self.assertEqual(len(legacy_manual.parameters), 4)
                manual = self.build(key)
                self.assertEqual(manual.template_key, key)
                self.assertEqual(len(manual.parameters), parameter_count)
                self.assertEqual(scheduler._process_agendamento(self.db, self.agendamento), "sent")
                sent = send.call_args.kwargs
                self.assertEqual(sent["template"], manual)
                self.assertEqual(sent["idempotency_key"], f"appointment-reminder-{self.agendamento.id}")

    def test_scheduler_missing_service_records_error_without_sending(self):
        self.agendamento.servico_id = None
        self.agendamento.servico = None
        self.db.commit()
        with patch.object(settings, "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED", True), \
             patch.object(settings, "WHATSAPP_REMINDER_RECIPIENT_TYPE", "clinica"), \
             patch("app.services.whatsapp_agenda_service.send_agenda_utility_template") as send:
            self.assertEqual(scheduler._process_agendamento(self.db, self.agendamento), "error")
        send.assert_not_called()
        self.assertIsNone(self.agendamento.whatsapp_reminder_sent_at)
        self.assertEqual(self.agendamento.whatsapp_reminder_attempts, 1)
        self.assertIn("serviço", self.agendamento.whatsapp_reminder_last_error)

    def test_service_change_request_requires_staff_review_and_preserves_appointment(self):
        before = {column.name: getattr(self.agendamento, column.name) for column in Agendamento.__table__.columns}
        result, duplicate = process_button_response(
            self.db, provider_message_id="wamid.service-change.synthetic",
            outbound_message_id="wamid.service-reminder.synthetic",
            agendamento_id=self.agendamento.id, action="solicitar_alteracao",
            from_phone="5585987654321",
        )
        self.db.refresh(self.agendamento)
        self.assertFalse(duplicate)
        self.assertEqual(result["result"], "alteracao_solicitada")
        self.assertEqual({column.name: getattr(self.agendamento, column.name) for column in Agendamento.__table__.columns}, before)
        alert = self.db.query(AlertaInterno).one()
        self.assertEqual(alert.entidade_id, self.agendamento.id)
        self.assertIn("servico e o horario", alert.mensagem)
        replay, duplicate = process_button_response(
            self.db, provider_message_id="wamid.service-change.synthetic",
            outbound_message_id="wamid.service-reminder.synthetic",
            agendamento_id=self.agendamento.id, action="solicitar_alteracao",
            from_phone="5585987654321",
        )
        self.assertTrue(duplicate)
        self.assertEqual(replay, result)
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)

    def test_api_contract_accepts_variant_and_delivery_preserves_five_parameters(self):
        request = AgendaUtilityTemplateSendRequest(
            destination="5585987654321", recipient_type="clinica",
            idempotency_key="reminder-service-test", template_key="appointmentReminderService",
        )
        self.assertEqual(request.template_key, "appointmentReminderService")
        template = self.build(request.template_key)
        response = SimpleNamespace(status_code=201, json=lambda: {"message_id": "wamid.service.synthetic"})
        with patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True), \
             patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node.synthetic"), \
             patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "synthetic-internal-token"), \
             patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response) as post:
            result = send_agenda_utility_template(
                agendamento_id=self.agendamento.id, template=template, idempotency_key=request.idempotency_key,
            )
        self.assertEqual(result["message_id"], "wamid.service.synthetic")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["template_key"], "appointmentReminderService")
        self.assertEqual(sent["parameters"], list(template.parameters))
        self.assertEqual(sent["subject_type"], "agendamento")
        self.assertEqual(sent["subject_id"], self.agendamento.id)

    def test_pending_approval_transport_uses_specific_exception_for_new_variant(self):
        response = SimpleNamespace(status_code=409, json=lambda: {
            "code": "WHATSAPP_TEMPLATE_APPROVAL_PENDING", "error": "Modelo ainda pendente.",
        })
        with patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True), \
             patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node.synthetic"), \
             patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "synthetic-internal-token"), \
             patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response):
            with self.assertRaises(WhatsAppTemplatePendingApproval):
                send_approved_utility_template(
                    template_key="appointmentReminderService", subject_type="agendamento",
                    subject_id=self.agendamento.id, destination="5585987654321",
                    parameters=self.build().parameters, idempotency_key="service-pending-transport",
                )

    def test_agenda_endpoint_preserves_pending_approval_409_without_success_audit(self):
        response = SimpleNamespace(status_code=409, json=lambda: {
            "code": "WHATSAPP_TEMPLATE_APPROVAL_PENDING", "error": "Modelo ainda pendente.",
        })
        payload = AgendaUtilityTemplateSendRequest(
            destination="5585987654321", recipient_type="clinica",
            idempotency_key="service-pending-endpoint", template_key="appointmentReminderService",
        )
        with patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True), \
             patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node.synthetic"), \
             patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "synthetic-internal-token"), \
             patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response) as post, \
             patch.object(whatsapp_agenda, "registrar_auditoria") as audit:
            with self.assertRaises(HTTPException) as exc:
                whatsapp_agenda.send_agenda_utility(
                    self.agendamento.id, payload, request=SimpleNamespace(), db=self.db,
                    current_user=SimpleNamespace(id=7, nome="Equipe teste"),
                )
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(exc.exception.detail, "O lembrete com serviço aguarda aprovação da Meta.")
        post.assert_called_once()
        audit.assert_not_called()
        self.assertIsNone(self.agendamento.whatsapp_reminder_sent_at)

    def test_other_node_errors_and_legacy_models_keep_generic_endpoint_failure(self):
        cases = (("appointmentReminderService", 409, "OUTRO_CONFLITO"),
                 ("appointmentReminderService", 503, "WHATSAPP_TEMPLATE_APPROVAL_PENDING"),
                 ("appointmentReminder", 409, "WHATSAPP_TEMPLATE_APPROVAL_PENDING"))
        for key, status, code in cases:
            with self.subTest(key=key, status=status, code=code):
                response = SimpleNamespace(status_code=status, json=lambda: {"code": code, "error": "Falha legada."})
                payload = AgendaUtilityTemplateSendRequest(
                    destination="5585987654321", recipient_type="clinica",
                    idempotency_key="service-generic-endpoint", template_key=key,
                )
                with patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True), \
                     patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://node.synthetic"), \
                     patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "synthetic-internal-token"), \
                     patch("app.services.whatsapp_template_delivery_service.httpx.post", return_value=response), \
                     patch.object(whatsapp_agenda, "registrar_auditoria") as audit:
                    with self.assertRaises(HTTPException) as exc:
                        whatsapp_agenda.send_agenda_utility(
                            self.agendamento.id, payload, request=SimpleNamespace(), db=self.db,
                            current_user=SimpleNamespace(id=7, nome="Equipe teste"),
                        )
                self.assertEqual(exc.exception.status_code, 502)
                self.assertEqual(exc.exception.detail, "Falha legada.")
                audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
