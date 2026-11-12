import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "custom-exam-panels-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.schemas.atendimento import PainelExameItemPayload, PainelExamePayload


class AtendimentoCustomExamPanelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=1, nome="Tester")

    def _build_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "custom-exam-panels.db"
        engine = create_engine(f"sqlite:///{db_path}")
        for table in (CatalogoExame.__table__, PainelExame.__table__, PainelExameItem.__table__):
            table.create(engine, checkfirst=True)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        return tmpdir, session, engine

    def _seed_catalog(self, db):
        ecg = CatalogoExame(
            codigo="ecg",
            nome="Eletrocardiograma",
            categoria="Cardiologia",
            ativo=1,
        )
        eco = CatalogoExame(
            codigo="eco",
            nome="Ecocardiograma",
            categoria="Cardiologia",
            ativo=1,
        )
        db.add_all([ecg, eco])
        db.commit()
        db.refresh(ecg)
        db.refresh(eco)
        return ecg, eco

    def test_create_update_list_and_delete_custom_exam_panel(self) -> None:
        tmpdir, db, engine = self._build_session()
        try:
            ecg, eco = self._seed_catalog(db)

            created = atendimento.criar_painel_customizado_atendimento(
                PainelExamePayload(
                    nome="Fezes",
                    categoria="Coco",
                    itens=[PainelExameItemPayload(catalogo_exame_id=ecg.id)],
                ),
                db=db,
                current_user=self.user,
            )

            self.assertEqual(created["nome"], "Fezes")
            self.assertEqual(created["categoria"], "Coco")
            self.assertTrue(created["codigo"].startswith("custom_"))
            self.assertEqual(len(created["itens"]), 1)
            self.assertEqual(created["itens"][0]["catalogo_exame_id"], ecg.id)

            listed = atendimento.listar_paineis_customizados_atendimento(db=db, current_user=self.user)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], created["id"])

            updated = atendimento.atualizar_painel_customizado_atendimento(
                created["id"],
                PainelExamePayload(
                    nome="Fezes completo",
                    categoria="Laboratorio",
                    itens=[
                        PainelExameItemPayload(catalogo_exame_id=ecg.id),
                        PainelExameItemPayload(catalogo_exame_id=eco.id),
                    ],
                ),
                db=db,
                current_user=self.user,
            )

            self.assertEqual(updated["nome"], "Fezes completo")
            self.assertEqual(updated["categoria"], "Laboratorio")
            self.assertEqual(len(updated["itens"]), 2)
            self.assertEqual(
                [item["catalogo_exame_id"] for item in updated["itens"]],
                [ecg.id, eco.id],
            )

            deleted = atendimento.excluir_painel_customizado_atendimento(
                created["id"],
                db=db,
                current_user=self.user,
            )
            self.assertEqual(deleted["id"], created["id"])

            listed_after_delete = atendimento.listar_paineis_customizados_atendimento(db=db, current_user=self.user)
            self.assertEqual(listed_after_delete, [])
        finally:
            db.close()
            engine.dispose()
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
