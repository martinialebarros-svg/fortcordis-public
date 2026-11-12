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
os.environ.setdefault("SECRET_KEY", "clinical-phrases-test-secret-key-1234567890")

from app.models.frase_atendimento_clinico import FraseAtendimentoClinico
from app.services import clinical_phrase_service


def _sample_payload() -> dict:
    return {
        "version": "1.0",
        "frases": [
            {
                "secao": "anamnese",
                "titulo": "Progressao lenta",
                "texto": "Tutor refere progressao lenta dos sinais.",
                "ordem": 10,
            },
            {
                "secao": "plano_terapeutico",
                "titulo": "Solicitar ECO + ECG",
                "texto": "Solicitar exames cardiologicos.",
                "ordem": 20,
            },
        ],
    }


class ClinicalPhraseServiceTest(unittest.TestCase):
    def _build_session(self, tmpdir: str):
        db_path = Path(tmpdir) / "clinical-phrases-test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        FraseAtendimentoClinico.__table__.create(engine, checkfirst=True)
        return sessionmaker(bind=engine, autocommit=False, autoflush=False)(), engine

    def test_seed_populates_phrase_bank(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_file = Path(tmpdir) / "atendimento_clinical_phrases.json"
            payload_file.write_text(json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")

            db, engine = self._build_session(tmpdir)
            try:
                with patch.object(clinical_phrase_service, "CLINICAL_PHRASES_FILE", payload_file):
                    report = clinical_phrase_service.ensure_clinical_phrases_seeded(db)
                    self.assertTrue(report["seeded"])
                    self.assertEqual(report["seeded_items"], 2)

                    contexto = clinical_phrase_service.montar_contexto_frases_clinicas(db)
                    self.assertEqual(len(contexto["frases"]), 2)
                    self.assertEqual(contexto["frases"][0]["secao"], "anamnese")
            finally:
                db.close()
                engine.dispose()

    def test_seed_is_idempotent_and_filters_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_file = Path(tmpdir) / "atendimento_clinical_phrases.json"
            payload_file.write_text(json.dumps(_sample_payload(), ensure_ascii=False), encoding="utf-8")

            db, engine = self._build_session(tmpdir)
            try:
                with patch.object(clinical_phrase_service, "CLINICAL_PHRASES_FILE", payload_file):
                    first = clinical_phrase_service.ensure_clinical_phrases_seeded(db)
                    second = clinical_phrase_service.ensure_clinical_phrases_seeded(db)

                    self.assertTrue(first["seeded"])
                    self.assertFalse(second["seeded"])
                    self.assertEqual(db.query(FraseAtendimentoClinico).count(), 2)

                    item = db.query(FraseAtendimentoClinico).filter(FraseAtendimentoClinico.secao == "anamnese").first()
                    self.assertIsNotNone(item)
                    item.ativo = 0
                    db.commit()

                    ativos = clinical_phrase_service.listar_frases_clinicas(db)
                    todos = clinical_phrase_service.listar_frases_clinicas(db, include_inactive=True)
                    self.assertEqual(len(ativos), 1)
                    self.assertEqual(len(todos), 2)
            finally:
                db.close()
                engine.dispose()

    def test_context_paginates_and_reports_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _sample_payload()
            payload["frases"].append(
                {
                    "secao": "anamnese",
                    "titulo": "Apetite preservado",
                    "texto": "Tutor relata apetite preservado.",
                    "ordem": 30,
                }
            )
            payload_file = Path(tmpdir) / "atendimento_clinical_phrases.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            db, engine = self._build_session(tmpdir)
            try:
                with patch.object(clinical_phrase_service, "CLINICAL_PHRASES_FILE", payload_file):
                    first_page = clinical_phrase_service.montar_contexto_frases_clinicas(db, limit=1)
                    second_page = clinical_phrase_service.montar_contexto_frases_clinicas(db, skip=1, limit=1)

                    self.assertEqual(first_page["total"], 3)
                    self.assertEqual(len(first_page["frases"]), 1)
                    self.assertEqual(len(second_page["frases"]), 1)
                    self.assertNotEqual(first_page["frases"][0]["id"], second_page["frases"][0]["id"])
            finally:
                db.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
