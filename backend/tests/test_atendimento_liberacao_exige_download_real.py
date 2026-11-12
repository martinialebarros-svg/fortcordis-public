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

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-liberacao-download-real-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.core.portal_release import PORTAL_RELEASED_STATUS
from app.models.atendimento_clinico import AnexoAtendimento, AtendimentoClinico
from app.models.laudo import Exame


class AtendimentoLiberacaoExigeDownloadRealTest(unittest.TestCase):
    """Achado #20 da auditoria: liberar_exame_no_portal exigia so que o
    metadado do anexo (mime_type/extensao) parecesse um PDF, sem confirmar
    que existe de fato algo baixavel - um anexo "externo" criado via
    POST /{id}/anexos com url/mime_type/nome_original livres (sem upload
    real) passava pelo guard e liberava o exame no portal."""

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "atendimento-liberacao-download-real.db"
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (AtendimentoClinico.__table__, Exame.__table__, AnexoAtendimento.__table__):
            table.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return tmpdir, session_factory(), engine

    def _seed_atendimento_e_exame(self, db):
        atendimento_item = AtendimentoClinico(
            paciente_id=182,
            tutor_id=44,
            clinica_id=8,
            veterinario_id=77,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Concluido",
            criado_por_id=77,
            criado_por_nome="Vet Teste",
        )
        db.add(atendimento_item)
        db.flush()
        exame = Exame(
            atendimento_id=atendimento_item.id,
            paciente_id=atendimento_item.paciente_id,
            tipo_exame="Ecocardiograma",
            categoria_exame="",
            prioridade="Rotina",
            status="Concluido",
            data_solicitacao=datetime(2026, 7, 5, 9, 30),
            data_resultado=datetime(2026, 7, 5, 10, 0),
            observacoes="Ecocardiograma concluido.",
        )
        db.add(exame)
        db.commit()
        return exame

    def test_anexo_com_metadado_falso_e_bloqueado(self) -> None:
        """PoC exato do achado: url/mime_type/nome_original batem com PDF,
        mas nao ha caminho_arquivo real nem URL remota valida - sem upload
        de fato, so metadado."""
        tmpdir, db, engine = self._build_session()
        try:
            exame = self._seed_atendimento_e_exame(db)
            db.add(
                AnexoAtendimento(
                    atendimento_id=exame.atendimento_id,
                    exame_id=exame.id,
                    tipo="resultado_exame",
                    descricao="PDF do resultado",
                    url="http://qualquer-coisa-que-nao-resolve.invalid",
                    nome_original="laudo.pdf",
                    mime_type="application/pdf",
                    caminho_arquivo=None,
                    origem="externo",
                )
            )
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                atendimento.liberar_exame_no_portal(
                    exame_id=exame.id,
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Dr Teste"),
                )

            self.assertEqual(ctx.exception.status_code, 422)
            db.refresh(exame)
            self.assertNotEqual(exame.status, PORTAL_RELEASED_STATUS)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_anexo_com_arquivo_local_real_e_liberado(self) -> None:
        """Caminho feliz: caminho_arquivo aponta para um arquivo que
        realmente existe - a liberacao deve continuar funcionando."""
        tmpdir, db, engine = self._build_session()
        try:
            exame = self._seed_atendimento_e_exame(db)
            caminho_real = str(Path(tmpdir.name) / "resultado.pdf")
            Path(caminho_real).write_bytes(b"%PDF-1.4 conteudo de teste")
            db.add(
                AnexoAtendimento(
                    atendimento_id=exame.atendimento_id,
                    exame_id=exame.id,
                    tipo="resultado_exame",
                    descricao="PDF do resultado",
                    url="/api/v1/atendimentos/anexos/1/arquivo",
                    nome_original="resultado.pdf",
                    mime_type="application/pdf",
                    caminho_arquivo=caminho_real,
                    origem="upload",
                )
            )
            db.commit()

            with patch.object(atendimento, "_auditar_transicao_exame_portal"):
                atendimento.liberar_exame_no_portal(
                    exame_id=exame.id,
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Dr Teste"),
                )

            db.refresh(exame)
            self.assertEqual(exame.status, PORTAL_RELEASED_STATUS)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()

    def test_anexo_com_caminho_arquivo_apontando_para_arquivo_inexistente_e_bloqueado(self) -> None:
        """Caso de borda real: registro do anexo existe (upload="upload"),
        mas o arquivo fisico foi removido do disco depois - nao pode liberar
        como se o resultado ainda estivesse disponivel."""
        tmpdir, db, engine = self._build_session()
        try:
            exame = self._seed_atendimento_e_exame(db)
            db.add(
                AnexoAtendimento(
                    atendimento_id=exame.atendimento_id,
                    exame_id=exame.id,
                    tipo="resultado_exame",
                    descricao="PDF do resultado",
                    url="/api/v1/atendimentos/anexos/1/arquivo",
                    nome_original="removido.pdf",
                    mime_type="application/pdf",
                    caminho_arquivo=str(Path(tmpdir.name) / "arquivo-que-nunca-existiu.pdf"),
                    origem="upload",
                )
            )
            db.commit()

            with self.assertRaises(HTTPException) as ctx:
                atendimento.liberar_exame_no_portal(
                    exame_id=exame.id,
                    db=db,
                    current_user=SimpleNamespace(id=1, nome="Dr Teste"),
                )
            self.assertEqual(ctx.exception.status_code, 422)
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
