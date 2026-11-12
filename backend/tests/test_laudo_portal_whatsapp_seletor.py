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

CLINICA_WHATSAPP = "5585999990001"
NOMEADO_WHATSAPP = "5585988880002"
VINCULO_WHATSAPP = "5585977770003"
CHAVE_NOMEADO = "veterinario:4"
CHAVE_VINCULO = "veterinario:5"


def _load_migration():
    from importlib import util

    module_path = BACKEND_DIR / "migrations" / "versions" / "20260917_86_laudo_whatsapp_envios.py"
    spec = util.spec_from_file_location("laudo_whatsapp_envios_migration", module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class LaudoPortalWhatsappSeletorTest(unittest.TestCase):
    """O seletor de destino: quem foi escolhido recebe, quem nao ficou de fora."""

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-whatsapp-seletor.db"
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

    def _build_laudo(self, db) -> Laudo:
        """Laudo liberado para a clinica, o veterinario nomeado e um por vinculo."""
        tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
        db.add(tutor)
        db.flush()
        db.add(Paciente(id=1, nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1))
        db.add(Clinica(id=8, nome="Clinica Parceira", telefone=CLINICA_WHATSAPP, ativo=True))
        db.add_all(
            [
                PortalPartnerProfile(
                    id=4,
                    tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                    nome_exibicao="Dra Isadora Bastos",
                    whatsapp=NOMEADO_WHATSAPP,
                    ativo=True,
                ),
                PortalPartnerProfile(
                    id=5,
                    tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                    nome_exibicao="Dra Camila Reboucas",
                    whatsapp=VINCULO_WHATSAPP,
                    ativo=True,
                ),
            ]
        )
        db.flush()
        db.add(PortalPartnerClinicLink(partner_id=5, clinica_id=8, receber_todos_laudos=True))
        laudo = Laudo(
            paciente_id=1,
            veterinario_id=7,
            tipo="ecocardiograma",
            titulo="Laudo ecocardiografico - Luna",
            status=PORTAL_RELEASED_STATUS,
            clinic_id=8,
            veterinario_parceiro_id=4,
            data_exame=datetime(2026, 7, 4, 15, 30),
            criado_por_id=7,
            criado_por_nome="Dr. Martiniano",
        )
        db.add(laudo)
        db.flush()
        exame = Exame(
            laudo_id=laudo.id,
            paciente_id=1,
            tipo_exame="Ecocardiograma",
            status=PORTAL_RELEASED_STATUS,
        )
        db.add(exame)
        db.flush()
        for partner_id in (4, 5):
            db.add(
                PortalPartnerReleaseTarget(
                    partner_id=partner_id,
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

    def _chamar(self, db, laudo, *, idempotency_key: str, destinos=None):
        payload = laudos.PortalReportWhatsAppRequest(
            idempotency_key=idempotency_key,
            **({"destinos": destinos} if destinos is not None else {}),
        )
        with (
            patch.object(
                laudos,
                "send_approved_utility_template",
                side_effect=lambda **kwargs: {
                    "message_id": f"wamid.{kwargs['destination']}",
                    "idempotent": False,
                },
            ) as send_mock,
            patch.object(laudos, "registrar_auditoria", return_value=None),
        ):
            resposta = laudos.avisar_laudo_liberado_por_whatsapp(
                laudo.id,
                payload,
                request=_make_request(),
                db=db,
                current_user=self._current_user(),
            )
        return resposta, send_mock

    def test_envia_so_para_o_veterinario_escolhido(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            resposta, send_mock = self._chamar(
                db, laudo, idempotency_key="idem-seletor-001", destinos=[CHAVE_VINCULO]
            )

            destinos_chamados = [call.kwargs["destination"] for call in send_mock.call_args_list]
            self.assertEqual(destinos_chamados, [VINCULO_WHATSAPP])
            self.assertEqual(
                resposta["clinica"], {"status": "ignorado", "motivo": "nao_selecionado"}
            )
            por_id = {item["partner_id"]: item for item in resposta["veterinarios_parceiros"]}
            self.assertEqual(por_id[4]["motivo"], "nao_selecionado")
            self.assertEqual(por_id[5]["status"], "enviado")

            db.refresh(laudo)
            self.assertIsNone(laudo.whatsapp_liberacao_status)
            self.assertEqual(laudo.whatsapp_envios[CHAVE_VINCULO]["status"], "enviado")
            self.assertNotIn(laudos.DESTINO_AVISO_CLINICA, laudo.whatsapp_envios)
            self.assertNotIn(CHAVE_NOMEADO, laudo.whatsapp_envios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_envia_so_para_a_clinica_quando_e_a_unica_escolhida(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            resposta, send_mock = self._chamar(
                db, laudo, idempotency_key="idem-seletor-002", destinos=[laudos.DESTINO_AVISO_CLINICA]
            )

            destinos_chamados = [call.kwargs["destination"] for call in send_mock.call_args_list]
            self.assertEqual(destinos_chamados, [CLINICA_WHATSAPP])
            self.assertEqual(resposta["clinica"]["status"], "enviado")
            self.assertTrue(
                all(item["motivo"] == "nao_selecionado" for item in resposta["veterinarios_parceiros"])
            )

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_envios["clinica"]["status"], "enviado")
            self.assertIsNone(laudo.whatsapp_parceiro_status)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_sem_o_campo_destinos_avisa_todo_mundo(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            _, send_mock = self._chamar(db, laudo, idempotency_key="idem-seletor-003")

            destinos_chamados = sorted(call.kwargs["destination"] for call in send_mock.call_args_list)
            self.assertEqual(
                destinos_chamados, sorted([CLINICA_WHATSAPP, NOMEADO_WHATSAPP, VINCULO_WHATSAPP])
            )

            db.refresh(laudo)
            self.assertEqual(
                sorted(laudo.whatsapp_envios), sorted(["clinica", CHAVE_NOMEADO, CHAVE_VINCULO])
            )
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_lista_vazia_de_destinos_responde_422(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            with self.assertRaises(HTTPException) as ctx:
                self._chamar(db, laudo, idempotency_key="idem-seletor-004", destinos=[])

            self.assertEqual(ctx.exception.status_code, 422)
            db.refresh(laudo)
            self.assertIsNone(laudo.whatsapp_envios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_destino_nao_elegivel_responde_422_nomeando_a_chave(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            with self.assertRaises(HTTPException) as ctx:
                self._chamar(
                    db,
                    laudo,
                    idempotency_key="idem-seletor-005",
                    destinos=["veterinario:999"],
                )

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("veterinario:999", ctx.exception.detail)
            db.refresh(laudo)
            self.assertIsNone(laudo.whatsapp_envios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_destino_escolhido_sem_numero_nao_derruba_o_envio_dos_outros(self) -> None:
        """Clinica liberada mas sem WhatsApp cadastrado: o veterinario recebe assim mesmo.

        A tela lista quem esta liberado no portal sem saber dos numeros. Recusar
        a chamada inteira por causa de um cadastro incompleto deixaria o envio
        travado para todo mundo.
        """
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)
            clinica = db.query(Clinica).filter(Clinica.id == 8).first()
            clinica.telefone = None
            clinica.whatsapps = []
            db.commit()

            resposta, send_mock = self._chamar(
                db,
                laudo,
                idempotency_key="idem-seletor-008",
                destinos=[laudos.DESTINO_AVISO_CLINICA, CHAVE_NOMEADO],
            )

            destinos_chamados = [call.kwargs["destination"] for call in send_mock.call_args_list]
            self.assertEqual(destinos_chamados, [NOMEADO_WHATSAPP])
            self.assertEqual(resposta["clinica"], {"status": "ignorado", "motivo": "sem_whatsapp"})

            db.refresh(laudo)
            self.assertEqual(laudo.whatsapp_envios[CHAVE_NOMEADO]["status"], "enviado")
            self.assertNotIn(laudos.DESTINO_AVISO_CLINICA, laudo.whatsapp_envios)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_envio_novo_preserva_o_resultado_dos_destinos_nao_escolhidos(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            self._chamar(
                db, laudo, idempotency_key="idem-seletor-006", destinos=[laudos.DESTINO_AVISO_CLINICA]
            )
            db.refresh(laudo)
            enviado_clinica_em = laudo.whatsapp_envios["clinica"]["em"]

            self._chamar(db, laudo, idempotency_key="idem-seletor-007", destinos=[CHAVE_NOMEADO])
            db.refresh(laudo)

            self.assertEqual(laudo.whatsapp_envios["clinica"]["em"], enviado_clinica_em)
            self.assertEqual(laudo.whatsapp_envios[CHAVE_NOMEADO]["status"], "enviado")

            listagem = laudos.listar_laudos(db=db, current_user=self._current_user())
            item = next(i for i in listagem["items"] if i["id"] == laudo.id)
            self.assertEqual(item["whatsapp_envios"]["clinica"]["status"], "enviado")
            self.assertEqual(item["whatsapp_envios"][CHAVE_NOMEADO]["status"], "enviado")
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_migracao_do_mapa_de_envios_e_idempotente(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        try:
            migration = _load_migration()
            engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'migracao.db'}")
            with engine.begin() as connection:
                connection.execute(
                    text("CREATE TABLE laudos (id INTEGER PRIMARY KEY, whatsapp_liberacao_status VARCHAR(20))")
                )
                migration.upgrade(connection, "sqlite")
                migration.upgrade(connection, "sqlite")
                colunas = {column["name"] for column in inspect(connection).get_columns("laudos")}

            self.assertIn("whatsapp_envios", colunas)
            self.assertIn("whatsapp_liberacao_status", colunas)
            engine.dispose()
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
