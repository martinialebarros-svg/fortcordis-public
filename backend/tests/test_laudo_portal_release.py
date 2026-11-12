import asyncio
import io
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
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints import laudos
from app.api.v1.endpoints import atendimento as atendimento_module
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.imagem_laudo import ImagemLaudo
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_clinic_auth import PortalClinicAccount, PortalClinicInvite
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
    PortalPartnerReleaseTarget,
)
from app.models.portal_partner_auth import PortalPartnerAccount
from app.models.tutor import Tutor


PDF_BYTES = b"%PDF-1.4\nportal laudo pdf\n"


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/laudos/1/portal/liberar-clinica",
        "raw_path": b"/api/v1/laudos/1/portal/liberar-clinica",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


def _make_upload_file(filename: str, content_type: str, content: bytes) -> UploadFile:
    headers = Headers({"content-type": content_type})
    return UploadFile(
        io.BytesIO(content),
        filename=filename,
        headers=headers,
        size=len(content),
    )


class LaudoPortalReleaseTest(unittest.TestCase):
    def test_parse_data_exame_preserves_calendar_date_in_operational_timezone(self) -> None:
        parsed = laudos._parse_data_exame("2026-07-25")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-07-25T00:00:00-03:00")

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-release.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            ImagemLaudo.__table__,
            AnexoAtendimento.__table__,
            PortalClinicInvite.__table__,
            PortalClinicAccount.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
            PortalPartnerReleaseTarget.__table__,
            PortalPartnerAccount.__table__,
            PortalClinicExamLink.__table__,
            PortalClinicTrustedDevice.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _fake_pdf(self):
        return SimpleNamespace(
            content=PDF_BYTES,
            filename="laudo-luna.pdf",
            cache_key="cache-key-test",
        )

    def _fake_store(self, tmpdir: tempfile.TemporaryDirectory):
        def _store(atendimento_id: int, filename: str, content: bytes, content_type: str):
            file_path = Path(tmpdir.name) / f"stored-{atendimento_id}-{filename}"
            file_path.write_bytes(content)
            return str(file_path), filename, content_type

        return _store

    def test_liberar_laudo_cria_exame_publicado_no_portal(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            db.add_all([paciente, clinica])
            db.flush()
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luna",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 4, 15, 30),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()) as render_mock,
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)) as store_mock,
                patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
                patch("app.services.portal_clinic_notification_service.send_portal_email_message") as email_mock,
            ):
                email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                response = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            db.refresh(laudo)
            exame = db.query(Exame).filter(Exame.laudo_id == laudo.id).first()
            anexo = db.query(AnexoAtendimento).filter(AnexoAtendimento.exame_id == exame.id).first()

            self.assertEqual(response["status"], PORTAL_RELEASED_STATUS)
            self.assertEqual(laudo.status, PORTAL_RELEASED_STATUS)
            self.assertIsNotNone(exame)
            self.assertIsNotNone(anexo)
            self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)
            self.assertEqual(exame.paciente_id, laudo.paciente_id)
            self.assertEqual(exame.tipo_exame, "Ecocardiograma")
            self.assertEqual(exame.categoria_exame, "Laudo")
            self.assertEqual(response["anexo_id"], anexo.id)
            self.assertEqual(anexo.nome_original, "laudo-luna.pdf")
            self.assertEqual(anexo.mime_type, "application/pdf")
            self.assertEqual(anexo.tamanho, len(PDF_BYTES))
            self.assertEqual(anexo.origem, laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN)
            self.assertEqual(anexo.url, f"/api/v1/portal/anexos/{anexo.id}/arquivo")
            self.assertTrue(Path(anexo.caminho_arquivo).exists())
            self.assertEqual(response["notificacao_clinica"]["status"], "sent")
            self.assertEqual(response["notificacao_clinica"]["destination_masked"], "co***@clinica.com")
            render_mock.assert_called_once()
            store_mock.assert_called_once()
            self.assertEqual(audit_mock.call_count, 2)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_upload_eletrocardiograma_pode_vincular_veterinario_parceiro_sem_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Bolt", especie="Canina", ativo=1)
            partner = PortalPartnerProfile(
                tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                nome_exibicao="Dra. Carla Soares",
                email_login="carla.soares@example.com",
                whatsapp="85999990002",
                cidade_base="Fortaleza",
                estado_base="CE",
                ativo=True,
            )
            db.add_all([paciente, partner])
            db.commit()
            db.refresh(paciente)
            db.refresh(partner)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            upload = _make_upload_file("eletro-bolt.pdf", "application/pdf", b"%PDF-1.4\neletro\n")
            with patch.object(
                laudos,
                "store_atendimento_attachment_file",
                side_effect=self._fake_store(tmpdir),
            ):
                response = asyncio.run(
                    laudos.criar_laudo_eletrocardiograma_por_pdf(
                        arquivo=upload,
                        agendamento_id=None,
                        atendimento_id=None,
                        paciente_id=paciente.id,
                        clinic_id=None,
                        veterinario_parceiro_id=partner.id,
                        data_exame="2026-07-30",
                        observacoes="Encaminhado para telemedicina.",
                        db=db,
                        current_user=current_user,
                    )
                )

            laudo = db.query(Laudo).filter(Laudo.id == response["id"]).first()
            self.assertIsNotNone(laudo)
            self.assertEqual(laudo.veterinario_parceiro_id, partner.id)
            self.assertIsNone(laudo.clinic_id)
            self.assertEqual(laudo.medico_solicitante, "Dra. Carla Soares")
            self.assertEqual(response["veterinario_parceiro_id"], partner.id)
            self.assertEqual(response["veterinario_parceiro_nome"], "Dra. Carla Soares")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_laudo_publica_tambem_para_veterinario_parceiro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            partner = PortalPartnerProfile(
                tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                nome_exibicao="Dra. Carla Soares",
                email_login="carla.soares@example.com",
                whatsapp="85999990002",
                cidade_base="Fortaleza",
                estado_base="CE",
                ativo=True,
            )
            db.add_all([paciente, clinica, partner])
            db.flush()
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luna",
                status="Finalizado",
                clinic_id=clinica.id,
                veterinario_parceiro_id=partner.id,
                data_exame=datetime(2026, 7, 30, 15, 30),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None),
                patch("app.services.portal_clinic_notification_service.send_portal_email_message") as clinic_email_mock,
                patch("app.services.portal_partner_notification_service.send_portal_email_message") as partner_email_mock,
            ):
                clinic_email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                partner_email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                response = laudos.liberar_laudo_para_portal(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            exame = db.query(Exame).filter(Exame.laudo_id == laudo.id).first()
            self.assertIsNotNone(exame)
            target = (
                db.query(PortalPartnerReleaseTarget)
                .filter(
                    PortalPartnerReleaseTarget.partner_id == partner.id,
                    PortalPartnerReleaseTarget.exame_id == exame.id,
                    PortalPartnerReleaseTarget.revoked_at.is_(None),
                )
                .first()
            )
            self.assertIsNotNone(target)
            self.assertEqual(response["destinos_liberados_agora"]["clinica"], True)
            self.assertEqual(response["destinos_liberados_agora"]["veterinario_parceiro"], True)
            self.assertEqual(response["portal_veterinario_liberado"], True)
            self.assertEqual(response["portal_destinos_pendentes"], [])
            self.assertEqual(response["notificacao_parceiro"]["status"], "sent")
            self.assertEqual(response["notificacao_parceiro"]["destination_masked"], "ca***@example.com")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_obter_laudo_indica_pendencia_de_veterinario_parceiro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Luna", especie="Canina", ativo=1)
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            partner = PortalPartnerProfile(
                tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                nome_exibicao="Dra. Carla Soares",
                email_login="carla.soares@example.com",
                ativo=True,
            )
            db.add_all([paciente, clinica, partner])
            db.flush()
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luna",
                status=PORTAL_RELEASED_STATUS,
                clinic_id=clinica.id,
                veterinario_parceiro_id=partner.id,
                data_exame=datetime(2026, 7, 30, 15, 30),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.flush()
            db.add(
                Exame(
                    laudo_id=laudo.id,
                    paciente_id=paciente.id,
                    tipo_exame="Ecocardiograma",
                    categoria_exame="Laudo",
                    status=PORTAL_RELEASED_STATUS,
                )
            )
            db.commit()
            payload = laudos.obter_laudo(
                laudo.id,
                db=db,
                current_user=SimpleNamespace(id=7, nome="Dr. Martiniano"),
            )
            self.assertEqual(payload["portal_clinica_liberado"], True)
            self.assertEqual(payload["portal_veterinario_liberado"], False)
            self.assertEqual(payload["portal_destinos_pendentes"], ["veterinario_parceiro"])
            self.assertEqual(payload["portal_pode_liberar"], True)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_laudo_reusa_anexo_pdf_existente(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            db.add(clinica)
            db.flush()
            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luna",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 4, 15, 30),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)) as store_mock,
                patch.object(laudos, "registrar_auditoria", return_value=None),
            ):
                first = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )
                second = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            self.assertEqual(first["anexo_id"], second["anexo_id"])
            self.assertEqual(db.query(AnexoAtendimento).count(), 1)
            store_mock.assert_called_once()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_eletrocardiograma_usa_pdf_externo_anexado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            pdf_path = Path(tmpdir.name) / "eletro-luke.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\neletro externo\n")
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            db.add(clinica)
            db.flush()

            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo=laudos.TIPO_LAUDO_ELETROCARDIOGRAMA,
                titulo="Laudo de Eletrocardiograma - Luke",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 5, 11, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.flush()

            anexo = AnexoAtendimento(
                atendimento_id=0,
                exame_id=None,
                tipo="documento",
                descricao="PDF do eletrocardiograma.",
                url="",
                nome_original="eletro-luke.pdf",
                tamanho=pdf_path.stat().st_size,
                mime_type="application/pdf",
                arquivo_hash="abc123",
                dedupe_key=f"laudo:{laudo.id}|sha256:abc123",
                caminho_arquivo=str(pdf_path),
                origem=laudos.ELETROCARDIOGRAMA_UPLOAD_ORIGIN,
            )
            db.add(anexo)
            db.flush()
            laudo.anexos = laudos._serializar_pdf_externo_laudo(
                laudo.anexos,
                {
                    "anexo_id": anexo.id,
                    "nome_original": anexo.nome_original,
                    "mime_type": anexo.mime_type,
                    "tamanho": anexo.tamanho,
                    "arquivo_hash": anexo.arquivo_hash,
                },
            )
            db.commit()
            db.refresh(laudo)
            db.refresh(anexo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()) as render_mock,
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)) as store_mock,
                patch.object(laudos, "registrar_auditoria", return_value=None),
            ):
                response = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            db.refresh(laudo)
            db.refresh(anexo)
            exame = db.query(Exame).filter(Exame.laudo_id == laudo.id).first()

            self.assertEqual(response["status"], PORTAL_RELEASED_STATUS)
            self.assertEqual(response["anexo_id"], anexo.id)
            self.assertEqual(laudo.status, PORTAL_RELEASED_STATUS)
            self.assertIsNotNone(exame)
            self.assertEqual(exame.tipo_exame, "Eletrocardiograma")
            self.assertEqual(anexo.exame_id, exame.id)
            self.assertEqual(anexo.origem, laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN)
            self.assertEqual(anexo.url, f"/api/v1/portal/anexos/{anexo.id}/arquivo")
            render_mock.assert_not_called()
            store_mock.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_laudo_sem_clinica_e_bloqueado(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo sem clinica",
                status="Finalizado",
                clinic_id=None,
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()) as render_mock:
                with self.assertRaises(HTTPException) as ctx:
                    laudos.liberar_laudo_para_portal_clinica(
                        laudo.id,
                        request=_make_request(),
                        db=db,
                        current_user=current_user,
                    )

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(db.query(Exame).count(), 0)
            self.assertEqual(db.query(AnexoAtendimento).count(), 0)
            render_mock.assert_not_called()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_laudo_envia_email_para_conta_ativa_da_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Luke", especie="Canina", tutor_id=tutor.id, ativo=1)
            clinica = Clinica(id=8, nome="La no Pet", email="contato@lanopet.com", ativo=True)
            account = PortalClinicAccount(
                clinica_id=8,
                email_normalized="portal@lanopet.com",
                responsavel_nome="Equipe La no Pet",
                password_hash="hash",
                status="active",
            )
            db.add_all([paciente, clinica, account])
            db.flush()

            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luke",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 21, 14, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None),
                patch("app.services.portal_clinic_notification_service.send_portal_email_message") as email_mock,
            ):
                email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                response = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            email_mock.assert_called_once()
            self.assertEqual(email_mock.call_args.kwargs["destination"], "portal@lanopet.com")
            self.assertEqual(response["notificacao_clinica"]["status"], "sent")
            self.assertEqual(response["notificacao_clinica"]["destination_masked"], "po***@lanopet.com")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_laudo_notifica_todos_os_gestores_ativos_da_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            paciente = Paciente(nome="Luke", especie="Canina", ativo=1)
            clinica = Clinica(id=8, nome="La no Pet", email="contato@lanopet.com", ativo=True)
            conta_ana = PortalClinicAccount(
                clinica_id=8,
                email_normalized="ana.diretora@lanopet.com",
                responsavel_nome="Ana Diretora",
                password_hash="hash",
                status="active",
            )
            conta_bruno = PortalClinicAccount(
                clinica_id=8,
                email_normalized="bruno.socio@lanopet.com",
                responsavel_nome="Bruno Socio",
                password_hash="hash",
                status="active",
            )
            db.add_all([paciente, clinica, conta_ana, conta_bruno])
            db.flush()

            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luke",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 21, 14, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None),
                patch("app.services.portal_clinic_notification_service.send_portal_email_message") as email_mock,
            ):
                email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                response = laudos.liberar_laudo_para_portal_clinica(
                    laudo.id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            self.assertEqual(email_mock.call_count, 2)
            destinos_notificados = {call.kwargs["destination"] for call in email_mock.call_args_list}
            self.assertEqual(destinos_notificados, {"ana.diretora@lanopet.com", "bruno.socio@lanopet.com"})
            self.assertEqual(response["notificacao_clinica"]["status"], "sent")
            destino_masked = response["notificacao_clinica"]["destination_masked"]
            self.assertIn("an***@lanopet.com", destino_masked)
            self.assertIn("br***@lanopet.com", destino_masked)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_substituir_pdf_eletrocardiograma_antes_da_liberacao_reaproveita_anexo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            old_pdf_path = Path(tmpdir.name) / "eletro-antigo.pdf"
            old_pdf_path.write_bytes(b"%PDF-1.4\neletro antigo\n")

            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo=laudos.TIPO_LAUDO_ELETROCARDIOGRAMA,
                titulo="Laudo de Eletrocardiograma - Luke",
                status="Finalizado",
                clinic_id=8,
                data_exame=datetime(2026, 7, 5, 11, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.flush()

            anexo = AnexoAtendimento(
                atendimento_id=0,
                exame_id=None,
                tipo="documento",
                descricao="PDF do eletrocardiograma.",
                url="",
                nome_original="eletro-antigo.pdf",
                tamanho=old_pdf_path.stat().st_size,
                mime_type="application/pdf",
                arquivo_hash="oldhash",
                dedupe_key=f"laudo:{laudo.id}|sha256:oldhash",
                caminho_arquivo=str(old_pdf_path),
                origem=laudos.ELETROCARDIOGRAMA_UPLOAD_ORIGIN,
            )
            db.add(anexo)
            db.flush()
            laudo.anexos = laudos._serializar_pdf_externo_laudo(
                laudo.anexos,
                {
                    "anexo_id": anexo.id,
                    "nome_original": anexo.nome_original,
                    "mime_type": anexo.mime_type,
                    "tamanho": anexo.tamanho,
                    "arquivo_hash": anexo.arquivo_hash,
                },
            )
            db.commit()
            db.refresh(laudo)
            db.refresh(anexo)

            arquivo = _make_upload_file(
                "eletro-correto.pdf",
                "application/pdf",
                b"%PDF-1.4\neletro correto\n",
            )
            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
            ):
                response = asyncio.run(
                    laudos.substituir_pdf_eletrocardiograma(
                        laudo.id,
                        request=_make_request(),
                        arquivo=arquivo,
                        db=db,
                        current_user=current_user,
                    )
                )

            db.refresh(laudo)
            db.refresh(anexo)

            self.assertEqual(response["laudo_id"], laudo.id)
            self.assertEqual(response["anexo_id"], anexo.id)
            self.assertFalse(response["liberado_no_portal"])
            self.assertEqual(anexo.origem, laudos.ELETROCARDIOGRAMA_UPLOAD_ORIGIN)
            self.assertEqual(anexo.exame_id, None)
            self.assertEqual(anexo.nome_original, "eletro-correto.pdf")
            self.assertEqual(anexo.url, f"/api/v1/atendimentos/anexos/{anexo.id}/arquivo")
            self.assertFalse(old_pdf_path.exists())
            self.assertIn("eletro-correto.pdf", anexo.caminho_arquivo)
            audit_mock.assert_called_once()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_substituir_pdf_eletrocardiograma_liberado_atualiza_portal(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            old_pdf_path = Path(tmpdir.name) / "eletro-portal-antigo.pdf"
            old_pdf_path.write_bytes(b"%PDF-1.4\neletro portal antigo\n")

            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo=laudos.TIPO_LAUDO_ELETROCARDIOGRAMA,
                titulo="Laudo de Eletrocardiograma - Luke",
                status=PORTAL_RELEASED_STATUS,
                clinic_id=8,
                data_exame=datetime(2026, 7, 5, 11, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.flush()

            exame = Exame(
                laudo_id=laudo.id,
                atendimento_id=55,
                paciente_id=laudo.paciente_id,
                tipo_exame="Eletrocardiograma",
                categoria_exame="Laudo",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                valor=0,
            )
            db.add(exame)
            db.flush()

            anexo = AnexoAtendimento(
                atendimento_id=55,
                exame_id=exame.id,
                tipo="documento",
                descricao="PDF do eletrocardiograma.",
                url="",
                nome_original="eletro-portal-antigo.pdf",
                tamanho=old_pdf_path.stat().st_size,
                mime_type="application/pdf",
                arquivo_hash="portaloldhash",
                dedupe_key=laudos.build_upload_dedupe_key(exame.id, "portaloldhash"),
                caminho_arquivo=str(old_pdf_path),
                origem=laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN,
            )
            db.add(anexo)
            db.flush()
            anexo.url = f"/api/v1/portal/anexos/{anexo.id}/arquivo"
            laudo.anexos = laudos._serializar_pdf_externo_laudo(
                laudo.anexos,
                {
                    "anexo_id": anexo.id,
                    "nome_original": anexo.nome_original,
                    "mime_type": anexo.mime_type,
                    "tamanho": anexo.tamanho,
                    "arquivo_hash": anexo.arquivo_hash,
                },
            )
            db.commit()
            db.refresh(laudo)
            db.refresh(exame)
            db.refresh(anexo)

            arquivo = _make_upload_file(
                "eletro-portal-correto.pdf",
                "application/pdf",
                b"%PDF-1.4\neletro portal correto\n",
            )
            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
            ):
                response = asyncio.run(
                    laudos.substituir_pdf_eletrocardiograma(
                        laudo.id,
                        request=_make_request(),
                        arquivo=arquivo,
                        db=db,
                        current_user=current_user,
                    )
                )

            db.refresh(laudo)
            db.refresh(exame)
            db.refresh(anexo)

            self.assertEqual(response["laudo_id"], laudo.id)
            self.assertEqual(response["anexo_id"], anexo.id)
            self.assertTrue(response["liberado_no_portal"])
            self.assertEqual(response["exame_id"], exame.id)
            self.assertEqual(anexo.origem, laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN)
            self.assertEqual(anexo.exame_id, exame.id)
            self.assertEqual(anexo.atendimento_id, 55)
            self.assertEqual(anexo.nome_original, "eletro-portal-correto.pdf")
            self.assertEqual(anexo.url, f"/api/v1/portal/anexos/{anexo.id}/arquivo")
            self.assertEqual(anexo.dedupe_key, laudos.build_upload_dedupe_key(exame.id, anexo.arquivo_hash))
            self.assertFalse(old_pdf_path.exists())
            self.assertIn("eletro-portal-correto.pdf", anexo.caminho_arquivo)
            audit_mock.assert_called_once()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_atualizar_laudo_liberado_atualiza_pdf_publicado_no_portal(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            old_pdf_path = Path(tmpdir.name) / "eco-portal-antigo.pdf"
            old_pdf_path.write_bytes(b"%PDF-1.4\neco portal antigo\n")

            laudo = Laudo(
                paciente_id=182,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luke",
                descricao="Descricao antiga",
                diagnostico="Diagnostico antigo",
                status=PORTAL_RELEASED_STATUS,
                clinic_id=8,
                data_exame=datetime(2026, 7, 5, 11, 0),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.flush()

            exame = Exame(
                laudo_id=laudo.id,
                atendimento_id=55,
                paciente_id=laudo.paciente_id,
                tipo_exame="Ecocardiograma",
                categoria_exame="Laudo",
                prioridade="Rotina",
                status=PORTAL_RELEASED_STATUS,
                valor=0,
                data_solicitacao=datetime(2026, 7, 5, 11, 0),
                data_resultado=datetime(2026, 7, 6, 13, 30),
            )
            db.add(exame)
            db.flush()

            anexo = AnexoAtendimento(
                atendimento_id=55,
                exame_id=exame.id,
                tipo="documento",
                descricao=laudos.PORTAL_LAUDO_ATTACHMENT_DESCRIPTION,
                url="",
                nome_original="eco-portal-antigo.pdf",
                tamanho=old_pdf_path.stat().st_size,
                mime_type="application/pdf",
                arquivo_hash="ecoportaloldhash",
                dedupe_key=laudos.build_upload_dedupe_key(exame.id, "ecoportaloldhash"),
                caminho_arquivo=str(old_pdf_path),
                origem=laudos.PORTAL_LAUDO_ATTACHMENT_ORIGIN,
            )
            db.add(anexo)
            db.flush()
            anexo.url = f"/api/v1/portal/anexos/{anexo.id}/arquivo"
            anexo_id_original = anexo.id
            db.commit()
            db.refresh(laudo)
            db.refresh(exame)
            db.refresh(anexo)

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            novo_pdf = SimpleNamespace(
                content=b"%PDF-1.4\neco portal corrigido\n",
                filename="eco-portal-corrigido.pdf",
                cache_key="cache-key-corrigido",
            )
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=novo_pdf) as render_mock,
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
            ):
                response = laudos.atualizar_laudo(
                    laudo.id,
                    {"diagnostico": "Diagnostico corrigido"},
                    db=db,
                    current_user=current_user,
                )

            db.refresh(laudo)
            db.refresh(exame)
            db.refresh(anexo)

            self.assertEqual(response.id, laudo.id)
            self.assertEqual(laudo.diagnostico, "Diagnostico corrigido")
            self.assertEqual(laudo.status, PORTAL_RELEASED_STATUS)
            self.assertEqual(exame.id, anexo.exame_id)
            self.assertEqual(exame.data_resultado, datetime(2026, 7, 6, 13, 30))
            self.assertEqual(anexo.id, anexo_id_original)
            self.assertEqual(db.query(AnexoAtendimento).count(), 1)
            self.assertEqual(anexo.nome_original, "eco-portal-corrigido.pdf")
            self.assertEqual(anexo.url, f"/api/v1/portal/anexos/{anexo.id}/arquivo")
            self.assertIn("eco-portal-corrigido.pdf", anexo.caminho_arquivo)
            self.assertFalse(old_pdf_path.exists())
            render_mock.assert_called_once()
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_deletar_laudo_revoga_liberacao_do_exame_no_portal(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
            db.add(tutor)
            db.flush()
            paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
            clinica = Clinica(id=8, nome="Clinica Parceira", email="contato@clinica.com", ativo=True)
            db.add_all([paciente, clinica])
            db.flush()
            laudo = Laudo(
                paciente_id=paciente.id,
                veterinario_id=7,
                tipo="ecocardiograma",
                titulo="Laudo ecocardiografico - Luna",
                status="Finalizado",
                clinic_id=clinica.id,
                data_exame=datetime(2026, 7, 4, 15, 30),
                criado_por_id=7,
                criado_por_nome="Dr. Martiniano",
            )
            db.add(laudo)
            db.commit()
            db.refresh(laudo)
            laudo_id = laudo.id

            current_user = SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")
            with (
                patch.object(laudos, "render_laudo_pdf", return_value=self._fake_pdf()),
                patch.object(laudos, "store_atendimento_attachment_file", side_effect=self._fake_store(tmpdir)),
                patch.object(laudos, "registrar_auditoria", return_value=None),
                patch("app.services.portal_clinic_notification_service.send_portal_email_message") as email_mock,
            ):
                email_mock.return_value = SimpleNamespace(provider="smtp", channel="email")
                laudos.liberar_laudo_para_portal_clinica(
                    laudo_id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            exame = db.query(Exame).filter(Exame.laudo_id == laudo_id).first()
            self.assertIsNotNone(exame)
            self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)
            exame_id = exame.id
            anexo = db.query(AnexoAtendimento).filter(AnexoAtendimento.exame_id == exame_id).first()
            self.assertIsNotNone(anexo)

            with patch.object(atendimento_module, "registrar_auditoria", return_value=None):
                resposta = laudos.deletar_laudo(
                    laudo_id,
                    request=_make_request(),
                    db=db,
                    current_user=current_user,
                )

            self.assertEqual(resposta["message"], "Laudo e imagens removidos com sucesso")
            self.assertIsNone(db.query(Laudo).filter(Laudo.id == laudo_id).first())

            db.refresh(exame)
            self.assertIsNone(exame.laudo_id)
            self.assertNotEqual(exame.status, PORTAL_RELEASED_STATUS)
            # O anexo publicado nao e apagado (o download deixa de ser
            # oferecido pelo portal porque o exame nao aparece mais como
            # liberado, nao porque o arquivo sumiu).
            self.assertIsNotNone(db.query(AnexoAtendimento).filter(AnexoAtendimento.id == anexo.id).first())
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
