import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SECRET_KEY", "configuracoes-autorizacao-test-secret-key-1234567890")

from fastapi import HTTPException

from app.api.v1.endpoints import configuracoes
from app.models.configuracao import Configuracao


class ConfiguracoesAutorizacaoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "configuracoes-autorizacao.db"
        self._engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(bind=self._engine, autocommit=False, autoflush=False)
        Configuracao.__table__.create(self._engine, checkfirst=True)

    def tearDown(self) -> None:
        self._engine.dispose()
        self._tmpdir.cleanup()

    def _build_user(self, is_admin: bool):
        return SimpleNamespace(
            id=12,
            nome="Teste",
            email="teste@fortcordis.com",
            tem_papel=lambda papel: bool(is_admin and str(papel).lower() == "admin"),
        )

    def test_nao_admin_nao_pode_alterar_agenda_excecoes(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={
                        "agenda_excecoes": [
                            {"data": "2026-05-30", "ativo": False, "inicio": "08:00", "fim": "18:00", "motivo": "Bloqueio"}
                        ]
                    },
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Apenas administradores", str(ctx.exception.detail))

    def test_nao_admin_pode_enviar_agenda_excecoes_sem_mudanca(self) -> None:
        with self._session_factory() as db:
            resposta = configuracoes.atualizar_configuracoes(
                dados={"agenda_excecoes": []},
                db=db,
                current_user=self._build_user(False),
            )

        self.assertEqual(resposta["message"], "Configurações atualizadas com sucesso")

    def test_nao_admin_nao_pode_alterar_whatsapp_lembrete_automatico(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_lembrete_automatico_habilitado": True},
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("lembrete automatico de WhatsApp", str(ctx.exception.detail))

    def test_admin_pode_habilitar_whatsapp_lembrete_automatico(self) -> None:
        with self._session_factory() as db:
            configuracoes.atualizar_configuracoes(
                dados={"whatsapp_lembrete_automatico_habilitado": True},
                db=db,
                current_user=self._build_user(True),
            )
            resposta = configuracoes.obter_configuracoes(db=db, current_user=self._build_user(True))

        self.assertTrue(resposta["whatsapp_lembrete_automatico_habilitado"])

    def test_nao_admin_nao_pode_alterar_whatsapp_bot_atendimento_habilitado(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_bot_atendimento_habilitado": True},
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("atendimento automatico de WhatsApp", str(ctx.exception.detail))

    def test_nao_admin_nao_pode_alterar_whatsapp_bot_modo(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_bot_modo": "auto"},
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("modo padrao", str(ctx.exception.detail))

    def test_nao_admin_pode_reenviar_whatsapp_bot_modo_sem_mudanca(self) -> None:
        with self._session_factory() as db:
            resposta = configuracoes.atualizar_configuracoes(
                dados={"whatsapp_bot_modo": "suggest"},
                db=db,
                current_user=self._build_user(False),
            )

        self.assertEqual(resposta["message"], "Configurações atualizadas com sucesso")

    def test_whatsapp_bot_modo_invalido_e_rejeitado_422(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_bot_modo": "invalido"},
                    db=db,
                    current_user=self._build_user(True),
                )

        self.assertEqual(ctx.exception.status_code, 422)

    def test_nao_admin_nao_pode_alterar_participacao_do_bot(self) -> None:
        """RF-P02: postura decide ALCANCE, entao segue a regra dos toggles.

        Modo por conversa e por clinica sao controle operacional e nao exigem
        admin; a postura, nao - ela sozinha coloca ou tira todo mundo.
        """
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_bot_participacao": "piloto"},
                    db=db,
                    current_user=self._build_user(False),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("participacao", str(ctx.exception.detail).lower())

    def test_participacao_invalida_e_rejeitada_422(self) -> None:
        with self._session_factory() as db:
            with self.assertRaises(HTTPException) as ctx:
                configuracoes.atualizar_configuracoes(
                    dados={"whatsapp_bot_participacao": "quase-piloto"},
                    db=db,
                    current_user=self._build_user(True),
                )

        self.assertEqual(ctx.exception.status_code, 422)

    def test_admin_pode_ligar_o_piloto(self) -> None:
        with self._session_factory() as db:
            configuracoes.atualizar_configuracoes(
                dados={"whatsapp_bot_participacao": "piloto"},
                db=db,
                current_user=self._build_user(True),
            )
            resposta = configuracoes.obter_configuracoes(db=db, current_user=self._build_user(True))

        self.assertEqual(resposta["whatsapp_bot_participacao"], "piloto")

    def test_admin_pode_habilitar_whatsapp_bot_e_mudar_modo(self) -> None:
        with self._session_factory() as db:
            configuracoes.atualizar_configuracoes(
                dados={"whatsapp_bot_atendimento_habilitado": True, "whatsapp_bot_modo": "auto"},
                db=db,
                current_user=self._build_user(True),
            )
            resposta = configuracoes.obter_configuracoes(db=db, current_user=self._build_user(True))

        self.assertTrue(resposta["whatsapp_bot_atendimento_habilitado"])
        self.assertEqual(resposta["whatsapp_bot_modo"], "auto")


if __name__ == "__main__":
    unittest.main()
