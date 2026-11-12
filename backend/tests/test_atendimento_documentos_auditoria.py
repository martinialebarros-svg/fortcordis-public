import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-documentos-auditoria-test-secret-key-1234567890")

from app.models.auditoria_evento import AuditoriaEvento
from app.models.atendimento_clinico import AtendimentoClinico, DocumentoAtendimento
from app.schemas.atendimento import DocumentoAtendimentoUpdatePayload
from app.services.atendimento import document_crud_service


class AtendimentoDocumentosAuditoriaTest(unittest.TestCase):
    """Achado #21 da auditoria: atualizar_documento_atendimento e
    excluir_documento_atendimento sobrescreviam/apagavam documentos clinicos
    (atestados, receituarios avulsos, declaracoes) sem nenhum registro de
    auditoria - se o conteudo original fosse contestado depois, nao havia
    como reconstituir o que foi de fato emitido nem quem alterou/apagou."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-documentos-auditoria.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (AtendimentoClinico.__table__, DocumentoAtendimento.__table__, AuditoriaEvento.__table__):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=17, nome="Dra. Teste")

        self.atendimento = AtendimentoClinico(
            paciente_id=100,
            veterinario_id=17,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Concluido",
        )
        self.db.add(self.atendimento)
        self.db.flush()

        self.documento = DocumentoAtendimento(
            atendimento_id=self.atendimento.id,
            titulo="Atestado de repouso",
            corpo="Recomendo 10 dias de repouso.",
            status="emitido",
        )
        self.db.add(self.documento)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def test_atualizar_documento_com_mudanca_gera_auditoria_com_antes_e_depois(self) -> None:
        with patch.object(document_crud_service, "auditar_documento") as auditoria_mock:
            document_crud_service.atualizar_documento_atendimento(
                self.db,
                self.atendimento,
                self.atendimento.id,
                self.documento.id,
                DocumentoAtendimentoUpdatePayload(versao=document_crud_service.versao_documento(self.documento), corpo="Recomendo 3 dias de repouso."),
                current_user=self.user,
            )

        auditoria_mock.assert_called_once()
        kwargs = auditoria_mock.call_args.kwargs
        self.assertEqual(auditoria_mock.call_args.args[2], "DOCUMENTO_ATENDIMENTO_ATUALIZADO")
        self.assertEqual(kwargs["current_user"], self.user)
        alteracoes = kwargs["detalhes"]["alteracoes"]
        self.assertEqual(alteracoes["corpo"]["antes"], "Recomendo 10 dias de repouso.")
        self.assertEqual(alteracoes["corpo"]["depois"], "Recomendo 3 dias de repouso.")
        self.assertNotIn("titulo", alteracoes)

    def test_atualizar_documento_sem_mudanca_nao_gera_auditoria(self) -> None:
        with patch.object(document_crud_service, "auditar_documento") as auditoria_mock:
            document_crud_service.atualizar_documento_atendimento(
                self.db,
                self.atendimento,
                self.atendimento.id,
                self.documento.id,
                DocumentoAtendimentoUpdatePayload(versao=document_crud_service.versao_documento(self.documento), corpo="Recomendo 10 dias de repouso."),
                current_user=self.user,
            )
        auditoria_mock.assert_not_called()

    def test_excluir_documento_e_auditado_com_conteudo_e_responsavel(self) -> None:
        documento_id = self.documento.id
        with patch.object(document_crud_service, "auditar_documento") as auditoria_mock:
            resposta = document_crud_service.excluir_documento_atendimento(
                self.db, self.atendimento.id, documento_id, current_user=self.user,
                versao=document_crud_service.versao_documento(self.documento)
            )

        self.assertEqual(resposta["id"], documento_id)
        self.assertEqual(self.db.get(DocumentoAtendimento, documento_id).status, "arquivado")

        auditoria_mock.assert_called_once()
        kwargs = auditoria_mock.call_args.kwargs
        self.assertEqual(auditoria_mock.call_args.args[2], "DOCUMENTO_ATENDIMENTO_ARQUIVADO")
        self.assertEqual(kwargs["current_user"], self.user)
        self.assertEqual(auditoria_mock.call_args.args[1].id, documento_id)
        self.assertEqual(kwargs["detalhes"]["conteudo_preservado"]["titulo"], "Atestado de repouso")
        self.assertEqual(
            kwargs["detalhes"]["conteudo_preservado"]["corpo"], "Recomendo 10 dias de repouso."
        )


if __name__ == "__main__":
    unittest.main()
