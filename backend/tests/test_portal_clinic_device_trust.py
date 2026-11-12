"""Confianca de dispositivo da recepcao - portal em modo laudos, sem senha.

Cobre docs/specs/portal-clinica-dispositivo-confiavel/ (CA-004 a CA-013, CB-005).
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-device-trust-test-secret-key-1234567890")

from app.api.v1.endpoints import portal, portal_clinic_auth
from app.core.config import settings
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.core.portal_security import decode_portal_session_token
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.tutor import Tutor
from app.schemas.portal import PortalAdminDeviceRevokeRequest, PortalDeviceTrustRequest
from app.services import portal_clinic_device_trust_service as trust_service
from app.services import portal_clinic_exam_link_service as link_service

COOKIE = settings.PORTAL_CLINIC_DEVICE_TRUST_COOKIE_NAME


def _request(*, cookie: str | None = None, user_agent: str = "Chrome/Recepcao") -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"user-agent", user_agent.encode())]
    if cookie:
        headers.append((b"cookie", f"{COOKIE}={cookie}".encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/portal/clinicas/dispositivo/sessao",
            "raw_path": b"/api/v1/portal/clinicas/dispositivo/sessao",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("app.fortcordis.com.br", 80),
        }
    )


def _cookie_do(response: Response) -> str | None:
    """Le o valor do cookie de dispositivo gravado na resposta."""
    for chave, valor in response.raw_headers:
        if chave.lower() != b"set-cookie":
            continue
        texto = valor.decode()
        if texto.startswith(f"{COOKIE}="):
            gravado = texto.split(";", 1)[0].split("=", 1)[1]
            return gravado or None
    return None


class PortalClinicDeviceTrustTest(unittest.TestCase):
    # ------------------------------------------------------------------

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-device-trust.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            PortalClinicExamLink.__table__,
            PortalClinicTrustedDevice.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session

    def _seed(self, db):
        tutor = Tutor(nome="Maria Tutora", email="maria@example.com", ativo=1)
        paciente = Paciente(nome="Thor", especie="Canina", tutor_id=1, ativo=1)
        clinica = Clinica(nome="Clinica Pet Sus", email="petsus@example.com", ativo=True)
        db.add_all([tutor, paciente, clinica])
        db.flush()
        paciente.tutor_id = tutor.id

        atendimento = AtendimentoClinico(
            paciente_id=paciente.id,
            tutor_id=tutor.id,
            clinica_id=clinica.id,
            veterinario_id=77,
            especie="Canina",
            data_atendimento=datetime(2026, 9, 17, 9, 30),
            status="Concluido",
            criado_por_id=77,
            criado_por_nome="Vet Teste",
        )
        db.add(atendimento)
        db.flush()

        exame = Exame(
            atendimento_id=atendimento.id,
            paciente_id=paciente.id,
            tipo_exame="Ecocardiograma",
            status=PORTAL_RELEASED_STATUS,
            data_solicitacao=datetime(2026, 9, 17, 9, 0),
        )
        db.add(exame)
        db.commit()
        for item in (clinica, exame):
            db.refresh(item)
        return clinica, exame

    def _conectar(self, db, token, *, response=None, request=None):
        response = response or Response()
        with (
            patch.object(settings, "PORTAL_CLINIC_DEVICE_TRUST_ENABLED", True),
            patch.object(portal, "registrar_auditoria", return_value=None),
            patch.object(portal, "notify_clinic_device_trusted", return_value=None),
        ):
            resultado = portal.confiar_dispositivo_por_link(
                token,
                PortalDeviceTrustRequest(device_label="Recepcao 1"),
                request=request or _request(),
                response=response,
                db=db,
            )
        return resultado, response

    def _sessao(self, db, cookie, *, user_agent="Chrome/Recepcao"):
        response = Response()
        with patch.object(portal, "registrar_auditoria", return_value=None):
            resultado = portal.abrir_sessao_dispositivo_confiavel(
                request=_request(cookie=cookie, user_agent=user_agent),
                response=response,
                db=db,
            )
        return resultado, response

    # ------------------------------------------------------------------

    def test_conectar_cria_confianca_com_escopo_so_de_laudos(self) -> None:
        """CA-004 e NFR-001: o link nunca vira acesso a gestao da unidade."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)

            resultado, response = self._conectar(db, raw)

            self.assertEqual(resultado.scope, ["exam:read", "exam:download"])
            self.assertNotIn("clinic:read", resultado.scope)
            self.assertEqual(resultado.clinica_id, clinica.id)
            self.assertEqual(resultado.auth_method, "device_trust")

            # O token emitido precisa carregar o escopo reduzido de verdade.
            contexto = decode_portal_session_token(resultado.access_token)
            self.assertEqual(contexto.scope, ("exam:read", "exam:download"))
            self.assertEqual(contexto.clinica_id, clinica.id)

            trust = db.query(PortalClinicTrustedDevice).one()
            self.assertEqual(trust.status, "active")
            self.assertEqual(trust.origin, "exam_link")
            self.assertIsNotNone(trust.origin_exam_link_id)
            self.assertIsNotNone(_cookie_do(response))
        finally:
            db.close()
            tmpdir.cleanup()

    def test_conectar_com_link_invalido_nao_cria_nada(self) -> None:
        """CA-005: a recusa e a mesma da abertura do laudo."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            link_service.revoke_links_for_exam(db, exame.id, motivo="teste")

            with self.assertRaises(HTTPException) as erro:
                self._conectar(db, raw)

            self.assertEqual(erro.exception.status_code, 404)
            self.assertEqual(erro.exception.detail, "Link de laudo invalido ou indisponivel.")
            self.assertEqual(db.query(PortalClinicTrustedDevice).count(), 0)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_flag_desligada_impede_conectar(self) -> None:
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)

            with patch.object(settings, "PORTAL_CLINIC_DEVICE_TRUST_ENABLED", False):
                with self.assertRaises(HTTPException) as erro:
                    portal.confiar_dispositivo_por_link(
                        raw,
                        PortalDeviceTrustRequest(),
                        request=_request(),
                        response=Response(),
                        db=db,
                    )
            self.assertEqual(erro.exception.status_code, 404)
            self.assertEqual(db.query(PortalClinicTrustedDevice).count(), 0)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_sessao_rotaciona_o_cookie_e_renova_o_prazo(self) -> None:
        """CA-006: o cookie anterior deixa de valer no acesso seguinte."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie_1 = _cookie_do(response)

            trust = db.query(PortalClinicTrustedDevice).one()
            trust.expires_at = trust.expires_at - timedelta(days=10)
            db.commit()
            prazo_antes = trust.expires_at

            _, response_2 = self._sessao(db, cookie_1)
            cookie_2 = _cookie_do(response_2)

            self.assertIsNotNone(cookie_2)
            self.assertNotEqual(cookie_1, cookie_2)
            db.refresh(trust)
            self.assertGreater(trust.expires_at, prazo_antes)

            # CB-005 tambem: a flag desligada nao afeta confianca existente.
            with patch.object(settings, "PORTAL_CLINIC_DEVICE_TRUST_ENABLED", False):
                self._sessao(db, cookie_2)

            # O cookie antigo morreu com a rotacao.
            with self.assertRaises(HTTPException) as erro:
                self._sessao(db, cookie_1)
            self.assertEqual(erro.exception.status_code, 401)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_prazo_de_inatividade_e_de_30_dias(self) -> None:
        """Decisao de 18/09/2026, fixada aqui para nao se perder num refactor.

        O numero e de operacao, nao de medicao: 30 dias derrubam a maquina de uma
        clinica que passou um mes sem mandar exame, e ela reconecta pelo link
        seguinte. Mudar isso deve ser deliberado.
        """
        self.assertEqual(settings.PORTAL_CLINIC_DEVICE_TRUST_INACTIVITY_DAYS, 30)

        tmpdir, db = self._build_session()
        try:
            clinica, _exame = self._seed(db)
            trust, _ = trust_service.create_trust(
                db, clinica_id=clinica.id, request=_request()
            )
            dias = (trust.expires_at - datetime.utcnow()).days
            self.assertEqual(dias, 29)  # 29 dias e alguma horas -> 30 dias corridos
        finally:
            db.close()
            tmpdir.cleanup()

    def test_confianca_sem_uso_alem_do_prazo_expira(self) -> None:
        """CA-007."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            trust = db.query(PortalClinicTrustedDevice).one()
            trust.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

            with self.assertRaises(HTTPException) as erro:
                self._sessao(db, cookie)
            self.assertEqual(erro.exception.status_code, 401)
            db.refresh(trust)
            self.assertEqual(trust.status, "expired")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_navegador_diferente_encerra_a_confianca(self) -> None:
        """CA-008: divergencia de navegador revoga, nao so recusa."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            with self.assertRaises(HTTPException) as erro:
                self._sessao(db, cookie, user_agent="Outro/Navegador")
            self.assertEqual(erro.exception.status_code, 401)

            trust = db.query(PortalClinicTrustedDevice).one()
            self.assertEqual(trust.status, "revoked")
            self.assertEqual(trust.revoked_reason, "mudanca-de-dispositivo")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_revogar_o_link_de_origem_derruba_a_confianca(self) -> None:
        """CA-009: se o link vazou, o que ele gerou morre junto."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            revogados = trust_service.revoke_trusts_for_exam(db, exame.id, motivo="link_revogado")
            self.assertEqual(revogados, 1)

            with self.assertRaises(HTTPException) as erro:
                self._sessao(db, cookie)
            self.assertEqual(erro.exception.status_code, 401)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_encerrar_revoga_e_e_idempotente(self) -> None:
        """CA-010."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            with patch.object(portal, "registrar_auditoria", return_value=None):
                primeiro = portal.encerrar_dispositivo_confiavel(
                    request=_request(cookie=cookie), response=Response(), db=db
                )
                segundo = portal.encerrar_dispositivo_confiavel(
                    request=_request(cookie=cookie), response=Response(), db=db
                )

            self.assertTrue(primeiro.encerrado)
            self.assertTrue(segundo.encerrado)
            trust = db.query(PortalClinicTrustedDevice).one()
            self.assertEqual(trust.status, "revoked")
            self.assertEqual(trust.revoked_reason, "encerrado-pela-unidade")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_clinica_inativa_invalida_a_confianca(self) -> None:
        """RF-014."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            clinica.ativo = False
            db.commit()

            with self.assertRaises(HTTPException) as erro:
                self._sessao(db, cookie)
            self.assertEqual(erro.exception.status_code, 401)
            trust = db.query(PortalClinicTrustedDevice).one()
            self.assertEqual(trust.status, "revoked")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_falha_no_aviso_ao_gestor_nao_impede_a_conexao(self) -> None:
        """CA-011."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)

            with (
                patch.object(settings, "PORTAL_CLINIC_DEVICE_TRUST_ENABLED", True),
                patch.object(portal, "registrar_auditoria", return_value=None),
                patch.object(
                    portal,
                    "notify_clinic_device_trusted",
                    side_effect=RuntimeError("SMTP fora do ar"),
                ) as aviso,
            ):
                resultado = portal.confiar_dispositivo_por_link(
                    raw,
                    PortalDeviceTrustRequest(),
                    request=_request(),
                    response=Response(),
                    db=db,
                )

            aviso.assert_called_once()
            self.assertEqual(resultado.scope, ["exam:read", "exam:download"])
            self.assertEqual(db.query(PortalClinicTrustedDevice).count(), 1)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_sessao_de_rotina_nao_gera_auditoria(self) -> None:
        """CA-013 / NFR-005: a recepcao renova por meses; auditar tudo inundaria."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            _, response = self._conectar(db, raw)
            cookie = _cookie_do(response)

            with patch.object(portal, "registrar_auditoria", return_value=None) as audit:
                portal.abrir_sessao_dispositivo_confiavel(
                    request=_request(cookie=cookie), response=Response(), db=db
                )
            audit.assert_not_called()
        finally:
            db.close()
            tmpdir.cleanup()

    def test_admin_revoga_por_dispositivo_e_por_clinica(self) -> None:
        """CA-012."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame = self._seed(db)
            _, raw = link_service.issue_exam_link(db, exame_id=exame.id, clinica_id=clinica.id)
            self._conectar(db, raw)
            trust = db.query(PortalClinicTrustedDevice).one()
            operador = SimpleNamespace(id=1, nome="Operador", email="op@example.com")

            with patch.object(portal_clinic_auth, "registrar_auditoria", return_value=None):
                por_id = portal_clinic_auth.revogar_dispositivos_confiaveis_admin(
                    PortalAdminDeviceRevokeRequest(device_id=trust.id),
                    request=_request(),
                    db=db,
                    current_user=operador,
                )
                self.assertEqual(por_id.revogados, 1)

                # Segunda confianca, revogada pela clinica inteira.
                trust_service.create_trust(db, clinica_id=clinica.id, request=_request())
                por_clinica = portal_clinic_auth.revogar_dispositivos_confiaveis_admin(
                    PortalAdminDeviceRevokeRequest(clinica_id=clinica.id),
                    request=_request(),
                    db=db,
                    current_user=operador,
                )
                self.assertEqual(por_clinica.revogados, 1)

                with self.assertRaises(HTTPException) as sem_alvo:
                    portal_clinic_auth.revogar_dispositivos_confiaveis_admin(
                        PortalAdminDeviceRevokeRequest(),
                        request=_request(),
                        db=db,
                        current_user=operador,
                    )
                self.assertEqual(sem_alvo.exception.status_code, 422)

            ativos = (
                db.query(PortalClinicTrustedDevice)
                .filter(PortalClinicTrustedDevice.status == "active")
                .count()
            )
            self.assertEqual(ativos, 0)
        finally:
            db.close()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
