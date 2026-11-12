import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "whatsapp-conversation-context-test-secret-key-1234567890")

from app.api.v1.endpoints.whatsapp_contexto import resolve_whatsapp_context
from app.models.agendamento import Agendamento
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor
from app.models.whatsapp_bot import WhatsAppBotContextoSelecao


class WhatsappConversationContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        database_path = Path(self._tmpdir.name) / "whatsapp-context.db"
        self._engine = create_engine(f"sqlite:///{database_path}")
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Servico.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
            WhatsAppBotContextoSelecao.__table__,
        ):
            table.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _seed_context(self, db):
        clinic = Clinica(
            nome="Animal Care",
            telefone="(85) 3333-4444",
            whatsapps=["(85) 8828-1436"],
            cidade="Fortaleza",
            estado="CE",
            ativo=True,
        )
        tutor = Tutor(
            nome="Maria Oliveira",
            telefone="(85) 3222-0000",
            whatsapp="(85) 99999-0001",
            ativo=1,
        )
        service = Servico(nome="Ecocardiograma", ativo=True)
        db.add_all([clinic, tutor, service])
        db.commit()
        db.refresh(clinic)
        db.refresh(tutor)
        db.refresh(service)

        patient = Paciente(
            tutor_id=tutor.id,
            nome="Gamora",
            especie="Canina",
            raca="SRD",
            ativo=1,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

        start = datetime.now(timezone.utc) + timedelta(days=1)
        appointment = Agendamento(
            paciente_id=patient.id,
            tutor_id=tutor.id,
            clinica_id=clinic.id,
            servico_id=service.id,
            inicio=start,
            fim=start + timedelta(minutes=30),
            data=start.date().isoformat(),
            hora=start.strftime("%H:%M"),
            status="Confirmado",
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)

        service_order = OrdemServico(
            numero_os="OS-0001",
            agendamento_id=appointment.id,
            paciente_id=patient.id,
            clinica_id=clinic.id,
            servico_id=service.id,
            data_atendimento=start,
            status="Pendente",
            valor_final=250,
        )
        db.add(service_order)
        db.commit()
        return clinic, tutor, patient, appointment, service_order

    def test_resolve_clinic_and_related_domain_records(self) -> None:
        with self._session_factory() as db:
            clinic, tutor, patient, appointment, service_order = self._seed_context(db)
            result = resolve_whatsapp_context(db, "+55 85 8828-1436")

        self.assertEqual(result["resolution"], "matched")
        self.assertEqual(result["match_type"], "clinica")
        self.assertEqual(result["normalized_phone"], "558588281436")
        self.assertEqual(result["clinicas"][0]["id"], clinic.id)
        self.assertEqual(result["tutores"][0]["id"], tutor.id)
        self.assertEqual(result["pets"][0]["id"], patient.id)
        self.assertEqual(result["agendamentos"][0]["id"], appointment.id)
        self.assertEqual(result["ordens_servico"][0]["id"], service_order.id)
        self.assertNotIn("observacoes", str(result).lower())

    def test_resolve_tutor_and_pet(self) -> None:
        with self._session_factory() as db:
            clinic, tutor, patient, appointment, service_order = self._seed_context(db)
            result = resolve_whatsapp_context(db, "85999990001")

        self.assertEqual(result["resolution"], "matched")
        self.assertEqual(result["match_type"], "tutor")
        self.assertEqual(result["tutores"][0]["id"], tutor.id)
        self.assertEqual(result["pets"][0]["id"], patient.id)
        self.assertEqual(result["clinicas"][0]["id"], clinic.id)
        self.assertEqual(result["agendamentos"][0]["id"], appointment.id)
        self.assertEqual(result["ordens_servico"][0]["id"], service_order.id)

    def test_resolve_tutor_pela_identidade_canonica_sem_nono_digito(self) -> None:
        """CA-012 (nono digito): tutor cadastrado como (85) 99999-0001 (forma

        local, com o nono digito) tambem resolve para `matched` quando a
        consulta chega na forma canonica do Node (sem o nono digito,
        558599990001), que e como `conversations.wa_phone_number` fica
        armazenado no whatsapp-stage-backend.
        """
        with self._session_factory() as db:
            clinic, tutor, patient, appointment, service_order = self._seed_context(db)
            result = resolve_whatsapp_context(db, "558599990001")

        self.assertEqual(result["resolution"], "matched")
        self.assertEqual(result["match_type"], "tutor")
        self.assertEqual(result["tutores"][0]["id"], tutor.id)
        self.assertEqual(result["pets"][0]["id"], patient.id)
        self.assertEqual(result["clinicas"][0]["id"], clinic.id)
        self.assertEqual(result["agendamentos"][0]["id"], appointment.id)
        self.assertEqual(result["ordens_servico"][0]["id"], service_order.id)
        # normalized_phone reflete a forma consultada (Node), sem o nono digito -
        # nao muda o contrato existente do endpoint.
        self.assertEqual(result["normalized_phone"], "558599990001")

    def test_resolve_nao_confunde_fixo_de_clinica_com_movel_sem_nono_digito(self) -> None:
        """A busca por variantes do nono digito parte so do numero consultado

        (que sempre vem de uma conversa de WhatsApp, logo e movel); um fixo
        de clinica com o mesmo formato de 12 digitos nao ganha uma variante
        "com nono digito" fantasma que poderia colidir com outro cadastro.
        """
        with self._session_factory() as db:
            self._seed_context(db)
            # Fixo de 12 digitos (55 + DDD + 8 digitos) que nao existe como
            # cadastro de ninguem - nao deve casar com o tutor de teste.
            result = resolve_whatsapp_context(db, "558533339999")

        self.assertEqual(result["resolution"], "not_found")

    def test_duplicate_number_is_ambiguous_and_does_not_expand_context(self) -> None:
        with self._session_factory() as db:
            _clinic, tutor, _patient, _appointment, _service_order = self._seed_context(db)
            duplicate = Clinica(
                nome="Clinica com numero compartilhado",
                telefone=tutor.whatsapp,
                whatsapps=[],
                ativo=True,
            )
            db.add(duplicate)
            db.commit()

            result = resolve_whatsapp_context(db, tutor.whatsapp)

        self.assertEqual(result["resolution"], "ambiguous")
        self.assertIsNone(result["match_type"])
        self.assertEqual(len(result["clinicas"]), 1)
        self.assertEqual(len(result["tutores"]), 1)
        self.assertEqual(result["pets"], [])
        self.assertEqual(result["agendamentos"], [])
        self.assertEqual(result["ordens_servico"], [])

    def test_unknown_number_returns_not_found(self) -> None:
        with self._session_factory() as db:
            self._seed_context(db)
            result = resolve_whatsapp_context(db, "85911112222")

        self.assertEqual(result["resolution"], "not_found")
        self.assertIsNone(result["match_type"])
        self.assertEqual(result["clinicas"], [])
        self.assertEqual(result["tutores"], [])


if __name__ == "__main__":
    unittest.main()
