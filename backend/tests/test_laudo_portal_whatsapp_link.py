"""Aviso de laudo no WhatsApp da clinica carregando o link direto.

Cobre docs/specs/portal-clinica-link-laudo-whatsapp/ (CA-001 a CA-003).
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-exam-link-whatsapp-test-secret-1234567890")

from app.api.v1.endpoints import laudos
from app.core.config import settings
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.portal_partner import PortalPartnerClinicLink, PortalPartnerProfile
from app.models.tutor import Tutor
from app.services.portal_clinic_exam_link_service import derive_link_token


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


class LaudoPortalWhatsappLinkTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-whatsapp-link.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Laudo.__table__,
            Exame.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
            PortalClinicExamLink.__table__,
            PortalClinicTrustedDevice.__table__,
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

    def _enviar(self, db, laudo, idempotency_key: str, send_mock):
        current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
        payload = laudos.PortalReportWhatsAppRequest(idempotency_key=idempotency_key)
        with (
            patch.object(laudos, "send_approved_utility_template", send_mock),
            patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
        ):
            resultado = laudos.avisar_laudo_liberado_por_whatsapp(
                laudo.id,
                payload,
                request=_make_request(),
                db=db,
                current_user=current_user,
            )
        return resultado, audit_mock

    def test_flag_ligada_envia_modelo_com_link(self) -> None:
        """CA-001."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)
            send_mock = Mock(return_value={"message_id": "wamid.com-link", "idempotent": False})

            with patch.object(settings, "PORTAL_CLINIC_EXAM_LINK_ENABLED", True):
                resultado, audit_mock = self._enviar(db, laudo, "idem-link-001", send_mock)

            self.assertTrue(resultado["link_incluido"])
            self.assertEqual(resultado["template_key"], "portalReportLink")

            chamada = send_mock.call_args.kwargs
            self.assertEqual(chamada["template_key"], "portalReportLink")
            parametros = chamada["parameters"]
            self.assertEqual(len(parametros), 4)
            self.assertIn("/laudo/", parametros[3])

            link = db.query(PortalClinicExamLink).one()
            self.assertEqual(link.clinica_id, 8)
            self.assertEqual(link.status, "active")
            # A URL carrega o token derivado, nunca o nonce guardado em banco.
            self.assertTrue(
                parametros[3].endswith(derive_link_token(link.exame_id, link.token_nonce))
            )
            self.assertNotIn(link.token_nonce, parametros[3])

            # A URL nao pode aparecer na auditoria: e credencial de acesso.
            detalhes = audit_mock.call_args.kwargs["detalhes"]
            self.assertTrue(detalhes["link_incluido"])
            self.assertNotIn(parametros[3], str(detalhes))
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_flag_desligada_mantem_o_aviso_de_antes(self) -> None:
        """CA-002."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)
            send_mock = Mock(
                return_value={"message_id": "wamid.sem-link", "idempotent": False}
            )

            with patch.object(settings, "PORTAL_CLINIC_EXAM_LINK_ENABLED", False):
                resultado, _ = self._enviar(db, laudo, "idem-link-002", send_mock)

            self.assertFalse(resultado["link_incluido"])
            self.assertEqual(resultado["template_key"], "portalReportAvailable")
            chamada = send_mock.call_args.kwargs
            self.assertEqual(chamada["template_key"], "portalReportAvailable")
            self.assertEqual(len(chamada["parameters"]), 3)
            self.assertEqual(db.query(PortalClinicExamLink).count(), 0)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_modelo_com_link_indisponivel_degrada_para_o_aviso_sem_link(self) -> None:
        """CA-003: aprovacao pendente na Meta nao pode derrubar o aviso."""
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)

            def envio(*, template_key, **kwargs):
                if template_key == "portalReportLink":
                    raise laudos.WhatsAppTemplateDeliveryError("template nao aprovado")
                return {"message_id": "wamid.degradado", "idempotent": False}

            send_mock = Mock(side_effect=envio)

            with patch.object(settings, "PORTAL_CLINIC_EXAM_LINK_ENABLED", True):
                resultado, _ = self._enviar(db, laudo, "idem-link-003", send_mock)

            self.assertFalse(resultado["link_incluido"])
            self.assertEqual(resultado["template_key"], "portalReportAvailable")
            self.assertEqual(resultado["message_id"], "wamid.degradado")
            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "enviado")

            chaves = [c.kwargs["template_key"] for c in send_mock.call_args_list]
            self.assertEqual(chaves, ["portalReportLink", "portalReportAvailable"])
            # A degradacao precisa de chave de idempotencia propria: o servico do
            # WhatsApp recusa a mesma chave com conteudo diferente.
            idem = [c.kwargs["idempotency_key"] for c in send_mock.call_args_list]
            self.assertEqual(idem[0], "idem-link-003")
            self.assertNotEqual(idem[1], idem[0])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
