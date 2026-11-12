import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "exam-catalog-test-secret-key-1234567890")

from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.services import exam_catalog_service


def _sample_catalog_payload() -> dict:
    return {
        "version": "1.0",
        "exames": [
            {
                "codigo": "ecg",
                "nome": "Eletrocardiograma",
                "categoria": "Cardiologia",
                "subcategoria": "Monitorizacao",
                "prioridade_padrao": "Rotina",
                "valor_padrao": 0,
                "preparo": "Ambiente calmo.",
                "observacoes_padrao": "Registrar ritmo.",
                "sinonimos": ["eletro", "tracado"],
            },
            {
                "codigo": "eco",
                "nome": "Ecocardiograma",
                "categoria": "Cardiologia",
                "subcategoria": "Imagem",
                "prioridade_padrao": "Rotina",
                "valor_padrao": 0,
                "preparo": "Tosar janela quando necessario.",
                "observacoes_padrao": "Avaliar camaras.",
                "sinonimos": ["eco", "doppler cardiaco"],
            },
        ],
        "paineis": [
            {
                "codigo": "painel_basico",
                "nome": "Painel basico",
                "categoria": "Cardiologia",
                "observacoes": "Triagem inicial.",
                "itens": ["ecg", "eco"],
            }
        ],
    }


class ExamCatalogServiceTest(unittest.TestCase):
    def _build_session(self, tmpdir: str):
        db_path = Path(tmpdir) / "exam-catalog-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        CatalogoExame.__table__.create(engine, checkfirst=True)
        PainelExame.__table__.create(engine, checkfirst=True)
        PainelExameItem.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False)(), engine

    def test_seed_populates_catalog_and_panels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_file = Path(tmpdir) / "catalogo_exames.json"
            payload_file.write_text(json.dumps(_sample_catalog_payload(), ensure_ascii=False), encoding="utf-8")

            db, engine = self._build_session(tmpdir)
            try:
                with patch.object(exam_catalog_service, "CATALOGO_EXAMES_FILE", payload_file):
                    report = exam_catalog_service.ensure_exam_catalog_seeded(db)
                    self.assertTrue(report["seeded"])
                    self.assertEqual(report["seeded_exames"], 2)
                    self.assertEqual(report["seeded_paineis"], 1)
                    self.assertEqual(report["seeded_itens"], 2)

                    contexto = exam_catalog_service.montar_contexto_catalogo_exames(db)
                    self.assertEqual(len(contexto["exames"]), 2)
                    self.assertEqual(len(contexto["paineis"]), 1)
                    self.assertEqual(len(contexto["paineis"][0]["itens"]), 2)
            finally:
                db.close()
                engine.dispose()

    def test_seed_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_file = Path(tmpdir) / "catalogo_exames.json"
            payload_file.write_text(json.dumps(_sample_catalog_payload(), ensure_ascii=False), encoding="utf-8")

            db, engine = self._build_session(tmpdir)
            try:
                with patch.object(exam_catalog_service, "CATALOGO_EXAMES_FILE", payload_file):
                    first = exam_catalog_service.ensure_exam_catalog_seeded(db)
                    second = exam_catalog_service.ensure_exam_catalog_seeded(db)

                    self.assertTrue(first["seeded"])
                    self.assertFalse(second["seeded"])
                    self.assertEqual(db.query(CatalogoExame).count(), 2)
                    self.assertEqual(db.query(PainelExame).count(), 1)
                    self.assertEqual(db.query(PainelExameItem).count(), 2)
            finally:
                db.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
