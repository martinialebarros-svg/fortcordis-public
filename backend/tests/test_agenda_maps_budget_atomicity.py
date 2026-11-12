"""A Maps denial after one successful leg must roll back the Agenda mutation."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "agenda-budget-atomicity-synthetic-secret-123456")

from app.api.v1.endpoints import agenda
from app.models.agendamento import Agendamento
from app.models.assistente_ia import AssistenteIAAcaoPendente
from app.models.clinica import Clinica
from app.models.clinica_deslocamento import ClinicaDeslocamento
from app.models.configuracao import Configuracao
from app.models.google_maps_usage_metrica import GoogleMapsUsageMetrica
from app.models.google_maps_cost_control import COST_TABLES
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.services import assistente_ia_tools, logistica_service
from app.services import google_maps_cost_control as cost_guard
from app.services.google_maps_cost_control import GoogleMapsCostBlocked


class AgendaMapsBudgetAtomicityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # The stage canary supplies only its newly created isolated schema.
        self.engine = getattr(self, "_isolated_engine", None)
        if self.engine is None:
            self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "synthetic.db"), connect_args={"check_same_thread": False})
        for model in (Agendamento, AssistenteIAAcaoPendente, Clinica, ClinicaDeslocamento, Configuracao, GoogleMapsUsageMetrica, Paciente, Servico, Tutor):
            model.__table__.create(self.engine)
        # Atomicity unit cases stub reservations explicitly; policy reads still
        # need a real isolated table, never the developer/global database.
        for table in COST_TABLES:
            table.create(self.engine)
        ledger = patch.object(cost_guard.database, "engine", self.engine)
        ledger.start()
        self.addCleanup(ledger.stop)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        with self.sessions() as db:
            db.add(Configuracao(
                agenda_semanal=json.dumps({str(day): {"ativo": True, "inicio": "08:00", "fim": "18:00"} for day in range(1, 8)}),
                agenda_feriados="[]", agenda_excecoes="[]",
                agenda_rota_regras=json.dumps({"route_policy": {"reject_clear_inefficiency": False}}),
            ))
            clinics = [Clinica(nome=f"Clínica sintética {i}", ativo=True, latitude=-3.7, longitude=-38.5, place_id=f"synthetic-{i}") for i in range(3)]
            tutor = Tutor(nome="Tutor sintético", ativo=1, latitude=-3.7, longitude=-38.6, place_id="synthetic-home", endereco="Endereço sintético", numero="1", cidade="Fortaleza", estado="CE")
            service = Servico(nome="Serviço sintético", duracao_minutos=30, ativo=True)
            db.add_all([*clinics, tutor, service])
            db.flush()
            patient = Paciente(nome="Paciente sintético", tutor_id=tutor.id, ativo=1)
            db.add(patient)
            db.flush()
            rows = []
            for clinic, hour in zip(clinics, (9, 11, 14)):
                start = datetime(2099, 5, 25, hour, tzinfo=agenda.LOCAL_TZ)
                rows.append(Agendamento(clinica_id=clinic.id, tutor_id=tutor.id, paciente_id=patient.id,
                    servico_id=service.id, inicio=start, fim=start + timedelta(minutes=30),
                    data="2099-05-25", hora=f"{hour:02}:00", status="Agendado"))
            db.add_all(rows)
            db.commit()
            self.id = rows[1].id
            self.clinic_id = clinics[1].id
            self.original_start = rows[1].inicio
        self.app = FastAPI()
        self.app.include_router(agenda.router, prefix="/agenda")

        def request_db():
            with self.sessions() as db:
                yield db

        self.app.dependency_overrides[agenda.get_db] = request_db
        self.app.dependency_overrides[agenda.get_current_user] = lambda: SimpleNamespace(id=1, nome="Admin sintético", tem_papel=lambda _: True)
        for patcher in (
            patch.object(logistica_service.settings, "GOOGLE_MAPS_API_KEY", "synthetic-key"),
            patch.object(logistica_service.settings, "LOGISTICA_ALLOW_LIVE_GOOGLE_LOOKUPS_ON_READ", True),
            patch.object(agenda, "registrar_auditoria"),
            patch.object(agenda, "_notificar_agenda_update"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def _request_with_one_paid_leg(self, method, suffix="", **kwargs):
        with (
            patch.object(logistica_service, "authorize_google_call", side_effect=[None, GoogleMapsCostBlocked("action_limit")]) as reserve,
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
            TestClient(self.app) as client,
        ):
            response = client.request(method, f"/agenda/{self.id}{suffix}", **kwargs)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["reason"], "action_limit")
        self.assertEqual(reserve.call_count, 2)
        self.assertEqual(network.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
            self.assertEqual(db.query(GoogleMapsUsageMetrica).count(), 0)

    def test_update_two_legs_denial_preserves_original_after_reload(self):
        self._request_with_one_paid_leg("PUT", json={"inicio": "2099-05-25T11:30:00", "fim": "2099-05-25T12:00:00"})
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_home_visit_update_uses_same_atomic_validation(self):
        with self.sessions() as db:
            row = db.get(Agendamento, self.id)
            row.origem_atendimento = "domiciliar"
            row.clinica_id = None
            db.commit()
        self._request_with_one_paid_leg("PUT", json={"inicio": "2099-05-25T11:30:00", "fim": "2099-05-25T12:00:00"})
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)

    def test_status_reactivation_denial_preserves_cancelled_status(self):
        with self.sessions() as db:
            db.get(Agendamento, self.id).status = "Cancelado"
            db.commit()
        self._request_with_one_paid_leg("PATCH", "/status", params={"status": "Agendado"})
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).status, "Cancelado")

    def test_expired_reservation_denial_preserves_status_and_deadline(self):
        old_deadline = datetime(2026, 1, 1)
        with self.sessions() as db:
            row = db.get(Agendamento, self.id)
            row.status = "Expirado"
            row.reserva_expira_em = old_deadline
            db.commit()
        self._request_with_one_paid_leg("POST", "/reabilitar-reserva", json={"prazo_confirmacao_horas": 24})
        with self.sessions() as db:
            row = db.get(Agendamento, self.id)
            self.assertEqual((row.status, row.reserva_expira_em), ("Expirado", old_deadline))

    def test_success_commits_appointment_and_cache_together(self):
        with (
            patch.object(logistica_service, "authorize_google_call"),
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
            TestClient(self.app) as client,
        ):
            response = client.put(f"/agenda/{self.id}", json={"inicio": "2099-05-25T11:30:00", "fim": "2099-05-25T12:00:00"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(network.call_count, 2)
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, datetime(2099, 5, 25, 11, 30))
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 4)

    def test_offer_validation_propagates_cost_reason_and_preserves_read_cache(self):
        with (
            patch.object(logistica_service, "authorize_google_call", side_effect=[None, GoogleMapsCostBlocked("action_limit")]),
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
            TestClient(self.app) as client,
        ):
            response = client.post("/agenda/assistente/validar-oferta", json={
                "inicio": "2099-05-25 11:30", "clinica_id": self.clinic_id,
                "ignorar_agendamento_id": self.id, "duracao_minutos": 30,
            })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["reason"], "action_limit")
        self.assertEqual(network.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 2)

    def test_ia_reschedule_denial_does_not_commit_business_write_or_invalidate_action(self):
        action_id = "synthetic-reschedule-action"
        user = SimpleNamespace(id=1, nome="Admin sintético", tem_papel=lambda _: True)
        with self.sessions() as db:
            appointment = db.get(Agendamento, self.id)
            action = AssistenteIAAcaoPendente(
                id=action_id, conversa_id="synthetic-conversation", usuario_id=1,
                tipo_acao="reschedule_appointment", status="pending",
                argumentos_json=json.dumps({"agendamento_id": self.id, "inicio": "2099-05-25T11:30:00", "fim": "2099-05-25T12:00:00"}),
                alvo_snapshot_json=json.dumps(assistente_ia_tools._appointment_snapshot(db, appointment)),
                expires_at=datetime(2099, 5, 25),
            )
            db.add(action)
            db.commit()
        with (
            self.sessions() as db,
            patch.object(logistica_service, "authorize_google_call", side_effect=[None, GoogleMapsCostBlocked("action_limit")]),
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
        ):
            with self.assertRaises(HTTPException) as caught:
                assistente_ia_tools._approve_reschedule_or_cancel(
                    db=db, current_user=user, request=None,
                    action=db.get(AssistenteIAAcaoPendente, action_id),
                    now_utc=datetime(2026, 10, 18), observation=None,
                )
        self.assertEqual(network.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.get(Agendamento, self.id).inicio, self.original_start)
            self.assertEqual(db.get(AssistenteIAAcaoPendente, action_id).status, "pending")
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
        self.assertIsInstance(caught.exception, GoogleMapsCostBlocked)
        self.assertEqual(caught.exception.reason, "action_limit")

    def test_ia_availability_stops_on_cost_denial_instead_of_reporting_empty_days(self):
        with self.sessions() as db:
            ctx = assistente_ia_tools.AssistenteIAToolContext(
                db=db, current_user=SimpleNamespace(id=1), conversa=SimpleNamespace(id="synthetic-conversation"),
            )
            with patch.object(agenda, "sugerir_horarios_agenda", side_effect=GoogleMapsCostBlocked("month_limit")) as search:
                with self.assertRaises(GoogleMapsCostBlocked):
                    assistente_ia_tools.verificar_disponibilidade(
                        ctx, clinica="Clínica sintética 1", servico="Serviço sintético",
                        data_inicio="2099-05-25", dias=7,
                    )
            self.assertEqual(search.call_count, 1)

    def test_ia_preparation_propagates_cost_denial_without_a_pending_action(self):
        with (
            self.sessions() as db,
            patch.object(logistica_service, "authorize_google_call", side_effect=[None, GoogleMapsCostBlocked("action_limit")]),
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
        ):
            ctx = assistente_ia_tools.AssistenteIAToolContext(
                db=db, current_user=SimpleNamespace(id=1, tem_papel=lambda _: True),
                conversa=SimpleNamespace(id="synthetic-conversation"),
            )
            with self.assertRaises(GoogleMapsCostBlocked):
                assistente_ia_tools.solicitar_criacao_agendamento(
                    ctx, tipo="agendamento", origem_atendimento="clinica_parceira",
                    clinica="Clínica sintética 0", tutor=f"#{db.query(Tutor.id).scalar()}", paciente="Paciente sintético",
                    servico="Serviço sintético", data="2099-05-25", horario="12:00",
                    destinatario_mensagem="clinica", prazo_confirmacao_horas=None, observacoes=None,
                )
        self.assertEqual(network.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 3)
            self.assertEqual(db.query(AssistenteIAAcaoPendente).count(), 0)
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)

    def test_ia_creation_denial_keeps_approval_pending_and_rolls_back_cache(self):
        action_id = "synthetic-creation-action"
        with self.sessions() as db:
            clinic = db.query(Clinica).order_by(Clinica.id).first()
            service, patient, tutor = db.query(Servico).first(), db.query(Paciente).first(), db.query(Tutor).first()
            action = AssistenteIAAcaoPendente(
                id=action_id, conversa_id="synthetic-conversation", usuario_id=1,
                tipo_acao="create_appointment", status="pending", expires_at=datetime(2099, 5, 25),
                argumentos_json=json.dumps({
                    "tipo": "agendamento", "origem_atendimento": "clinica_parceira", "clinica_id": clinic.id,
                    "servico_id": service.id, "paciente_id": patient.id, "tutor_id": tutor.id,
                    "inicio": "2099-05-25T12:00:00", "fim": "2099-05-25T12:30:00",
                }),
                alvo_snapshot_json=json.dumps({"referencias": assistente_ia_tools._references_snapshot(clinic, service, patient, tutor)}),
            )
            db.add(action)
            db.commit()
        with (
            self.sessions() as db,
            patch.object(logistica_service, "authorize_google_call", side_effect=[None, GoogleMapsCostBlocked("action_limit")]),
            patch.object(logistica_service, "_http_post_json", return_value={"routes": [{"distanceMeters": 1000, "duration": "600s"}]}) as network,
        ):
            with self.assertRaises(GoogleMapsCostBlocked):
                assistente_ia_tools._approve_appointment_creation(
                    db=db, current_user=SimpleNamespace(id=1, nome="Admin sintético", tem_papel=lambda _: True), request=None,
                    action=db.get(AssistenteIAAcaoPendente, action_id), now_utc=datetime(2026, 10, 18), observation=None,
                )
        self.assertEqual(network.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(Agendamento).count(), 3)
            self.assertEqual(db.get(AssistenteIAAcaoPendente, action_id).status, "pending")
            self.assertEqual(db.query(ClinicaDeslocamento).count(), 0)
