import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "pagination-test-secret-key-not-for-production")

from app.api.v1.endpoints.financeiro import listar_transacoes
from app.models.financeiro import Transacao


class TransacoesPaginationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Transacao.__table__.create(self.engine)
        self.db = Session(self.engine)
        for i in range(1, 506):
            self.db.add(Transacao(
                id=i, tipo="entrada", categoria="banho_tosa" if i == 1 else "consulta",
                descricao="Alvo 100%_" if i == 1 else "Consulta",
                paciente_nome="Rex" if i == 1 else None,
                valor=10, valor_final=10, status="Pago" if i == 1 else "Pendente",
                data_transacao=datetime(2026, 9, 13),
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def query(self, **kwargs):
        params = dict(tipo=None, clinica_id=None, skip=0, limit=100, db=self.db, current_user=None)
        params.update(kwargs)
        return listar_transacoes(**params)

    def test_pages_have_stable_order_and_full_total(self):
        first = self.query()
        second = self.query(skip=100)
        last = self.query(skip=500)
        self.assertEqual(first["total"], 505)
        self.assertEqual([t.id for t in first["items"]], list(range(505, 405, -1)))
        self.assertFalse(set(t.id for t in first["items"]) & set(t.id for t in second["items"]))
        self.assertEqual(len(last["items"]), 5)

    def test_search_finds_record_beyond_old_cap_and_filters_before_count(self):
        for term in (" rex ", "ALVO", "Banho e Tosa", "100%_"):
            result = self.query(search=term)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0].id, 1)
        self.assertEqual(self.query(search="rex", status="Pendente")["total"], 0)
        self.assertEqual(self.query(search="   ")["total"], 505)

    def test_literal_wildcards_and_empty_page(self):
        self.assertEqual(self.query(search="%")["total"], 1)
        self.assertEqual(self.query(search="_")["total"], 1)
        self.assertEqual(self.query(skip=600)["items"], [])


if __name__ == "__main__":
    unittest.main()
