"""Link direto de laudo entregue no WhatsApp da clinica.

Cobre docs/specs/portal-clinica-link-laudo-whatsapp/ (CA-004 a CA-010, CB-003).
"""
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
from starlette.requests import Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-exam-link-test-secret-key-1234567890")

from app.api.v1.endpoints import portal
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.core.portal_security import (
    PORTAL_DOWNLOAD_AUDIENCE,
    decode_portal_session_token,
)
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.paciente import Paciente
from app.models.portal_clinic_exam_link import PortalClinicExamLink
from app.models.portal_clinic_trusted_device import PortalClinicTrustedDevice
from app.models.tutor import Tutor
from app.services import portal_clinic_exam_link_service as link_service


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/portal/laudo-link/x",
        "raw_path": b"/api/v1/portal/laudo-link/x",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("app.fortcordis.com.br", 80),
    }
    return Request(scope)


class PortalClinicExamLinkTests(unittest.TestCase):
    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-exam-link.db"
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

    def _seed(self, db, tmpdir):
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
            categoria_exame="Cardiologia",
            prioridade="Rotina",
            status=PORTAL_RELEASED_STATUS,
            data_solicitacao=datetime(2026, 9, 17, 9, 0),
            data_resultado=datetime(2026, 9, 17, 10, 0),
        )
        db.add(exame)
        db.flush()

        file_path = Path(tmpdir.name) / "laudo-thor.pdf"
        file_path.write_bytes(b"%PDF-1.4\nlaudo\n")
        anexo = AnexoAtendimento(
            atendimento_id=atendimento.id,
            exame_id=exame.id,
            tipo="documento",
            descricao="Laudo PDF",
            url="/api/v1/atendimentos/anexos/1/arquivo",
            nome_original="laudo-thor.pdf",
            tamanho=file_path.stat().st_size,
            mime_type="application/pdf",
            caminho_arquivo=str(file_path),
            origem="upload",
        )
        db.add(anexo)
        db.commit()
        for item in (clinica, exame, anexo):
            db.refresh(item)
        return clinica, exame, anexo

    def _abrir(self, db, token: str):
        with patch.object(portal, "registrar_auditoria", return_value=None):
            return portal.abrir_laudo_por_link(token, request=_make_request(), db=db)

    def test_link_valido_entrega_o_exame_e_o_download(self) -> None:
        """CA-004 e CA-007: entrega o laudo, sem abrir sessao de portal."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, anexo = self._seed(db, tmpdir)
            _, raw_token = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )

            resposta = self._abrir(db, raw_token)

            self.assertEqual(resposta.clinica_nome, "Clinica Pet Sus")
            self.assertEqual(resposta.paciente_nome, "Thor")
            self.assertEqual(resposta.tipo_exame, "Ecocardiograma")
            self.assertEqual(len(resposta.arquivos), 1)
            self.assertEqual(resposta.arquivos[0].anexo_id, anexo.id)

            # CA-007: nada que sirva de sessao do portal na resposta.
            self.assertFalse(hasattr(resposta, "access_token"))
            with self.assertRaises(HTTPException):
                decode_portal_session_token(resposta.arquivos[0].download_token)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_download_token_fica_preso_ao_par_exame_anexo(self) -> None:
        """CA-006: o token nao serve para outro anexo nem para outro exame."""
        from jose import jwt

        from app.core.config import settings

        tmpdir, db = self._build_session()
        try:
            clinica, exame, anexo = self._seed(db, tmpdir)
            _, raw_token = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )
            resposta = self._abrir(db, raw_token)

            claims = jwt.decode(
                resposta.arquivos[0].download_token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                audience=PORTAL_DOWNLOAD_AUDIENCE,
            )
            self.assertEqual(claims["portal_exame_id"], exame.id)
            self.assertEqual(claims["portal_anexo_id"], anexo.id)
            self.assertEqual(claims["portal_clinica_id"], clinica.id)
            self.assertEqual(claims["token_kind"], "portal_download")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_token_inexistente_revogado_ou_despublicado_devolve_404(self) -> None:
        """CA-005 e CA-008: os tres casos caem no mesmo 404 generico."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, _ = self._seed(db, tmpdir)
            _, raw_token = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )

            with self.assertRaises(HTTPException) as inexistente:
                self._abrir(db, "token-que-nunca-existiu-mas-com-formato-plausivel")
            self.assertEqual(inexistente.exception.status_code, 404)

            # Exame fora do ar derruba o link mesmo sem revogacao explicita.
            exame.status = "Concluido"
            db.commit()
            with self.assertRaises(HTTPException) as despublicado:
                self._abrir(db, raw_token)
            self.assertEqual(despublicado.exception.status_code, 404)
            self.assertEqual(despublicado.exception.detail, inexistente.exception.detail)

            exame.status = PORTAL_RELEASED_STATUS
            db.commit()
            link_service.revoke_links_for_exam(db, exame.id, motivo="teste")
            with self.assertRaises(HTTPException) as revogado:
                self._abrir(db, raw_token)
            self.assertEqual(revogado.exception.status_code, 404)
            self.assertEqual(revogado.exception.detail, inexistente.exception.detail)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_reenvio_reaproveita_o_link_ativo(self) -> None:
        """CA-009: reenviar o aviso nao cria credencial nova."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, _ = self._seed(db, tmpdir)
            primeiro, token_a = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )
            segundo, token_b = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )

            self.assertEqual(primeiro.id, segundo.id)
            self.assertEqual(token_a, token_b)
            self.assertEqual(db.query(PortalClinicExamLink).count(), 1)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_reemissao_depois_de_revogar_gera_token_diferente(self) -> None:
        """CB-003: revogacao nao volta atras."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, _ = self._seed(db, tmpdir)
            _, token_antigo = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )
            link_service.revoke_links_for_exam(db, exame.id, motivo="teste")
            _, token_novo = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )

            self.assertNotEqual(token_antigo, token_novo)
            with self.assertRaises(HTTPException):
                self._abrir(db, token_antigo)
            self.assertEqual(self._abrir(db, token_novo).paciente_nome, "Thor")
        finally:
            db.close()
            tmpdir.cleanup()

    def test_abertura_conta_acessos(self) -> None:
        """CA-010: first_opened_at so na primeira vez."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, _ = self._seed(db, tmpdir)
            link, raw_token = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=clinica.id
            )
            self.assertEqual(link.open_count, 0)
            self.assertIsNone(link.first_opened_at)

            self._abrir(db, raw_token)
            db.refresh(link)
            primeiro_acesso = link.first_opened_at
            self.assertEqual(link.open_count, 1)
            self.assertIsNotNone(primeiro_acesso)

            self._abrir(db, raw_token)
            db.refresh(link)
            self.assertEqual(link.open_count, 2)
            self.assertEqual(link.first_opened_at, primeiro_acesso)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_link_de_outra_clinica_nao_abre_o_exame(self) -> None:
        """O vinculo exame->clinica e reconferido a cada abertura."""
        tmpdir, db = self._build_session()
        try:
            clinica, exame, _ = self._seed(db, tmpdir)
            outra = Clinica(nome="Clinica B", email="b@example.com", ativo=True)
            db.add(outra)
            db.commit()

            _, raw_token = link_service.issue_exam_link(
                db, exame_id=exame.id, clinica_id=outra.id
            )

            with self.assertRaises(HTTPException) as erro:
                self._abrir(db, raw_token)
            self.assertEqual(erro.exception.status_code, 404)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_token_com_formato_impossivel_nao_consulta_o_banco(self) -> None:
        """CB-005."""
        self.assertFalse(link_service.is_plausible_link_token("abc"))
        self.assertFalse(link_service.is_plausible_link_token(""))
        self.assertFalse(link_service.is_plausible_link_token(None))
        self.assertFalse(link_service.is_plausible_link_token("tem espaco no meio dele aqui ok"))
        self.assertTrue(link_service.is_plausible_link_token(link_service.derive_link_token(1, "nonce")))


if __name__ == "__main__":
    unittest.main()
