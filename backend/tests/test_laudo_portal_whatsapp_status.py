import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints import laudos
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_partner import PortalPartnerClinicLink, PortalPartnerProfile
from app.models.tutor import Tutor


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/laudos/1/portal/whatsapp",
        "raw_path": b"/api/v1/laudos/1/portal/whatsapp",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class LaudoPortalWhatsappStatusTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-whatsapp-status.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Laudo.__table__,
            Exame.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _build_laudo_liberado(self, db):
        tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
        db.add(tutor)
        db.flush()
        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
        clinica = Clinica(id=8, nome="Clinica Parceira", telefone="85999990001", ativo=True)
        db.add_all([paciente, clinica])
        db.flush()
        laudo = Laudo(
            paciente_id=paciente.id,
            veterinario_id=7,
            tipo="ecocardiograma",
            titulo="Laudo ecocardiografico - Luna",
            status=PORTAL_RELEASED_STATUS,
            clinic_id=clinica.id,
            data_exame=datetime(2026, 7, 4, 15, 30),
            criado_por_id=7,
            criado_por_nome="Dr. Martiniano",
        )
        db.add(laudo)
        db.flush()
        exame = Exame(
            laudo_id=laudo.id,
            paciente_id=paciente.id,
            tipo_exame="Ecocardiograma",
            status=PORTAL_RELEASED_STATUS,
        )
        db.add(exame)
        db.commit()
        db.refresh(laudo)
        return laudo

    def test_aviso_whatsapp_com_sucesso_persiste_status_enviado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)
            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            payload = laudos.PortalReportWhatsAppRequest(idempotency_key="idem-key-teste-001")

            with (
                patch.object(
                    laudos,
                    "send_approved_utility_template",
                    return_value={"message_id": "wamid.teste", "idempotent": False},
                ) as send_mock,
                patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
            ):
                result = laudos.avisar_laudo_liberado_por_whatsapp(
                    laudo.id,
                    payload,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            db.refresh(laudo)
            self.assertEqual(result["message_id"], "wamid.teste")
            self.assertEqual(laudo.whatsapp_liberacao_status, "enviado")
            self.assertIsNotNone(laudo.whatsapp_liberacao_em)
            self.assertIsNone(laudo.whatsapp_liberacao_erro)
            send_mock.assert_called_once()
            audit_mock.assert_called_once()
            self.assertEqual(audit_mock.call_args.kwargs["acao"], "LAUDO_PORTAL_WHATSAPP_ENVIADO")

            listagem = laudos.listar_laudos(db=db, current_user=current_user)
            item = next(i for i in listagem["items"] if i["id"] == laudo.id)
            self.assertEqual(item["whatsapp_liberacao_status"], "enviado")
            self.assertIsNone(item["whatsapp_liberacao_erro"])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_aviso_whatsapp_com_falha_persiste_status_falhou(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)
            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            payload = laudos.PortalReportWhatsAppRequest(idempotency_key="idem-key-teste-002")

            with (
                patch.object(
                    laudos,
                    "send_approved_utility_template",
                    side_effect=laudos.WhatsAppTemplateDeliveryError("Erro simulado da Graph API"),
                ) as send_mock,
                patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
            ):
                with self.assertRaises(HTTPException) as ctx:
                    laudos.avisar_laudo_liberado_por_whatsapp(
                        laudo.id,
                        payload,
                        request=_make_request(),
                        db=db,
                        current_user=current_user,
                    )

            self.assertEqual(ctx.exception.status_code, 502)
            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "falhou")
            self.assertIsNotNone(laudo.whatsapp_liberacao_em)
            self.assertEqual(laudo.whatsapp_liberacao_erro, "Erro simulado da Graph API")
            send_mock.assert_called_once()
            audit_mock.assert_called_once()
            self.assertEqual(audit_mock.call_args.kwargs["acao"], "LAUDO_PORTAL_WHATSAPP_FALHOU")

            listagem = laudos.listar_laudos(db=db, current_user=current_user)
            item = next(i for i in listagem["items"] if i["id"] == laudo.id)
            self.assertEqual(item["whatsapp_liberacao_status"], "falhou")
            self.assertEqual(item["whatsapp_liberacao_erro"], "Erro simulado da Graph API")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
