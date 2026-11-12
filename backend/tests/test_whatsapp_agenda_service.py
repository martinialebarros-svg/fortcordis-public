import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-agenda-test-secret-key-1234567890")

from app.models.agendamento import Agendamento
from app.models.alerta_interno import AlertaInterno
from app.models.clinica import Clinica
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.whatsapp_agenda_resposta import WhatsappAgendaResposta
from app.services.whatsapp_agenda_service import (
    WhatsAppAgendaUtilityTemplate,
    WhatsAppReservationTemplate,
    build_agenda_utility_template,
    build_reservation_template,
    normalize_whatsapp_number,
    process_button_response,
    send_agenda_utility_template,
    send_reservation_template,
)
from app.api.v1.endpoints.whatsapp_agenda import _require_internal_token
from app.core.config import settings


class WhatsAppAgendaServiceTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "whatsapp-agenda.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Clinica.__table__,
            Tutor.__table__,
            Paciente.__table__,
            Agendamento.__table__,
            AlertaInterno.__table__,
            WhatsappAgendaResposta.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_reservation(self, db, *, expired=False, status="Reservado"):
        clinica = Clinica(
            nome="Clinica Teste",
            telefone="(85) 98888-1111",
            whatsapps=["5585988881111", "5585877772222"],
            ativo=True,
        )
        tutor = Tutor(nome="Maria", telefone="(85) 99999-3333", whatsapp="5585999993333", ativo=1)
        db.add_all([clinica, tutor])
        db.flush()
        paciente = Paciente(nome="Thor", tutor_id=tutor.id, ativo=1)
        db.add(paciente)
        db.flush()
        now = datetime.now(timezone.utc)
        agendamento = Agendamento(
            clinica_id=clinica.id,
            tutor_id=tutor.id,
            paciente_id=paciente.id,
            inicio=now + timedelta(days=1),
            fim=now + timedelta(days=1, minutes=30),
            status=status,
            reserva_expira_em=now - timedelta(minutes=1) if expired else now + timedelta(hours=2),
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        return clinica, tutor, paciente, agendamento

    def _seed_reservation_sem_paciente_tutor(self, db, *, expired=False):
        clinica = Clinica(
            nome="Clinica Teste",
            telefone="(85) 98888-1111",
            whatsapps=["5585988881111", "5585877772222"],
            ativo=True,
        )
        db.add(clinica)
        db.flush()
        now = datetime.now(timezone.utc)
        agendamento = Agendamento(
            clinica_id=clinica.id,
            tutor_id=None,
            paciente_id=None,
            inicio=now + timedelta(days=1),
            fim=now + timedelta(days=1, minutes=30),
            status="Reservado",
            reserva_expira_em=now - timedelta(minutes=1) if expired else now + timedelta(hours=2),
        )
        db.add(agendamento)
        db.commit()
        db.refresh(agendamento)
        return clinica, agendamento

    def test_build_reservation_template_aceita_reserva_sem_paciente_tutor_vinculados(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reservation_sem_paciente_tutor(db)
            template = build_reservation_template(
                db,
                agendamento=agendamento,
                destination="(85) 98888-1111",
                recipient_type="clinica",
            )
            self.assertEqual(template.recipient_name, "Clinica Teste")
            self.assertEqual(template.pet_name, "seu pet")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_reservation_template_exige_tutor_quando_destinatario_e_tutor(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reservation_sem_paciente_tutor(db)
            with self.assertRaises(HTTPException) as ctx:
                build_reservation_template(
                    db,
                    agendamento=agendamento,
                    destination="(85) 98888-1111",
                    recipient_type="tutor",
                )
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_agenda_utility_template_missing_data_aceita_sem_paciente_tutor(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reservation_sem_paciente_tutor(db)
            template = build_agenda_utility_template(
                db,
                agendamento=agendamento,
                destination="(85) 98888-1111",
                recipient_type="clinica",
                template_key="appointmentMissingData",
            )
            self.assertEqual(template.parameters[0], "Clinica Teste")
            self.assertEqual(template.parameters[1], "seu pet")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_agenda_utility_template_outros_modelos_continuam_exigindo_paciente_tutor(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, agendamento = self._seed_reservation_sem_paciente_tutor(db)
            with self.assertRaises(HTTPException) as ctx:
                build_agenda_utility_template(
                    db,
                    agendamento=agendamento,
                    destination="(85) 98888-1111",
                    recipient_type="clinica",
                    template_key="appointmentReminder",
                )
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_template_only_accepts_registered_recipient_number(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db)
            template = build_reservation_template(
                db,
                agendamento=agendamento,
                destination="(85) 98888-1111",
                recipient_type="clinica",
            )
            self.assertEqual(template.destination, "5585988881111")
            self.assertEqual(template.recipient_name, "Clinica Teste")
            self.assertEqual(template.pet_name, "Thor")
            self.assertIn("às", template.confirmation_deadline)
            self.assertEqual(normalize_whatsapp_number("85 99999-3333"), "5585999993333")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_confirm_is_idempotent_and_updates_active_reservation(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db)
            result, idempotent = process_button_response(
                db,
                provider_message_id="wamid.confirm.123",
                outbound_message_id="wamid.outbound.123",
                agendamento_id=agendamento.id,
                action="confirmar",
                from_phone="5585988881111",
            )
            self.assertFalse(idempotent)
            self.assertEqual(result["result"], "confirmado")
            db.refresh(agendamento)
            self.assertEqual(agendamento.status, "Confirmado")
            self.assertEqual(agendamento.confirmado_por_nome, "WhatsApp Fort Cordis")

            repeated, repeated_idempotent = process_button_response(
                db,
                provider_message_id="wamid.confirm.123",
                outbound_message_id="wamid.outbound.123",
                agendamento_id=agendamento.id,
                action="confirmar",
                from_phone="5585988881111",
            )
            self.assertTrue(repeated_idempotent)
            self.assertEqual(repeated["result"], "confirmado")
            self.assertEqual(db.query(WhatsappAgendaResposta).count(), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_late_confirmation_does_not_reactivate_and_creates_alert(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db, expired=True)
            result, _ = process_button_response(
                db,
                provider_message_id="wamid.late.123",
                outbound_message_id="wamid.outbound.456",
                agendamento_id=agendamento.id,
                action="confirmar",
                from_phone="5585988881111",
            )
            db.refresh(agendamento)
            self.assertEqual(result["result"], "confirmacao_apos_prazo")
            self.assertEqual(agendamento.status, "Expirado")
            alerta = db.query(AlertaInterno).one()
            self.assertEqual(alerta.tipo, "whatsapp_reserva_confirmacao_atrasada")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_change_request_keeps_schedule_and_creates_staff_alert(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db)
            result, _ = process_button_response(
                db,
                provider_message_id="wamid.change.123",
                outbound_message_id="wamid.outbound.789",
                agendamento_id=agendamento.id,
                action="solicitar_alteracao",
                from_phone="5585988881111",
            )
            db.refresh(agendamento)
            self.assertEqual(result["result"], "alteracao_solicitada")
            self.assertEqual(agendamento.status, "Reservado")
            alerta = db.query(AlertaInterno).one()
            self.assertEqual(alerta.tipo, "whatsapp_reserva_solicitar_alteracao")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_falar_equipe_cria_alerta_interno_independente_do_status(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db, status="Agendado")
            result, idempotent = process_button_response(
                db,
                provider_message_id="wamid.falar-equipe.123",
                outbound_message_id="wamid.outbound.999",
                agendamento_id=agendamento.id,
                action="falar_equipe",
                from_phone="5585988881111",
            )
            db.refresh(agendamento)
            self.assertFalse(idempotent)
            self.assertEqual(result["result"], "falar_equipe_solicitado")
            self.assertEqual(agendamento.status, "Agendado")
            alerta = db.query(AlertaInterno).one()
            self.assertEqual(alerta.tipo, "whatsapp_agenda_falar_equipe")

            _result_again, idempotent_again = process_button_response(
                db,
                provider_message_id="wamid.falar-equipe.123",
                outbound_message_id="wamid.outbound.999",
                agendamento_id=agendamento.id,
                action="falar_equipe",
                from_phone="5585988881111",
            )
            self.assertTrue(idempotent_again)
            self.assertEqual(db.query(AlertaInterno).count(), 1)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_delivery_contract_uses_internal_token_and_expected_parameters(self):
        response = SimpleNamespace(
            status_code=201,
            json=lambda: {"message_id": "wamid.outbound.contract", "idempotent": False},
        )
        template = WhatsAppReservationTemplate(
            destination="5585988881111",
            recipient_name="Clinica Teste",
            pet_name="Thor",
            appointment_date="12/08/2026",
            appointment_time="14:30",
            confirmation_deadline="11/08/2026 às 18:00",
        )
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_agenda_service.httpx.post", return_value=response) as post,
        ):
            result = send_reservation_template(
                agendamento_id=42,
                template=template,
                idempotency_key="idempotency-123",
            )

        self.assertEqual(result["message_id"], "wamid.outbound.contract")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["X-WhatsApp-Internal-Token"], "internal-secret")
        self.assertEqual(kwargs["json"]["reservation_id"], 42)
        self.assertEqual(kwargs["json"]["parameters"]["pet_name"], "Thor")

    def test_build_agenda_utility_template_validates_status_and_recipient(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(
                db,
                status="Confirmado",
            )
            template = build_agenda_utility_template(
                db,
                agendamento=agendamento,
                destination="(85) 98888-1111",
                recipient_type="clinica",
                template_key="appointmentReminder",
            )
            self.assertEqual(template.template_key, "appointmentReminder")
            self.assertEqual(template.destination, "5585988881111")
            self.assertEqual(template.parameters[0], "Clinica Teste")
            self.assertEqual(template.parameters[1], "Thor")

            with self.assertRaises(HTTPException) as invalid_cancellation:
                build_agenda_utility_template(
                    db,
                    agendamento=agendamento,
                    destination="(85) 98888-1111",
                    recipient_type="clinica",
                    template_key="appointmentCancellation",
                )
            self.assertEqual(invalid_cancellation.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_build_agenda_utility_template_formalized_monta_sete_parametros(self):
        tmpdir, db, engine = self._build_session()
        try:
            _clinica, _tutor, _paciente, agendamento = self._seed_reservation(db, status="Agendado")
            agendamento.servico = "Ecocardiograma"
            db.commit()
            db.refresh(agendamento)

            template = build_agenda_utility_template(
                db,
                agendamento=agendamento,
                destination="(85) 98888-1111",
                recipient_type="clinica",
                template_key="appointmentFormalized",
            )

            self.assertEqual(template.template_key, "appointmentFormalized")
            self.assertEqual(len(template.parameters), 7)
            self.assertEqual(template.parameters[0], "Clinica Teste")
            self.assertEqual(template.parameters[1], "Ecocardiograma")
            self.assertEqual(template.parameters[2], "Thor")
            self.assertEqual(template.parameters[3], "Maria")
            self.assertEqual(template.parameters[6], "Clinica Teste")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agenda_utility_delivery_uses_approved_template_contract(self):
        response = SimpleNamespace(
            status_code=201,
            json=lambda: {"message_id": "wamid.utility.contract", "idempotent": False},
        )
        template = WhatsAppAgendaUtilityTemplate(
            template_key="appointmentChange",
            destination="5585988881111",
            parameters=("Clinica Teste", "Thor", "16/08/2026", "14:30"),
        )
        with (
            patch.object(settings, "WHATSAPP_AGENDA_ENABLED", True),
            patch.object(settings, "WHATSAPP_AGENDA_SERVICE_URL", "http://127.0.0.1:3010"),
            patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "internal-secret"),
            patch("app.services.whatsapp_agenda_service.httpx.post", return_value=response) as post,
        ):
            result = send_agenda_utility_template(
                agendamento_id=42,
                template=template,
                idempotency_key="utility-idempotency-123",
            )

        self.assertEqual(result["message_id"], "wamid.utility.contract")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["template_key"], "appointmentChange")
        self.assertEqual(kwargs["json"]["subject_type"], "agendamento")
        self.assertEqual(kwargs["json"]["subject_id"], 42)
        self.assertEqual(kwargs["json"]["parameters"][1], "Thor")

    def test_internal_callback_rejects_missing_or_wrong_token(self):
        with patch.object(settings, "WHATSAPP_AGENDA_INTERNAL_TOKEN", "expected-secret"):
            with self.assertRaises(HTTPException) as missing:
                _require_internal_token(None)
            self.assertEqual(missing.exception.status_code, 401)

            with self.assertRaises(HTTPException) as wrong:
                _require_internal_token("wrong-secret")
            self.assertEqual(wrong.exception.status_code, 401)

            self.assertIsNone(_require_internal_token("expected-secret"))


if __name__ == "__main__":
    unittest.main()
