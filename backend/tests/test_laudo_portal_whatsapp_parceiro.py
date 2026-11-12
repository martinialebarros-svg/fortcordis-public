import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
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
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
    PortalPartnerReleaseTarget,
)
from app.models.tutor import Tutor


def _load_migration():
    from importlib import util

    module_path = BACKEND_DIR / "migrations" / "versions" / "20260916_85_laudo_whatsapp_parceiro_status.py"
    spec = util.spec_from_file_location("laudo_whatsapp_parceiro_status_migration", module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CLINICA_WHATSAPP = "5585999990001"
PARCEIRO_WHATSAPP = "5585988880002"


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


class LaudoPortalWhatsappParceiroTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-whatsapp-parceiro.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            Laudo.__table__,
            Exame.__table__,
            PortalPartnerProfile.__table__,
            PortalPartnerClinicLink.__table__,
            PortalPartnerReleaseTarget.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _build_laudo_liberado(
        self,
        db,
        *,
        com_clinica: bool = True,
        com_parceiro: bool = True,
        parceiro_whatsapp: str | None = PARCEIRO_WHATSAPP,
        parceiro_liberado: bool = True,
    ) -> Laudo:
        tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
        db.add(tutor)
        db.flush()
        paciente = Paciente(nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1)
        db.add(paciente)
        if com_clinica:
            db.add(Clinica(id=8, nome="Clinica Parceira", telefone=CLINICA_WHATSAPP, ativo=True))
        if com_parceiro:
            db.add(
                PortalPartnerProfile(
                    id=4,
                    tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                    nome_exibicao="Dra Isadora Bastos",
                    whatsapp=parceiro_whatsapp,
                    ativo=True,
                )
            )
        db.flush()
        laudo = Laudo(
            paciente_id=paciente.id,
            veterinario_id=7,
            tipo="ecocardiograma",
            titulo="Laudo ecocardiografico - Luna",
            status=PORTAL_RELEASED_STATUS,
            clinic_id=8 if com_clinica else None,
            veterinario_parceiro_id=4 if com_parceiro else None,
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
        db.flush()
        if com_parceiro and parceiro_liberado:
            db.add(
                PortalPartnerReleaseTarget(
                    partner_id=4,
                    exame_id=exame.id,
                    laudo_id=laudo.id,
                    permitir_download=True,
                    released_at=datetime(2026, 7, 4, 16, 0),
                    created_by_user_id=7,
                    contexto_json="{}",
                )
            )
        db.commit()
        db.refresh(laudo)
        return laudo

    @staticmethod
    def _current_user():
        return SimpleNamespace(id=7, nome="Dr. Martiniano", email="vet@example.com")

    @staticmethod
    def _envio_ok(destino_com_falha: str | None = None):
        def _send(**kwargs):
            if destino_com_falha and kwargs["destination"] == destino_com_falha:
                raise laudos.WhatsAppTemplateDeliveryError("Erro simulado da Graph API")
            return {"message_id": f"wamid.{kwargs['destination']}", "idempotent": False}

        return _send

    def _chamar(self, db, laudo, *, idempotency_key: str, destino_com_falha: str | None = None):
        payload = laudos.PortalReportWhatsAppRequest(idempotency_key=idempotency_key)
        with (
            patch.object(
                laudos,
                "send_approved_utility_template",
                side_effect=self._envio_ok(destino_com_falha),
            ) as send_mock,
            patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock,
        ):
            resposta = laudos.avisar_laudo_liberado_por_whatsapp(
                laudo.id,
                payload,
                request=_make_request(),
                db=db,
                current_user=self._current_user(),
            )
        return resposta, send_mock, audit_mock

    def test_aviso_vai_para_clinica_e_para_parceiro_liberados(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)

            resposta, send_mock, audit_mock = self._chamar(db, laudo, idempotency_key="idem-parceiro-001")

            self.assertEqual(send_mock.call_count, 2)
            envio_clinica, envio_parceiro = (call.kwargs for call in send_mock.call_args_list)

            self.assertEqual(envio_clinica["destination"], CLINICA_WHATSAPP)
            self.assertEqual(envio_clinica["parameters"][0], "Clinica Parceira")
            self.assertEqual(envio_clinica["idempotency_key"], "idem-parceiro-001")

            self.assertEqual(envio_parceiro["destination"], PARCEIRO_WHATSAPP)
            self.assertEqual(envio_parceiro["parameters"][0], "Dra Isadora Bastos")
            self.assertEqual(envio_parceiro["idempotency_key"], "idem-parceiro-001-vet")
            self.assertLessEqual(len(envio_parceiro["idempotency_key"]), 128)
            self.assertEqual(envio_clinica["parameters"][1:], envio_parceiro["parameters"][1:])

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "enviado")
            self.assertEqual(laudo.whatsapp_parceiro_status, "enviado")
            self.assertIsNotNone(laudo.whatsapp_parceiro_em)
            self.assertIsNone(laudo.whatsapp_parceiro_erro)

            self.assertEqual(resposta["clinica"]["status"], "enviado")
            self.assertEqual(resposta["veterinario_parceiro"]["status"], "enviado")
            self.assertIn("veterinario parceiro", resposta["message"])

            acoes = [call.kwargs["acao"] for call in audit_mock.call_args_list]
            self.assertEqual(
                acoes,
                ["LAUDO_PORTAL_WHATSAPP_ENVIADO", "LAUDO_PORTAL_WHATSAPP_PARCEIRO_ENVIADO"],
            )

            listagem = laudos.listar_laudos(db=db, current_user=self._current_user())
            item = next(i for i in listagem["items"] if i["id"] == laudo.id)
            self.assertEqual(item["whatsapp_parceiro_status"], "enviado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_sem_clinica_avisa_somente_o_parceiro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db, com_clinica=False)

            resposta, send_mock, _ = self._chamar(db, laudo, idempotency_key="idem-parceiro-002")

            self.assertEqual(send_mock.call_count, 1)
            self.assertEqual(send_mock.call_args.kwargs["destination"], PARCEIRO_WHATSAPP)
            self.assertEqual(resposta["clinica"], {"status": "ignorado", "motivo": "sem_vinculo"})
            self.assertEqual(resposta["veterinario_parceiro"]["status"], "enviado")

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_parceiro_status, "enviado")
            self.assertIsNone(laudo.whatsapp_liberacao_status)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_parceiro_sem_liberacao_no_portal_nao_recebe_aviso(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db, parceiro_liberado=False)

            resposta, send_mock, _ = self._chamar(db, laudo, idempotency_key="idem-parceiro-003")

            self.assertEqual(send_mock.call_count, 1)
            self.assertEqual(send_mock.call_args.kwargs["destination"], CLINICA_WHATSAPP)
            self.assertEqual(
                resposta["veterinario_parceiro"],
                {"status": "ignorado", "motivo": "nao_liberado"},
            )

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "enviado")
            self.assertIsNone(laudo.whatsapp_parceiro_status)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_parceiro_sem_whatsapp_cadastrado_nao_bloqueia_a_clinica(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db, parceiro_whatsapp=None)

            resposta, send_mock, _ = self._chamar(db, laudo, idempotency_key="idem-parceiro-004")

            self.assertEqual(send_mock.call_count, 1)
            self.assertEqual(send_mock.call_args.kwargs["destination"], CLINICA_WHATSAPP)
            self.assertEqual(
                resposta["veterinario_parceiro"],
                {"status": "ignorado", "motivo": "sem_whatsapp"},
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_falha_no_parceiro_mantem_200_e_persiste_o_erro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)

            resposta, send_mock, audit_mock = self._chamar(
                db,
                laudo,
                idempotency_key="idem-parceiro-005",
                destino_com_falha=PARCEIRO_WHATSAPP,
            )

            self.assertEqual(send_mock.call_count, 2)
            self.assertEqual(resposta["clinica"]["status"], "enviado")
            self.assertEqual(resposta["veterinario_parceiro"]["status"], "falhou")
            self.assertEqual(
                resposta["veterinario_parceiro"]["erro"], "Erro simulado da Graph API"
            )
            self.assertIn("falhou", resposta["message"])

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "enviado")
            self.assertEqual(laudo.whatsapp_parceiro_status, "falhou")
            self.assertEqual(laudo.whatsapp_parceiro_erro, "Erro simulado da Graph API")

            acoes = [call.kwargs["acao"] for call in audit_mock.call_args_list]
            self.assertIn("LAUDO_PORTAL_WHATSAPP_PARCEIRO_FALHOU", acoes)

            listagem = laudos.listar_laudos(db=db, current_user=self._current_user())
            item = next(i for i in listagem["items"] if i["id"] == laudo.id)
            self.assertEqual(item["whatsapp_parceiro_status"], "falhou")
            self.assertEqual(item["whatsapp_parceiro_erro"], "Erro simulado da Graph API")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_falha_na_clinica_continua_502_sem_perder_o_envio_do_parceiro(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db)

            with self.assertRaises(HTTPException) as ctx:
                self._chamar(
                    db,
                    laudo,
                    idempotency_key="idem-parceiro-006",
                    destino_com_falha=CLINICA_WHATSAPP,
                )

            self.assertEqual(ctx.exception.status_code, 502)
            self.assertEqual(ctx.exception.detail, "Erro simulado da Graph API")

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_liberacao_status, "falhou")
            self.assertEqual(laudo.whatsapp_parceiro_status, "enviado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_sem_destino_com_whatsapp_responde_409(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo_liberado(db, com_clinica=False, parceiro_whatsapp=None)

            with self.assertRaises(HTTPException) as ctx:
                self._chamar(db, laudo, idempotency_key="idem-parceiro-007")

            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_migracao_do_status_do_parceiro_e_idempotente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        try:
            migration = _load_migration()
            engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'migracao.db'}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE laudos (id INTEGER PRIMARY KEY)"))
                migration.upgrade(connection, "sqlite")
                migration.upgrade(connection, "sqlite")
                colunas = {column["name"] for column in inspect(connection).get_columns("laudos")}

            self.assertIn("whatsapp_parceiro_status", colunas)
            self.assertIn("whatsapp_parceiro_em", colunas)
            self.assertIn("whatsapp_parceiro_erro", colunas)
            engine.dispose()
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
