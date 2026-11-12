import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-clinica-financeiro-test-secret-key-1234567890")

from app.api.v1.endpoints import portal
from app.core.portal_security import PortalSessionContext
from app.models.clinica import Clinica
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico


def _portal_session(*, clinica_id: int, actor_type: str = "clinica") -> PortalSessionContext:
    return PortalSessionContext(
        actor_type=actor_type,
        actor_id=1,
        paciente_id=None,
        clinica_id=clinica_id,
        challenge_id="challenge-teste",
        display_name="Clinica Teste",
        channel="email",
        scope=("clinic:read",),
        expires_at=datetime(2099, 1, 1),
    )


class PortalClinicaFinanceiroTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-clinica-financeiro.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (Clinica.__table__, Paciente.__table__, Servico.__table__, OrdemServico.__table__):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed(self, db):
        clinica_a = Clinica(nome="Clinica Parceira A", email="a@example.com", ativo=True)
        clinica_b = Clinica(nome="Clinica Parceira B", email="b@example.com", ativo=True)
        db.add_all([clinica_a, clinica_b])
        db.flush()

        paciente = Paciente(nome="Luna", especie="Canina", ativo=1)
        servico = Servico(nome="Ecocardiograma")
        db.add_all([paciente, servico])
        db.flush()

        pendente_a = OrdemServico(
            numero_os="OS202608" + "0001",
            agendamento_id=1,
            paciente_id=paciente.id,
            clinica_id=clinica_a.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 8, 1, 9, 0),
            valor_servico=200,
            valor_final=200,
            status="Pendente",
        )
        paga_a = OrdemServico(
            numero_os="OS202608" + "0002",
            agendamento_id=2,
            paciente_id=paciente.id,
            clinica_id=clinica_a.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 7, 20, 9, 0),
            valor_servico=150,
            valor_final=150,
            status="Pago",
        )
        cancelada_a = OrdemServico(
            numero_os="OS202608" + "0003",
            agendamento_id=3,
            paciente_id=paciente.id,
            clinica_id=clinica_a.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 7, 15, 9, 0),
            valor_servico=100,
            valor_final=100,
            status="Cancelado",
        )
        pendente_b = OrdemServico(
            numero_os="OS202608" + "0004",
            agendamento_id=4,
            paciente_id=paciente.id,
            clinica_id=clinica_b.id,
            servico_id=servico.id,
            data_atendimento=datetime(2026, 8, 1, 9, 0),
            valor_servico=300,
            valor_final=300,
            status="Pendente",
        )
        db.add_all([pendente_a, paga_a, cancelada_a, pendente_b])
        db.commit()
        for item in (clinica_a, clinica_b, pendente_a, paga_a, cancelada_a, pendente_b):
            db.refresh(item)
        return clinica_a, clinica_b, pendente_a, paga_a, cancelada_a, pendente_b

    def test_retorna_apenas_pendentes_e_pagas_da_propria_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, pendente_a, paga_a, cancelada_a, pendente_b = self._seed(db)

            response = portal.obter_financeiro_clinica_portal(
                db=db,
                portal_session=_portal_session(clinica_id=clinica_a.id),
            )

            pendentes_ids = {item.id for item in response.pendentes}
            pagas_ids = {item.id for item in response.pagas}

            self.assertEqual(pendentes_ids, {pendente_a.id})
            self.assertEqual(pagas_ids, {paga_a.id})
            self.assertNotIn(cancelada_a.id, pendentes_ids | pagas_ids)
            self.assertNotIn(pendente_b.id, pendentes_ids)

            self.assertEqual(response.summary.total_pendente, 200.0)
            self.assertEqual(response.summary.total_pago, 150.0)
            self.assertEqual(response.summary.quantidade_pendente, 1)
            self.assertEqual(response.summary.quantidade_pago, 1)

            item_pendente = response.pendentes[0]
            self.assertEqual(item_pendente.paciente_nome, "Luna")
            self.assertEqual(item_pendente.servico_nome, "Ecocardiograma")
            self.assertEqual(item_pendente.numero_os, pendente_a.numero_os)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sessao_sem_clinica_nao_acessa_financeiro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, *_ = self._seed(db)
            with self.assertRaises(HTTPException) as ctx:
                portal.obter_financeiro_clinica_portal(
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id, actor_type="parceiro"),
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_clinica_sem_movimentacao_recebe_resumo_zerado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, *_ = self._seed(db)

            response = portal.obter_financeiro_clinica_portal(
                db=db,
                portal_session=_portal_session(clinica_id=clinica_b.id),
            )

            self.assertEqual(response.summary.total_pago, 0)
            self.assertEqual(response.summary.quantidade_pago, 0)
            self.assertEqual(len(response.pagas), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
