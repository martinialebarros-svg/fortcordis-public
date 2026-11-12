import importlib.util
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "imagens-configuracao-test-secret-key-1234567890")

from app.api.v1.endpoints.imagens import (  # noqa: E402
    ImagemConfiguracaoItem,
    ImagensConfiguracaoPayload,
    associar_imagens_ao_laudo,
    atualizar_configuracao_imagens_laudo,
    atualizar_configuracao_imagens_temporarias,
)
from app.models.imagem_laudo import ImagemLaudo, ImagemTemporaria  # noqa: E402
from app.models.laudo import Laudo  # noqa: E402
from app.models.paciente import Paciente  # noqa: E402
from app.services.laudo_pdf_service import (  # noqa: E402
    _carregar_stamp_cache,
    _listar_imagens_incluidas_no_pdf,
    _preparar_imagens_pdf,
)

MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "20260924_91_imagens_incluir_no_pdf.py"
SPEC = importlib.util.spec_from_file_location("migration_20260924_91", MIGRATION_PATH)
MIGRATION = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MIGRATION)


class ImagensConfiguracaoPdfTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            Paciente.__table__.create(connection)
            Laudo.__table__.create(connection)
            connection.execute(Laudo.__table__.insert(), [
                {"id": row_id, "paciente_id": 1, "veterinario_id": 3,
                 "tipo": "ecocardiograma", "titulo": "TESTE DE IMAGENS"}
                for row_id in (7, 8, 9)
            ])
            connection.execute(text("""
                CREATE TABLE imagens_laudo (
                    id INTEGER PRIMARY KEY, laudo_id INTEGER, nome_arquivo VARCHAR(255) NOT NULL,
                    tipo_mime VARCHAR(100), tamanho_bytes INTEGER, conteudo BLOB,
                    caminho_arquivo VARCHAR(500), ordem INTEGER DEFAULT 0, pagina INTEGER DEFAULT 1,
                    largura FLOAT DEFAULT 0, altura FLOAT DEFAULT 0, descricao TEXT DEFAULT '',
                    incluir_no_pdf BOOLEAN NOT NULL DEFAULT 1, created_at TIMESTAMP, ativo INTEGER DEFAULT 1
                )
            """))
            connection.execute(text("""
                CREATE TABLE imagens_temporarias (
                    id INTEGER PRIMARY KEY, session_id VARCHAR(255), nome_arquivo VARCHAR(255) NOT NULL,
                    tipo_mime VARCHAR(100), tamanho_bytes INTEGER, conteudo BLOB NOT NULL,
                    ordem INTEGER DEFAULT 0, descricao TEXT DEFAULT '', incluir_no_pdf BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP, expira_em TIMESTAMP
                )
            """))
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_atualiza_ordem_e_selecao_e_pdf_filtra_sem_apagar_imagem(self) -> None:
        self.session.add_all([
            ImagemLaudo(id=1, laudo_id=7, nome_arquivo="a.jpg", conteudo=b"a", ordem=0),
            ImagemLaudo(id=2, laudo_id=7, nome_arquivo="b.jpg", conteudo=b"b", ordem=1),
        ])
        self.session.commit()

        atualizar_configuracao_imagens_laudo(
            7,
            ImagensConfiguracaoPayload(imagens=[
                ImagemConfiguracaoItem(id=2, ordem=0, incluir_no_pdf=True),
                ImagemConfiguracaoItem(id=1, ordem=1, incluir_no_pdf=False),
            ]),
            self.session,
            SimpleNamespace(id=3),
        )

        todas = self.session.query(ImagemLaudo).order_by(ImagemLaudo.id).all()
        self.assertEqual(len(todas), 2)
        self.assertFalse(todas[0].incluir_no_pdf)
        self.assertEqual([imagem.id for imagem in _listar_imagens_incluidas_no_pdf(self.session, 7)], [2])
        stamp = _carregar_stamp_cache(
            self.session,
            self.session.get(Laudo, 7),
            3,
        )
        self.assertEqual(stamp["imagens_config"], [
            {"id": 2, "ordem": 0, "incluir_no_pdf": True, "descricao": ""},
            {"id": 1, "ordem": 1, "incluir_no_pdf": False, "descricao": ""},
        ])
        imagens_bytes, imagens_eco = _preparar_imagens_pdf(_listar_imagens_incluidas_no_pdf(self.session, 7))
        self.assertEqual(imagens_bytes, [b"b"])
        self.assertEqual(imagens_eco, [{"conteudo": b"b", "descricao": ""}])

    def test_legenda_opcional_persiste_sem_alterar_outra_imagem(self) -> None:
        self.session.add_all([
            ImagemLaudo(id=1, laudo_id=7, nome_arquivo="a.jpg", conteudo=b"a", ordem=0, descricao="Original"),
            ImagemLaudo(id=2, laudo_id=7, nome_arquivo="b.jpg", conteudo=b"b", ordem=1, descricao="Preservar"),
        ])
        self.session.commit()

        atualizar_configuracao_imagens_laudo(
            7,
            ImagensConfiguracaoPayload(imagens=[
                ImagemConfiguracaoItem(id=1, ordem=0, descricao="  Doppler da IT  "),
                ImagemConfiguracaoItem(id=2, ordem=1),
            ]),
            self.session,
            SimpleNamespace(id=3),
        )

        self.assertEqual(self.session.get(ImagemLaudo, 1).descricao, "Doppler da IT")
        self.assertEqual(self.session.get(ImagemLaudo, 2).descricao, "Preservar")

        stamp = _carregar_stamp_cache(
            self.session,
            self.session.get(Laudo, 7),
            3,
        )
        self.assertEqual(stamp["imagens_config"][0]["descricao"], "Doppler da IT")
        _, imagens_eco = _preparar_imagens_pdf(_listar_imagens_incluidas_no_pdf(self.session, 7))
        self.assertEqual(imagens_eco[0]["descricao"], "Doppler da IT")

    def test_configuracao_temporaria_fica_restrita_a_sessao(self) -> None:
        futuro = datetime.utcnow() + timedelta(hours=1)
        self.session.add_all([
            ImagemTemporaria(id=10, session_id="sessao-a", nome_arquivo="a.jpg", conteudo=b"a", ordem=0, expira_em=futuro),
            ImagemTemporaria(id=11, session_id="sessao-b", nome_arquivo="b.jpg", conteudo=b"b", ordem=0, expira_em=futuro),
        ])
        self.session.commit()

        atualizar_configuracao_imagens_temporarias(
            "sessao-a",
            ImagensConfiguracaoPayload(imagens=[
                ImagemConfiguracaoItem(id=10, ordem=2, incluir_no_pdf=False),
            ]),
            self.session,
            SimpleNamespace(id=3),
        )

        self.assertFalse(self.session.get(ImagemTemporaria, 10).incluir_no_pdf)
        self.assertTrue(self.session.get(ImagemTemporaria, 11).incluir_no_pdf)

    def test_legenda_temporaria_e_restrita_a_sessao(self) -> None:
        futuro = datetime.utcnow() + timedelta(hours=1)
        self.session.add_all([
            ImagemTemporaria(id=10, session_id="sessao-a", nome_arquivo="a.jpg", conteudo=b"a", ordem=0, expira_em=futuro),
            ImagemTemporaria(id=11, session_id="sessao-b", nome_arquivo="b.jpg", conteudo=b"b", ordem=0, expira_em=futuro),
        ])
        self.session.commit()

        atualizar_configuracao_imagens_temporarias(
            "sessao-a",
            ImagensConfiguracaoPayload(imagens=[ImagemConfiguracaoItem(id=10, ordem=0, descricao="Imagem apical")]),
            self.session,
            SimpleNamespace(id=3),
        )
        self.assertEqual(self.session.get(ImagemTemporaria, 10).descricao, "Imagem apical")
        self.assertEqual(self.session.get(ImagemTemporaria, 11).descricao or "", "")

    def test_associacao_preserva_ordem_e_selecao_para_pdf(self) -> None:
        futuro = datetime.utcnow() + timedelta(hours=1)
        self.session.add_all([
            ImagemTemporaria(id=20, session_id="sessao-c", nome_arquivo="a.jpg", conteudo=b"a", ordem=1, incluir_no_pdf=False, expira_em=futuro),
            ImagemTemporaria(id=21, session_id="sessao-c", nome_arquivo="b.jpg", conteudo=b"b", ordem=0, incluir_no_pdf=True, expira_em=futuro),
        ])
        self.session.commit()

        associar_imagens_ao_laudo(9, "sessao-c", self.session, SimpleNamespace(id=3))

        associadas = self.session.query(ImagemLaudo).filter(ImagemLaudo.laudo_id == 9).order_by(ImagemLaudo.ordem).all()
        self.assertEqual([imagem.nome_arquivo for imagem in associadas], ["b.jpg", "a.jpg"])
        self.assertEqual([imagem.incluir_no_pdf for imagem in associadas], [True, False])

    def test_migracao_adiciona_coluna_com_default_sem_desmarcar_legado(self) -> None:
        self.assertEqual(MIGRATION._boolean_default_sql("postgresql"), "TRUE")
        self.assertEqual(MIGRATION._boolean_default_sql("sqlite"), "1")
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE imagens_laudo (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE imagens_temporarias (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO imagens_laudo (id) VALUES (1)"))
            MIGRATION.upgrade(connection, "sqlite")
            MIGRATION.upgrade(connection, "sqlite")
            self.assertIn("incluir_no_pdf", {c["name"] for c in inspect(connection).get_columns("imagens_laudo")})
            self.assertEqual(connection.execute(text("SELECT incluir_no_pdf FROM imagens_laudo WHERE id=1")).scalar_one(), 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
