"""Presença pelo lembrete registra recibo, sem formalizar ou alterar a agenda."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "whatsapp-presence-test-secret-1234567890")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import whatsapp_agenda
from app.core.config import settings
from app.db.database import get_db
from app.models.agendamento import Agendamento
from app.models.alerta_interno import AlertaInterno
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.services.whatsapp_agenda_service import process_button_response
from app.services.push_notifications import _build_agenda_title, _build_agenda_body


class WhatsAppAgendaPresenceTests(unittest.TestCase):
    def test_internal_push_distinguishes_presence_from_reservation_or_attendance(self):
        data = {"action": "confirmar_presenca", "result": "presenca_confirmada", "status": "Agendado"}
        self.assertEqual(
            _build_agenda_title("whatsapp_reserva_resposta", 19, data),
            "Presenca registrada pelo WhatsApp - agendamento #19",
        )
        self.assertIn("horario e status da agenda foram preservados", _build_agenda_body("whatsapp_reserva_resposta", data))

    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        # Sem tabelas de paciente/tutor: presença não exige nova consulta clínica.
        for model in (Agendamento, AlertaInterno, WhatsappAgendaResposta):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.addCleanup(self.db.close)
        self.now = datetime.now(timezone.utc)

    def appointment(self, status="Agendado", *, expired=False):
        row = Agendamento(
            clinica_id=9, paciente_id=None, tutor_id=None,
            inicio=self.now + timedelta(days=1),
            fim=self.now + timedelta(days=1, minutes=30),
            status=status,
            reserva_expira_em=self.now + timedelta(hours=-1 if expired else 2),
            confirmado_por_id=7 if status == "Confirmado" else None,
            confirmado_por_nome="Equipe" if status == "Confirmado" else None,
            confirmado_em=self.now - timedelta(hours=1) if status == "Confirmado" else None,
            updated_at=self.now - timedelta(hours=2),
            atualizado_em=self.now - timedelta(hours=2),
            observacoes="Dados operacionais preservados",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def snapshot(self, appointment):
        self.db.refresh(appointment)
        return {column.name: getattr(appointment, column.name) for column in Agendamento.__table__.columns}

    def payload(self, appointment, message_id):
        return {
            "provider_message_id": message_id,
            "outbound_message_id": "wamid.reminder.synthetic",
            "agendamento_id": appointment.id,
            "action": "confirmar_presenca",
            "from_phone": "5585987654321",
        }

    def api(self):
        app = FastAPI()
        app.include_router(whatsapp_agenda.router)
        app.dependency_overrides[get_db] = lambda: self.db
        audit = patch.object(whatsapp_agenda, "registrar_auditoria")
        self.audit = audit.start()
        self.addCleanup(audit.stop)
        notify = patch("app.api.v1.endpoints.agenda._notificar_agenda_update")
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        token = patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "presence-internal-test-token")
        token.start()
        self.addCleanup(token.stop)
        return TestClient(app)

    def test_presence_records_receipt_and_preserves_both_current_states(self):
        for status in ("Agendado", "Confirmado"):
            with self.subTest(status=status):
                appointment = self.appointment(status)
                before = self.snapshot(appointment)
                payload = self.payload(appointment, f"wamid.presence.{status}")
                result, idempotent = process_button_response(self.db, **payload)
                self.assertFalse(idempotent)
                self.assertEqual(result, {
                    "agendamento_id": appointment.id, "action": "confirmar_presenca",
                    "result": "presenca_confirmada", "status": status,
                })
                self.assertEqual(self.snapshot(appointment), before)
                receipt = self.db.query(WhatsappAgendaResposta).filter_by(
                    provider_message_id=payload["provider_message_id"],
                ).one()
                self.assertEqual(receipt.action, "confirmar_presenca")
                self.assertEqual(receipt.result, "presenca_confirmada")
                self.assertEqual(receipt.outbound_message_id, payload["outbound_message_id"])
                self.assertEqual(self.db.query(AlertaInterno).count(), 0)

    def test_presence_requires_review_for_reservation_and_final_or_unknown_status(self):
        cases = (("Reservado", False), ("Reservado", True), ("Expirado", True),
                 ("Cancelado", False), ("Realizado", False), ("Faltou", False),
                 ("Em atendimento", False), ("Estado desconhecido", False))
        for index, (status, expired) in enumerate(cases):
            with self.subTest(status=status, expired=expired):
                appointment = self.appointment(status, expired=expired)
                before = self.snapshot(appointment)
                result, idempotent = process_button_response(
                    self.db, **self.payload(appointment, f"wamid.presence.review.{index}"),
                )
                self.assertFalse(idempotent)
                self.assertEqual(result["result"], "revisao_manual")
                self.assertEqual(result["status"], status)
                self.assertEqual(self.snapshot(appointment), before)
                alert = self.db.query(AlertaInterno).filter_by(entidade_id=appointment.id).one()
                self.assertEqual(alert.tipo, "whatsapp_reserva_resposta_revisao")
                self.assertEqual(alert.clinica_id, appointment.clinica_id)

    def test_presence_retry_returns_first_receipt_after_appointment_status_changes(self):
        appointment = self.appointment()
        payload = self.payload(appointment, "wamid.presence.repeat")
        first, idempotent = process_button_response(self.db, **payload)
        self.assertFalse(idempotent)
        appointment.status = "Cancelado"
        self.db.commit()
        before_retry = self.snapshot(appointment)
        repeated, idempotent = process_button_response(self.db, **payload)
        self.assertTrue(idempotent)
        self.assertEqual(repeated, first)
        self.assertEqual(self.snapshot(appointment), before_retry)
        self.assertEqual(self.db.query(WhatsappAgendaResposta).count(), 1)
        self.assertEqual(self.db.query(AlertaInterno).count(), 0)

    def test_presence_for_missing_appointment_records_safe_result(self):
        result, idempotent = process_button_response(
            self.db, provider_message_id="wamid.presence.missing",
            outbound_message_id="wamid.reminder.synthetic", agendamento_id=999,
            action="confirmar_presenca", from_phone="5585987654321",
        )
        self.assertFalse(idempotent)
        self.assertEqual(result["result"], "agendamento_nao_encontrado")
        self.assertIsNone(result["status"])
        self.assertEqual(self.db.query(Agendamento).count(), 0)
        self.assertEqual(self.db.query(WhatsappAgendaResposta).count(), 1)
        self.assertEqual(self.db.query(AlertaInterno).count(), 0)

    def test_api_accepts_presence_and_preserves_both_current_states(self):
        with self.api() as client:
            for status in ("Agendado", "Confirmado"):
                with self.subTest(status=status):
                    appointment = self.appointment(status)
                    before = self.snapshot(appointment)
                    response = client.post(
                        "/integracoes/whatsapp/agenda/respostas",
                        json=self.payload(appointment, f"wamid.presence.api.{status}"),
                        headers={"x-fortcordis-whatsapp-token": "presence-internal-test-token"},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["result"], "presenca_confirmada")
                    self.assertEqual(response.json()["status"], status)
                    self.assertFalse(response.json()["idempotent"])
                    self.assertEqual(self.snapshot(appointment), before)
            self.assertEqual(self.db.query(WhatsappAgendaResposta).count(), 2)
            self.assertEqual(self.db.query(AlertaInterno).count(), 0)

    def test_api_keeps_internal_authentication_and_rejects_unknown_action(self):
        appointment = self.appointment()
        before = self.snapshot(appointment)
        payload = self.payload(appointment, "wamid.presence.api.unauthorized")
        with self.api() as client:
            for headers in ({}, {"x-fortcordis-whatsapp-token": "wrong-token"}):
                with self.subTest(headers=headers):
                    response = client.post("/integracoes/whatsapp/agenda/respostas", json=payload, headers=headers)
                    self.assertEqual(response.status_code, 401)
            response = client.post(
                "/integracoes/whatsapp/agenda/respostas", json={**payload, "action": "agendar"},
                headers={"x-fortcordis-whatsapp-token": "presence-internal-test-token"},
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.snapshot(appointment), before)
        self.assertEqual(self.db.query(WhatsappAgendaResposta).count(), 0)
        self.audit.assert_not_called()
        self.notify.assert_not_called()

    def test_api_presence_retry_is_idempotent_and_notifies_only_once(self):
        appointment = self.appointment()
        before = self.snapshot(appointment)
        payload = self.payload(appointment, "wamid.presence.api.repeat")
        with self.api() as client:
            headers = {"x-fortcordis-whatsapp-token": "presence-internal-test-token"}
            first = client.post("/integracoes/whatsapp/agenda/respostas", json=payload, headers=headers)
            repeated = client.post("/integracoes/whatsapp/agenda/respostas", json=payload, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json(), {**repeated.json(), "idempotent": False})
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(self.snapshot(appointment), before)
        self.assertEqual(self.db.query(WhatsappAgendaResposta).count(), 1)
        self.assertEqual(self.db.query(AlertaInterno).count(), 0)
        self.notify.assert_called_once()

    def test_api_presence_does_not_reactivate_expired_reservation(self):
        appointment = self.appointment("Reservado", expired=True)
        before = self.snapshot(appointment)
        with self.api() as client:
            response = client.post(
                "/integracoes/whatsapp/agenda/respostas",
                json=self.payload(appointment, "wamid.presence.api.expired"),
                headers={"x-fortcordis-whatsapp-token": "presence-internal-test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "revisao_manual")
        self.assertEqual(response.json()["status"], "Reservado")
        self.assertEqual(self.snapshot(appointment), before)
        self.assertEqual(self.db.query(AlertaInterno).count(), 1)


if __name__ == "__main__":
    unittest.main()
