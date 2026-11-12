"""Verificacao de escopo nas sessoes do portal.

Ate esta mudanca o campo `scope` era gravado no token e nunca lido: o controle de
acesso era so por `actor_type`. Cobre docs/specs/portal-escopo-sessao-clinica/.

O teste mais importante daqui e o de compatibilidade (CA-001 / NFR-002): toda
sessao que o portal emite hoje ja carrega o escopo cheio do seu ator, entao a
conferencia nova nasce sem efeito pratico. Se alguem um dia emitir sessao com
escopo menor por engano, e aqui que estoura.
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

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "portal-escopo-sessao-test-secret-key-1234567890")

from app.api.v1.endpoints import portal
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.core.portal_security import PortalSessionContext
from app.models.agendamento import Agendamento
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.clinica import Clinica
from app.models.laudo import Exame, Laudo
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.servico import Servico
from app.models.tutor import Tutor

CLINICA_ID = 8

# Escopo que o modo laudos usara (portal-clinica-dispositivo-confiavel): tudo de
# exame, nada de gestao da unidade.
ESCOPO_SO_LAUDOS = ("exam:read", "exam:download")


def _sessao(scope, *, actor_type: str = "clinica", actor_id: int = CLINICA_ID) -> PortalSessionContext:
    return PortalSessionContext(
        actor_type=actor_type,
        actor_id=actor_id,
        paciente_id=None,
        clinica_id=CLINICA_ID if actor_type == "clinica" else None,
        challenge_id="teste",
        display_name="Clinica Teste",
        channel="email_password",
        scope=tuple(scope),
        expires_at=datetime(2026, 12, 31, 23, 59),
    )


class PortalEscopoSessaoTest(unittest.TestCase):
    # ------------------------------------------------------------------
    # Compatibilidade: o que o portal emite hoje continua valendo tudo.
    # ------------------------------------------------------------------

    def test_todo_escopo_emitido_hoje_carrega_a_permissao_do_seu_ator(self) -> None:
        """CA-001 / NFR-002, na origem: nenhuma sessao atual perde acesso."""
        self.assertIn("clinic:read", portal.PORTAL_SCOPE_CLINICA)
        for escopo in (
            portal.PORTAL_SCOPE_CLINICA,
            portal.PORTAL_SCOPE_TUTOR,
            portal.PORTAL_SCOPE_PARTNER,
        ):
            self.assertIn("exam:read", escopo)
            self.assertIn("exam:download", escopo)

    def test_servicos_de_autenticacao_emitem_o_escopo_cheio(self) -> None:
        """Os tres pontos que emitem token nao podem divergir das constantes."""
        from app.services import portal_clinic_auth_service, portal_partner_auth_service

        clinic_source = Path(portal_clinic_auth_service.__file__).read_text(encoding="utf-8")
        partner_source = Path(portal_partner_auth_service.__file__).read_text(encoding="utf-8")

        self.assertIn('scope = ["clinic:read", "exam:read", "exam:download"]', clinic_source)
        self.assertIn('scope = ["partner:read", "exam:read", "exam:download"]', partner_source)

    def test_sessao_com_escopo_cheio_passa_no_guard_de_clinica(self) -> None:
        tmpdir, db = self._build_session()
        try:
            self._seed(db)
            clinica = portal._exigir_sessao_clinica_portal(db, _sessao(portal.PORTAL_SCOPE_CLINICA))
            self.assertEqual(clinica.id, CLINICA_ID)
        finally:
            db.close()
            tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Escopo reduzido: gestao da unidade fecha, laudo continua aberto.
    # ------------------------------------------------------------------

    def test_escopo_so_laudos_e_barrado_na_gestao_da_unidade(self) -> None:
        """CA-003: agenda, financeiro, cancelamento e recibo exigem clinic:read."""
        tmpdir, db = self._build_session()
        try:
            self._seed(db)
            sessao = _sessao(ESCOPO_SO_LAUDOS)

            chamadas = {
                "agendamentos": lambda: portal.listar_agendamentos_clinica_portal(
                    db=db, portal_session=sessao
                ),
                "financeiro": lambda: portal.obter_financeiro_clinica_portal(
                    db=db, portal_session=sessao
                ),
                "cancelamento": lambda: portal.cancelar_agendamento_clinica_portal(
                    1, request=None, db=db, portal_session=sessao
                ),
                "recibo": lambda: portal.baixar_recibo_os_clinica_portal(
                    1, db=db, portal_session=sessao
                ),
            }
            for nome, chamada in chamadas.items():
                with self.subTest(endpoint=nome):
                    with self.assertRaises(HTTPException) as erro:
                        chamada()
                    self.assertEqual(erro.exception.status_code, 403)
                    self.assertIn("permissao", erro.exception.detail)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_escopo_so_laudos_continua_lendo_exames_liberados(self) -> None:
        """CA-002: a leitura que o modo laudos precisa nao pode ser barrada."""
        tmpdir, db = self._build_session()
        try:
            self._seed(db)
            with patch.object(portal, "registrar_auditoria", return_value=None):
                resposta = self._listar_exames(db, _sessao(ESCOPO_SO_LAUDOS))

            self.assertEqual(len(resposta.items), 1)
            self.assertEqual(resposta.items[0].tipo_exame, "Ecocardiograma")
            self.assertIsNotNone(resposta.operational_summary)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_sessao_sem_exam_read_nao_le_exames(self) -> None:
        tmpdir, db = self._build_session()
        try:
            self._seed(db)
            with self.assertRaises(HTTPException) as erro:
                self._listar_exames(db, _sessao(("clinic:read",)))
            self.assertEqual(erro.exception.status_code, 403)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_download_exige_exam_download(self) -> None:
        tmpdir, db = self._build_session()
        try:
            exame = self._seed(db)
            with self.assertRaises(HTTPException) as erro:
                portal.gerar_download_url_exame_portal(
                    exame.id, db=db, portal_session=_sessao(("exam:read",))
                )
            self.assertEqual(erro.exception.status_code, 403)
            self.assertIn("permissao", erro.exception.detail)
        finally:
            db.close()
            tmpdir.cleanup()

    def test_escopo_vazio_nao_passa_em_nada(self) -> None:
        """Token sem scope (ou com scope ilegivel) falha fechado."""
        sessao = _sessao(())
        for permissao in ("clinic:read", "exam:read", "exam:download"):
            with self.subTest(permissao=permissao):
                with self.assertRaises(HTTPException) as erro:
                    portal._assert_portal_scope(sessao, permissao)
                self.assertEqual(erro.exception.status_code, 403)

    def test_guard_de_clinica_confere_escopo_antes_de_tocar_o_banco(self) -> None:
        """A recusa por permissao nao pode depender de consulta ao banco."""
        with self.assertRaises(HTTPException) as erro:
            portal._exigir_sessao_clinica_portal(None, _sessao(ESCOPO_SO_LAUDOS))
        self.assertEqual(erro.exception.status_code, 403)

    # ------------------------------------------------------------------

    def _listar_exames(self, db, sessao):
        return portal.listar_exames_clinica_portal(
            q=None,
            pet=None,
            tutor=None,
            especie=None,
            tipo_exame=None,
            status_exame=None,
            data_inicio=None,
            data_fim=None,
            sort_by="data",
            sort_dir="desc",
            limit=100,
            offset=0,
            db=db,
            portal_session=sessao,
        )

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "portal-escopo-sessao.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (
            Tutor.__table__,
            Paciente.__table__,
            Clinica.__table__,
            AtendimentoClinico.__table__,
            Laudo.__table__,
            Exame.__table__,
            AnexoAtendimento.__table__,
            Agendamento.__table__,
            OrdemServico.__table__,
            Servico.__table__,
        ):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session

    def _seed(self, db):
        tutor = Tutor(nome="Maria Tutora", email="maria@example.com", ativo=1)
        paciente = Paciente(nome="Thor", especie="Canina", tutor_id=1, ativo=1)
        clinica = Clinica(id=CLINICA_ID, nome="Clinica Pet Sus", ativo=True)
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
        db.commit()
        db.refresh(exame)
        return exame


if __name__ == "__main__":
    unittest.main()
