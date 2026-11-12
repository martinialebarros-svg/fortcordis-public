import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-clinica-recibo-test-secret-key-1234567890")

from app.api.v1.endpoints import portal
from app.core.portal_security import PortalSessionContext
from app.models.clinica import Clinica
from app.models.configuracao import Configuracao
from app.models.financeiro import CreditoFinanceiro, OrdemServicoPagamento, Transacao
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor


def _portal_session(*, clinica_id: int) -> PortalSessionContext:
    return PortalSessionContext(
        actor_type="clinica",
        actor_id=1,
        paciente_id=None,
        clinica_id=clinica_id,
        challenge_id="challenge-teste",
        display_name="Clinica Teste",
        channel="email",
        scope=("clinic:read",),
        expires_at=datetime(2099, 1, 1),
    )


class PortalClinicaReciboTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-clinica-recibo.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Clinica.__table__,
            Paciente.__table__,
            Tutor.__table__,
            Servico.__table__,
            OrdemServico.__table__,
            OrdemServicoPagamento.__table__,
            Transacao.__table__,
            CreditoFinanceiro.__table__,
            Configuracao.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed(self, db):
        clinica_a = Clinica(nome="Clinica Parceira A", email="a@example.com", ativo=True)
        clinica_b = Clinica(nome="Clinica Parceira B", email="b@example.com", ativo=True)
        db.add_all([clinica_a, clinica_b])
        db.flush()

        tutor = Tutor(nome="Maria Tutora", ativo=1)
        db.add(tutor)
        db.flush()

        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
        servico = Servico(nome="Ecocardiograma")
        db.add_all([paciente, servico])
        db.flush()

        paga_a = OrdemServico(
            numero_os="OS2026080001",
            agendamento_id=1,
            paciente_id=paciente.id,
            clinica_id=clinica_a.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 7, 20, 9, 0),
            valor_servico=150,
            valor_final=150,
            status="Pago",
        )
        pendente_a = OrdemServico(
            numero_os="OS2026080002",
            agendamento_id=2,
            paciente_id=paciente.id,
            clinica_id=clinica_a.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 8, 1, 9, 0),
            valor_servico=200,
            valor_final=200,
            status="Pendente",
        )
        paga_b = OrdemServico(
            numero_os="OS2026080003",
            agendamento_id=3,
            paciente_id=paciente.id,
            clinica_id=clinica_b.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 7, 20, 9, 0),
            valor_servico=100,
            valor_final=100,
            status="Pago",
        )
        db.add_all([paga_a, pendente_a, paga_b])
        db.commit()
        for item in (clinica_a, clinica_b, paga_a, pendente_a, paga_b):
            db.refresh(item)
        return clinica_a, clinica_b, paga_a, pendente_a, paga_b

    def test_baixa_recibo_de_os_paga_da_propria_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, paga_a, pendente_a, paga_b = self._seed(db)

            response = portal.baixar_recibo_os_clinica_portal(
                paga_a.id,
                db=db,
                portal_session=_portal_session(clinica_id=clinica_a.id),
            )

            self.assertIsInstance(response, StreamingResponse)
            self.assertEqual(response.media_type, "application/pdf")
            self.assertIn(paga_a.numero_os, response.headers["content-disposition"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nao_baixa_recibo_de_os_de_outra_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, paga_a, pendente_a, paga_b = self._seed(db)

            with self.assertRaises(HTTPException) as ctx:
                portal.baixar_recibo_os_clinica_portal(
                    paga_b.id,
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id),
                )
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nao_baixa_recibo_de_os_pendente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, paga_a, pendente_a, paga_b = self._seed(db)

            with self.assertRaises(HTTPException) as ctx:
                portal.baixar_recibo_os_clinica_portal(
                    pendente_a.id,
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id),
                )
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
