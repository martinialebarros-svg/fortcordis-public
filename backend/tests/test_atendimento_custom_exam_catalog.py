import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "custom-exam-catalog-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.catalogo_exame import CatalogoExame, PainelExame, PainelExameItem
from app.schemas.atendimento import CatalogoExameCustomPayload


class AtendimentoCustomExamCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "custom-exam-catalog.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        for table in (CatalogoExame.__table__, PainelExame.__table__, PainelExameItem.__table__):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=1, nome="Tester")

        self.standard_exam = CatalogoExame(
            codigo="ecg",
            nome="Eletrocardiograma",
            categoria="Cardiologia",
            ativo=1,
        )
        self.db.add(self.standard_exam)
        self.db.commit()
        self.db.refresh(self.standard_exam)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _payload(self, **overrides) -> CatalogoExameCustomPayload:
        values = {
            "nome": "Relacao proteina creatinina urinaria",
            "categoria": "Laboratorio",
            "subcategoria": "Urinaria",
            "preparo": "Coleta por cistocentese quando indicada.",
            "sinonimos": ["RPCU", "  RPCU  ", "Relacao proteina creatinina urinaria"],
        }
        values.update(overrides)
        return CatalogoExameCustomPayload(**values)

    def test_create_update_and_delete_custom_catalog_exam(self) -> None:
        created = atendimento.criar_catalogo_exame_customizado_atendimento(
            self._payload(),
            db=self.db,
            current_user=self.user,
        )

        self.assertTrue(created["codigo"].startswith("custom_exam_"))
        self.assertTrue(created["customizado"])
        self.assertEqual(created["sinonimos"], ["RPCU"])

        custom_id = created["id"]
        painel = PainelExame(
            codigo="custom_painel-renal",
            nome="Painel renal",
            categoria="Laboratorio",
            ativo=1,
        )
        self.db.add(painel)
        self.db.flush()
        self.db.add(PainelExameItem(painel_id=painel.id, catalogo_exame_id=custom_id, ordem=0))
        self.db.commit()

        updated = atendimento.atualizar_catalogo_exame_customizado_atendimento(
            custom_id,
            self._payload(nome="Relacao proteina/creatinina urinaria", sinonimos=["RPCU", "UPC"]),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(updated["nome"], "Relacao proteina/creatinina urinaria")
        self.assertEqual(updated["sinonimos"], ["RPCU", "UPC"])

        deleted = atendimento.excluir_catalogo_exame_customizado_atendimento(
            custom_id,
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(deleted["id"], custom_id)
        self.assertEqual(
            self.db.query(PainelExameItem).filter(PainelExameItem.catalogo_exame_id == custom_id).count(),
            0,
        )
        self.assertEqual(self.db.query(CatalogoExame).filter(CatalogoExame.id == custom_id).one().ativo, 0)

    def test_rejects_duplicate_active_name_case_insensitively(self) -> None:
        atendimento.criar_catalogo_exame_customizado_atendimento(
            self._payload(),
            db=self.db,
            current_user=self.user,
        )

        with self.assertRaises(HTTPException) as ctx:
            atendimento.criar_catalogo_exame_customizado_atendimento(
                self._payload(nome="RELACAO PROTEINA CREATININA URINARIA"),
                db=self.db,
                current_user=self.user,
            )

        self.assertEqual(ctx.exception.status_code, 409)

    def test_standard_catalog_exam_cannot_be_updated_or_deleted(self) -> None:
        with self.assertRaises(HTTPException) as update_ctx:
            atendimento.atualizar_catalogo_exame_customizado_atendimento(
                self.standard_exam.id,
                self._payload(nome="ECG alterado"),
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(update_ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as delete_ctx:
            atendimento.excluir_catalogo_exame_customizado_atendimento(
                self.standard_exam.id,
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(delete_ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
