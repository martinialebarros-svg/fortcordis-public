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
from app.models.portal_partner import (
    PORTAL_PARTNER_TYPE_VETERINARIO,
    PortalPartnerClinicLink,
    PortalPartnerProfile,
    PortalPartnerReleaseTarget,
)
from app.models.tutor import Tutor

PARTNER_NOMEADO = 4
PARTNER_VINCULO = 5


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/laudos/1/portal/veterinarios/4/revogar",
        "raw_path": b"/api/v1/laudos/1/portal/veterinarios/4/revogar",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class LaudoPortalRevogarParceiroTest(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "laudo-portal-revogar-parceiro.db"
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

    def _build_laudo(self, db, *, com_exame: bool = True, liberar_parceiros: bool = True) -> Laudo:
        tutor = Tutor(nome="Monica", email="monica@example.com", ativo=1)
        db.add(tutor)
        db.flush()
        db.add(Paciente(id=1, nome="Luna", especie="Canina", tutor_id=tutor.id, ativo=1))
        db.add(Clinica(id=8, nome="Clinica Parceira", telefone="5585999990001", ativo=True))
        db.add_all(
            [
                PortalPartnerProfile(
                    id=PARTNER_NOMEADO,
                    tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                    nome_exibicao="Dra Isadora Bastos",
                    whatsapp="5585988880002",
                    ativo=True,
                ),
                PortalPartnerProfile(
                    id=PARTNER_VINCULO,
                    tipo=PORTAL_PARTNER_TYPE_VETERINARIO,
                    nome_exibicao="Dra Camila Reboucas",
                    whatsapp="5585977770003",
                    ativo=True,
                ),
            ]
        )
        db.flush()
        db.add(PortalPartnerClinicLink(partner_id=PARTNER_VINCULO, clinica_id=8, receber_todos_laudos=True))
        laudo = Laudo(
            paciente_id=1,
            veterinario_id=7,
            tipo="ecocardiograma",
            titulo="Laudo ecocardiografico - Luna",
            status=PORTAL_RELEASED_STATUS,
            clinic_id=8,
            veterinario_parceiro_id=PARTNER_NOMEADO,
            data_exame=datetime(2026, 7, 4, 15, 30),
            criado_por_id=7,
            criado_por_nome="Dr. Martiniano",
        )
        db.add(laudo)
        db.flush()
        if com_exame:
            exame = Exame(
                laudo_id=laudo.id,
                paciente_id=1,
                tipo_exame="Ecocardiograma",
                status=PORTAL_RELEASED_STATUS,
            )
            db.add(exame)
            db.flush()
            if liberar_parceiros:
                for partner_id in (PARTNER_NOMEADO, PARTNER_VINCULO):
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

    def _revogar(self, db, laudo_id: int, partner_id: int):
        with patch.object(laudos, "registrar_auditoria", return_value=None) as audit_mock:
            resposta = laudos.revogar_liberacao_veterinario_no_portal(
                laudo_id,
                partner_id,
                request=_make_request(),
                db=db,
                current_user=self._current_user(),
            )
        return resposta, audit_mock

    def _target(self, db, laudo, partner_id):
        exame = db.query(Exame).filter(Exame.laudo_id == laudo.id).order_by(Exame.id.desc()).first()
        return (
            db.query(PortalPartnerReleaseTarget)
            .filter(
                PortalPartnerReleaseTarget.partner_id == partner_id,
                PortalPartnerReleaseTarget.exame_id == exame.id,
            )
            .first()
        )

    def test_revoga_o_acesso_do_parceiro_sem_tocar_no_resto(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)

            resposta, audit_mock = self._revogar(db, laudo.id, PARTNER_NOMEADO)

            self.assertIsNotNone(self._target(db, laudo, PARTNER_NOMEADO).revoked_at)
            self.assertIsNone(self._target(db, laudo, PARTNER_VINCULO).revoked_at)

            por_id = {item["partner_id"]: item for item in resposta["portal_veterinarios_destinos"]}
            self.assertFalse(por_id[PARTNER_NOMEADO]["liberado"])
            self.assertTrue(por_id[PARTNER_VINCULO]["liberado"])
            self.assertIn("veterinario_parceiro", resposta["portal_destinos_pendentes"])

            db.refresh(laudo)
            self.assertEqual(laudo.status, PORTAL_RELEASED_STATUS)
            self.assertTrue(resposta["portal_clinica_liberado"])

            self.assertEqual(audit_mock.call_args.kwargs["acao"], "LAUDO_PORTAL_PARCEIRO_REVOGADO")
            detalhes = audit_mock.call_args.kwargs["detalhes"]
            self.assertEqual(detalhes["partner_id"], PARTNER_NOMEADO)
            self.assertEqual(detalhes["laudo_id"], laudo.id)
            self.assertIn("exame_id", detalhes)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_revogar_duas_vezes_responde_409(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)
            self._revogar(db, laudo.id, PARTNER_NOMEADO)

            with self.assertRaises(HTTPException) as ctx:
                self._revogar(db, laudo.id, PARTNER_NOMEADO)

            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_parceiro_sem_liberacao_responde_409(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db, liberar_parceiros=False)

            with self.assertRaises(HTTPException) as ctx:
                self._revogar(db, laudo.id, PARTNER_NOMEADO)

            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_laudo_inexistente_responde_404_e_sem_exame_responde_409(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            with self.assertRaises(HTTPException) as ctx:
                self._revogar(db, 9999, PARTNER_NOMEADO)
            self.assertEqual(ctx.exception.status_code, 404)

            laudo = self._build_laudo(db, com_exame=False)
            with self.assertRaises(HTTPException) as ctx:
                self._revogar(db, laudo.id, PARTNER_NOMEADO)
            self.assertEqual(ctx.exception.status_code, 409)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_liberar_de_novo_reativa_a_mesma_linha(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)
            self._revogar(db, laudo.id, PARTNER_NOMEADO)
            target_antes = self._target(db, laudo, PARTNER_NOMEADO)
            target_id = target_antes.id
            exame = db.query(Exame).filter(Exame.laudo_id == laudo.id).order_by(Exame.id.desc()).first()

            target, liberado_agora = laudos._upsert_portal_partner_release_target(
                db,
                partner_id=PARTNER_NOMEADO,
                exame_id=exame.id,
                laudo_id=laudo.id,
                created_by_user_id=7,
                released_at=datetime(2026, 9, 18, 12, 0),
                contexto={"source": "teste"},
            )
            db.commit()

            self.assertEqual(target.id, target_id)
            self.assertTrue(liberado_agora)
            self.assertIsNone(self._target(db, laudo, PARTNER_NOMEADO).revoked_at)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_parceiro_revogado_nao_recebe_mais_aviso_por_whatsapp(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            laudo = self._build_laudo(db)
            self._revogar(db, laudo.id, PARTNER_NOMEADO)

            payload = laudos.PortalReportWhatsAppRequest(idempotency_key="idem-revogar-001")
            with (
                patch.object(
                    laudos,
                    "send_approved_utility_template",
                    side_effect=lambda **kwargs: {"message_id": "wamid.teste", "idempotent": False},
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

            por_id = {item["partner_id"]: item for item in resposta["veterinarios_parceiros"]}
            self.assertEqual(por_id[PARTNER_NOMEADO]["motivo"], "nao_liberado")
            self.assertEqual(por_id[PARTNER_VINCULO]["status"], "enviado")
            destinos_chamados = [call.kwargs["destination"] for call in send_mock.call_args_list]
            self.assertNotIn("5585988880002", destinos_chamados)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
