import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite:///./fortcordis.db")
os.environ.setdefault("SECRET_KEY", "atendimento-sync-batching-nplus1-test-secret-key-1234567890")

from app.api.v1.endpoints import atendimento
from app.models.atendimento_clinico import (
    AnexoAtendimento,
    AtendimentoClinico,
    ExameAjuste,
    Medicamento,
    PrescricaoClinica,
    PrescricaoItem,
    PrescricaoItemAjuste,
)
from app.models.catalogo_exame import CatalogoExame, PainelExame
from app.models.laudo import Exame
from app.schemas.atendimento import ExameSolicitacaoPayload, PrescricaoItemPayload, PrescricaoPayload


class AtendimentoSyncBatchingNPlusOneTest(unittest.TestCase):
    """Achado #22 da auditoria: _sync_exames e _sync_prescricao faziam uma
    query de CatalogoExame/PainelExame/Medicamento POR ITEM do payload, em
    vez de uma unica query em lote - custo que se repete a cada autosave
    (PUT), mesmo quando nenhum campo de exame/prescricao de fato mudou,
    porque o frontend sempre reenvia os arrays inteiros."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "atendimento-sync-batching.db"
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        for table in (
            AtendimentoClinico.__table__,
            Exame.__table__,
            ExameAjuste.__table__,
            AnexoAtendimento.__table__,
            CatalogoExame.__table__,
            PainelExame.__table__,
            PrescricaoClinica.__table__,
            PrescricaoItem.__table__,
            PrescricaoItemAjuste.__table__,
            Medicamento.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.user = SimpleNamespace(id=1, nome="Dr Teste")

        self.atendimento = AtendimentoClinico(
            paciente_id=100,
            veterinario_id=1,
            especie="Canina",
            data_atendimento=datetime(2026, 7, 5, 9, 30),
            status="Em atendimento",
        )
        self.db.add(self.atendimento)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _capturar_sql(self):
        statements = []

        def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(self.engine, "before_cursor_execute", _capture)
        return statements, lambda: event.remove(self.engine, "before_cursor_execute", _capture)

    def test_painel_de_8_exames_com_mesmo_catalogo_faz_uma_unica_query_de_catalogo(self) -> None:
        catalogo = CatalogoExame(codigo="ECO-001", nome="Ecocardiograma", categoria="Cardiologia", clinic_id=None)
        self.db.add(catalogo)
        self.db.commit()

        payload = [
            ExameSolicitacaoPayload(tipo_exame="Ecocardiograma", catalogo_exame_id=catalogo.id)
            for _ in range(8)
        ]

        statements, parar_captura = self._capturar_sql()
        try:
            atendimento._sync_exames(self.db, self.atendimento, payload, self.user)
            self.db.commit()
        finally:
            parar_captura()

        selects_catalogo = [
            sql for sql in statements if "select" in sql and "catalogo_exames" in sql
        ]
        self.assertEqual(
            len(selects_catalogo),
            1,
            msg=f"esperava 1 SELECT para 8 itens com o mesmo catalogo_exame_id, achou {len(selects_catalogo)}",
        )

        exames_criados = self.db.query(Exame).filter(Exame.atendimento_id == self.atendimento.id).all()
        self.assertEqual(len(exames_criados), 8)
        self.assertTrue(all(e.categoria_exame == "Cardiologia" for e in exames_criados))

    def test_5_exames_com_catalogos_distintos_faz_uma_query_com_in(self) -> None:
        catalogos = [
            CatalogoExame(codigo=f"EXM-{i:03d}", nome=f"Exame {i}", categoria="Geral", clinic_id=None)
            for i in range(5)
        ]
        self.db.add_all(catalogos)
        self.db.commit()

        payload = [
            ExameSolicitacaoPayload(tipo_exame=f"Exame {i}", catalogo_exame_id=catalogo.id)
            for i, catalogo in enumerate(catalogos)
        ]

        statements, parar_captura = self._capturar_sql()
        try:
            atendimento._sync_exames(self.db, self.atendimento, payload, self.user)
            self.db.commit()
        finally:
            parar_captura()

        selects_catalogo = [sql for sql in statements if "select" in sql and "catalogo_exames" in sql]
        self.assertEqual(len(selects_catalogo), 1)

    def test_prescricao_com_5_itens_por_medicamento_id_faz_uma_unica_query(self) -> None:
        medicamentos = [Medicamento(nome=f"Medicamento {i}", ativo=1) for i in range(5)]
        self.db.add_all(medicamentos)
        self.db.commit()

        payload = PrescricaoPayload(
            itens=[
                PrescricaoItemPayload(medicamento_id=medicamento.id, medicamento_nome="")
                for medicamento in medicamentos
            ]
        )

        statements, parar_captura = self._capturar_sql()
        try:
            atendimento._sync_prescricao(self.db, self.atendimento, payload, self.user)
            self.db.commit()
        finally:
            parar_captura()

        selects_medicamento = [sql for sql in statements if "select" in sql and "medicamentos" in sql]
        self.assertEqual(
            len(selects_medicamento),
            1,
            msg=f"esperava 1 SELECT para 5 itens de prescricao, achou {len(selects_medicamento)}",
        )

        prescricao = (
            self.db.query(PrescricaoClinica)
            .filter(PrescricaoClinica.atendimento_id == self.atendimento.id)
            .first()
        )
        itens_criados = (
            self.db.query(PrescricaoItem).filter(PrescricaoItem.prescricao_id == prescricao.id).all()
        )
        self.assertEqual(len(itens_criados), 5)
        nomes = sorted(item.medicamento_nome for item in itens_criados)
        self.assertEqual(nomes, [f"Medicamento {i}" for i in range(5)])

    def test_prescricao_com_medicamento_id_invalido_continua_levantando_422(self) -> None:
        """Garante que o batching nao perdeu a validacao existente: id sem
        nome e sem medicamento correspondente ainda deve falhar."""
        from fastapi import HTTPException

        payload = PrescricaoPayload(
            itens=[PrescricaoItemPayload(medicamento_id=999999, medicamento_nome="")]
        )
        with self.assertRaises(HTTPException) as ctx:
            atendimento._sync_prescricao(self.db, self.atendimento, payload, self.user)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
