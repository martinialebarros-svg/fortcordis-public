import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "agenda-assistente-encerramento-test-secret-key-1234567890")

from fastapi import HTTPException

from app.api.v1.endpoints import agenda
from app.models.clinica import Clinica
from app.models.servico import Servico


class AgendaAssistenteEncerramentoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "agenda-assistente-encerramento.db"
        self._engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        Clinica.__table__.create(self._engine, checkfirst=True)
        Servico.__table__.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _seed_data(self):
        with self._session_factory() as db:
            clinica = Clinica(
                nome="Zoomare",
                razao_social="Zoomare LTDA",
                cnpj="",
                telefone="",
                email="",
                endereco="Av Teste",
                cidade="Fortaleza",
                estado="CE",
                cep="60000-000",
            )
            servico = Servico(nome="Consulta", descricao="Consulta", duracao_minutos=60)
            db.add(clinica)
            db.add(servico)
            db.commit()
            db.refresh(clinica)
            db.refresh(servico)
            return clinica.id, servico.id

    def _build_user(self, is_admin: bool):
        return SimpleNamespace(
            id=9,
            nome="Teste",
            email="teste@fortcordis.com",
            tem_papel=lambda papel: bool(is_admin and str(papel).lower() == "admin"),
        )

    def test_registra_solicitacao_excecao_com_detalhes_estruturados(self) -> None:
        clinica_id, servico_id = self._seed_data()
        payload = agenda.AssistenteEncerramentoPayload(
            tipo="solicitacao_excecao",
            motivo="Cliente so pode no inicio da manha por restricao de transporte.",
            clinica_id=clinica_id,
            servico_id=servico_id,
            data_referencia="2026-05-23",
            data_contato="2026-05-21",
            contexto={"total_sugestoes": 2},
        )

        with self._session_factory() as db, patch.object(agenda, "registrar_auditoria") as mocked_audit:
            resposta = agenda.registrar_encerramento_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._build_user(False),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["tipo"], "solicitacao_excecao")
        self.assertGreaterEqual(mocked_audit.call_count, 1)
        chamada_principal = next(
            (
                call
                for call in mocked_audit.call_args_list
                if call.kwargs.get("acao") == "ASSISTENTE_AGENDA_SOLICITACAO_EXCECAO"
            ),
            None,
        )
        self.assertIsNotNone(chamada_principal)
        detalhes = chamada_principal.kwargs["detalhes"]
        self.assertEqual(detalhes["tipo"], "solicitacao_excecao")
        self.assertEqual(detalhes["clinica_id"], clinica_id)
        self.assertEqual(detalhes["servico_id"], servico_id)
        self.assertEqual(detalhes["perfil_usuario"], "nao_admin")
        self.assertEqual(detalhes["contexto"], {"total_sugestoes": 2})

    def test_rejeita_motivo_sem_conteudo_util(self) -> None:
        payload = agenda.AssistenteEncerramentoPayload(
            tipo="encerramento_sem_agendamento",
            motivo="     ",
        )

        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                agenda.registrar_encerramento_assistente(
                    payload=payload,
                    request=None,
                    db=db,
                    current_user=self._build_user(True),
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Motivo deve ter ao menos", str(ctx.exception.detail))

    def test_rejeita_data_referencia_invalida(self) -> None:
        payload = agenda.AssistenteEncerramentoPayload(
            tipo="encerramento_sem_agendamento",
            motivo="Cliente nao pode nas datas disponiveis.",
            data_referencia="21-05-2026",
        )

        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                agenda.registrar_encerramento_assistente(
                    payload=payload,
                    request=None,
                    db=db,
                    current_user=self._build_user(True),
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Data de referencia invalida", str(ctx.exception.detail))

    def test_registra_encerramento_sem_agendamento_para_admin(self) -> None:
        clinica_id, _ = self._seed_data()
        payload = agenda.AssistenteEncerramentoPayload(
            tipo="encerramento_sem_agendamento",
            motivo="Cliente desistiu do atendimento nesta semana.",
            clinica_id=clinica_id,
            data_referencia="2026-05-23",
            contexto={"total_sugestoes": 1},
        )

        with self._session_factory() as db, patch.object(agenda, "registrar_auditoria") as mocked_audit:
            resposta = agenda.registrar_encerramento_assistente(
                payload=payload,
                request=None,
                db=db,
                current_user=self._build_user(True),
            )

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["tipo"], "encerramento_sem_agendamento")
        chamada_principal = next(
            (
                call
                for call in mocked_audit.call_args_list
                if call.kwargs.get("acao") == "ASSISTENTE_AGENDA_ENCERRADO_SEM_AGENDAMENTO"
            ),
            None,
        )
        self.assertIsNotNone(chamada_principal)
        detalhes = chamada_principal.kwargs["detalhes"]
        self.assertEqual(detalhes["perfil_usuario"], "admin")
        self.assertEqual(detalhes["tipo"], "encerramento_sem_agendamento")

    def test_rejeita_encerramento_sem_oferta_exibida(self) -> None:
        payload = agenda.AssistenteEncerramentoPayload(
            tipo="solicitacao_excecao",
            motivo="Cliente nao aceitou as alternativas apresentadas.",
            contexto={"total_sugestoes": 0},
        )

        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                agenda.registrar_encerramento_assistente(
                    payload=payload,
                    request=None,
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("ao menos 1 oferta exibida", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
