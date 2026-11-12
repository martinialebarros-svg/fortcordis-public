import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-clinica-agendamentos-test-secret-key-1234567890")

from app.api.v1.endpoints import portal
from app.core.portal_security import PortalSessionContext
from app.models.agendamento import Agendamento
from app.models.alerta_interno import AlertaInterno
from app.models.clinica import Clinica


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


class PortalClinicaAgendamentosTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-clinica-agendamentos.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (Clinica.__table__, Agendamento.__table__, AlertaInterno.__table__):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed(self, db):
        clinica_a = Clinica(nome="Clinica Parceira A", email="a@example.com", ativo=True)
        clinica_b = Clinica(nome="Clinica Parceira B", email="b@example.com", ativo=True)
        db.add_all([clinica_a, clinica_b])
        db.flush()

        agendado_a = Agendamento(
            clinica_id=clinica_a.id,
            paciente="Luna",
            tutor="Maria",
            servico="Ecocardiograma",
            inicio=datetime(2026, 8, 10, 9, 0),
            data="2026-08-10",
            hora="09:00",
            status="Agendado",
        )
        reservado_a = Agendamento(
            clinica_id=clinica_a.id,
            servico="Ecocardiograma",
            inicio=datetime(2026, 8, 11, 10, 0),
            data="2026-08-11",
            hora="10:00",
            status="Reservado",
        )
        realizado_a = Agendamento(
            clinica_id=clinica_a.id,
            paciente="Rex",
            servico="Ecocardiograma",
            inicio=datetime(2026, 8, 1, 9, 0),
            data="2026-08-01",
            hora="09:00",
            status="Realizado",
        )
        cancelado_a = Agendamento(
            clinica_id=clinica_a.id,
            paciente="Thor",
            servico="Ecocardiograma",
            inicio=datetime(2026, 8, 2, 9, 0),
            data="2026-08-02",
            hora="09:00",
            status="Cancelado",
        )
        agendado_b = Agendamento(
            clinica_id=clinica_b.id,
            paciente="Mel",
            servico="Ecocardiograma",
            inicio=datetime(2026, 8, 12, 9, 0),
            data="2026-08-12",
            hora="09:00",
            status="Agendado",
        )
        db.add_all([agendado_a, reservado_a, realizado_a, cancelado_a, agendado_b])
        db.commit()
        for item in (clinica_a, clinica_b, agendado_a, reservado_a, realizado_a, cancelado_a, agendado_b):
            db.refresh(item)
        return clinica_a, clinica_b, agendado_a, reservado_a, realizado_a, cancelado_a, agendado_b

    def test_lista_apenas_agendamentos_ativos_da_propria_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, agendado_a, reservado_a, realizado_a, cancelado_a, agendado_b = self._seed(db)

            response = portal.listar_agendamentos_clinica_portal(
                db=db,
                portal_session=_portal_session(clinica_id=clinica_a.id),
            )

            ids_retornados = {item.id for item in response.items}
            self.assertEqual(response.total, 2)
            self.assertIn(agendado_a.id, ids_retornados)
            self.assertIn(reservado_a.id, ids_retornados)
            self.assertNotIn(realizado_a.id, ids_retornados)
            self.assertNotIn(cancelado_a.id, ids_retornados)
            self.assertNotIn(agendado_b.id, ids_retornados)

            por_id = {item.id: item for item in response.items}
            self.assertTrue(por_id[agendado_a.id].pode_cancelar)
            self.assertTrue(por_id[reservado_a.id].pode_cancelar)
            self.assertEqual(por_id[agendado_a.id].paciente_nome, "Luna")
            self.assertEqual(por_id[agendado_a.id].tutor_nome, "Maria")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sessao_sem_clinica_nao_acessa_agendamentos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, *_ = self._seed(db)
            with self.assertRaises(HTTPException) as ctx:
                portal.listar_agendamentos_clinica_portal(
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id, actor_type="tutor"),
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_cancela_agendamento_pendente_da_propria_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, agendado_a, *_ = self._seed(db)

            with patch.object(portal, "registrar_auditoria", return_value=None) as audit_mock:
                response = portal.cancelar_agendamento_clinica_portal(
                    agendado_a.id,
                    request=None,
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id),
                )
                audit_mock.assert_called_once()
                self.assertEqual(audit_mock.call_args.kwargs["acao"], "cancelar")
                self.assertEqual(audit_mock.call_args.kwargs["detalhes"]["clinica_id"], clinica_a.id)

            self.assertEqual(response.item.status, "Cancelado")
            self.assertFalse(response.item.pode_cancelar)

            db.refresh(agendado_a)
            self.assertEqual(agendado_a.status, "Cancelado")
            self.assertIn("[Portal] Cancelado pela clinica parceira", agendado_a.observacoes or "")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_cancelamento_cria_alerta_interno_explicito(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, agendado_a, *_ = self._seed(db)

            with patch.object(portal, "registrar_auditoria", return_value=None):
                portal.cancelar_agendamento_clinica_portal(
                    agendado_a.id,
                    request=None,
                    db=db,
                    portal_session=_portal_session(clinica_id=clinica_a.id),
                )

            alertas = db.query(AlertaInterno).all()
            self.assertEqual(len(alertas), 1)
            alerta = alertas[0]
            self.assertEqual(alerta.tipo, "agendamento_cancelado_portal")
            self.assertEqual(alerta.entidade_tipo, "agendamento")
            self.assertEqual(alerta.entidade_id, agendado_a.id)
            self.assertEqual(alerta.clinica_id, clinica_a.id)
            self.assertFalse(alerta.lido)
            self.assertIn(clinica_a.nome, alerta.titulo)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nao_cancela_agendamento_de_outra_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, agendado_a, *_ = self._seed(db)

            with patch.object(portal, "registrar_auditoria", return_value=None):
                with self.assertRaises(HTTPException) as ctx:
                    portal.cancelar_agendamento_clinica_portal(
                        agendado_a.id,
                        request=None,
                        db=db,
                        portal_session=_portal_session(clinica_id=clinica_b.id),
                    )
            self.assertEqual(ctx.exception.status_code, 404)

            db.refresh(agendado_a)
            self.assertEqual(agendado_a.status, "Agendado")
            self.assertEqual(db.query(AlertaInterno).count(), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_nao_cancela_agendamento_ja_realizado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, clinica_b, agendado_a, reservado_a, realizado_a, *_ = self._seed(db)

            with patch.object(portal, "registrar_auditoria", return_value=None):
                with self.assertRaises(HTTPException) as ctx:
                    portal.cancelar_agendamento_clinica_portal(
                        realizado_a.id,
                        request=None,
                        db=db,
                        portal_session=_portal_session(clinica_id=clinica_a.id),
                    )
            self.assertEqual(ctx.exception.status_code, 409)

            db.refresh(realizado_a)
            self.assertEqual(realizado_a.status, "Realizado")
            self.assertEqual(db.query(AlertaInterno).count(), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_agendamento_inexistente_retorna_404(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica_a, *_ = self._seed(db)
            with patch.object(portal, "registrar_auditoria", return_value=None):
                with self.assertRaises(HTTPException) as ctx:
                    portal.cancelar_agendamento_clinica_portal(
                        999999,
                        request=None,
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
