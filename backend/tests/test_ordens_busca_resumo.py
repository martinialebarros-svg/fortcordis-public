import os
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "ordens-search-synthetic-tests-secret-key")

from app.api.v1.endpoints.ordens_servico import listar_ordens, listar_grupos_cobranca, gerar_relatorio_pendencias_pdf
from fastapi import HTTPException
from app.models.ordem_servico import OrdemServico
from app.models.paciente import Paciente
from app.models.tutor import Tutor
from app.models.clinica import Clinica
from app.models.servico import Servico


class OrdensBuscaResumoTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        for model in (Tutor, Paciente, Clinica, Servico, OrdemServico):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            Tutor(id=1, nome="Pessoa teste"),
            Paciente(id=1, nome="Animal teste", tutor_id=1, especie="Canina"),
            Clinica(id=1, nome="Unidade teste"),
            Servico(id=1, nome="Servico teste"),
        ])
        self.db.flush()
        for i in range(1, 506):
            self.db.add(OrdemServico(
                id=i, numero_os="OS-100%_\\" if i == 1 else f"OS-{i}",
                agendamento_id=i, paciente_id=1 if i == 1 else 999,
                servico_id=1 if i == 1 else 999, clinica_id=1 if i == 1 else None,
                origem_atendimento="clinica_parceira" if i == 1 else "domiciliar",
                data_atendimento=datetime(2026, 9, 15), tipo_horario="comercial",
                valor_final=Decimal("10.01"),
                status="Pago" if i == 1 else "Cancelado" if i == 2 else "Pendente",
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def query(self, **kwargs):
        params = dict(tipo_horario=None, skip=0, limit=100, db=self.db, current_user=None)
        params.update(kwargs)
        return listar_ordens(**params)

    def test_old_contract_unchanged_and_stable_pages(self):
        first, second = self.query(), self.query(skip=100)
        self.assertEqual(set(first), {"total", "items"})
        self.assertEqual(first["total"], 505)
        self.assertEqual([r["id"] for r in first["items"]], list(range(505, 405, -1)))
        self.assertFalse({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})

    def test_pdf_remote_search_and_recipient_do_not_expand_scope(self):
        # '%' must not match all pending OS; clinic 1 must not leak into tutor groups.
        for filters in ({"search": "%"}, {"destinatario_chave": "clinica:1"}):
            with self.subTest(filters=filters), self.assertRaises(HTTPException) as raised:
                gerar_relatorio_pendencias_pdf(status="Pendente", tipo_horario=None,
                    db=self.db, current_user=None, **filters)
            self.assertEqual(raised.exception.status_code, 404)

    def test_deep_link_by_id_reaches_old_order_and_keeps_filters(self):
        result = self.query(os_id=1, incluir_resumo=True)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], 1)
        self.assertEqual(self.query(os_id=1, status="Pendente")["total"], 0)

    def test_search_full_base_and_all_visible_fields(self):
        for term in ("100%_\\", "animal TESTE", "pessoa teste", "unidade teste", "servico teste"):
            with self.subTest(term=term):
                result = self.query(search=term, incluir_resumo=True)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["items"][0]["id"], 1)
                self.assertEqual(result["resumo"]["valor_recebido"], 10.01)
        self.assertEqual(self.query(search=" atendimento domiciliar ")["total"], 504)

    def test_literal_wildcards_and_empty_search(self):
        for term in ("%", "_", "\\"):
            self.assertEqual(self.query(search=term)["total"], 1)
        self.assertEqual(self.query(search="   ")["total"], 505)

    def test_summary_independent_of_page_and_decimal_sum(self):
        expected = dict(pendentes=503, pagas=1, canceladas=1, valor_pendente=5035.03, valor_recebido=10.01)
        for skip in (0, 100, 500, 600):
            result = self.query(skip=skip, limit=10, incluir_resumo=True)
            self.assertEqual(result["resumo"], expected)
            self.assertEqual(result["total"], 505)
            self.assertLessEqual(len(result["items"]), 10)

    def test_filters_apply_to_items_count_and_summary(self):
        for filters in (
            {"clinica_id": 1}, {"servico_id": 1}, {"status": "Pago"},
            {"origem_atendimento": "clinica_parceira"},
            {"search": "animal", "tipo_horario": "comercial", "data_inicio": "2026-09-15", "data_fim": "2026-09-15"},
        ):
            with self.subTest(filters=filters):
                result = self.query(**filters, incluir_resumo=True)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["resumo"]["pendentes"], 0)
                self.assertEqual(result["resumo"]["valor_recebido"], 10.01)
        for filters in ({"search": "animal", "status": "Pendente"}, {"data_inicio": "2026-09-16"}, {"data_fim": "2026-09-14"}):
            result = self.query(**filters, incluir_resumo=True)
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["items"], [])
            self.assertTrue(all(v == 0 for v in result["resumo"].values()))

    def test_two_reads_no_n_plus_one(self):
        statements = []
        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            self.query(incluir_resumo=True)
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 2)
        self.assertTrue(all(s.lstrip().upper().startswith("SELECT") for s in statements))

    def groups(self, **kwargs):
        params = dict(tipo_horario=None, skip=0, limit=50, db=self.db, current_user=None)
        params.update(kwargs)
        return listar_grupos_cobranca(**params)

    def test_group_totals_complete_even_with_one_group_per_page(self):
        first, second = self.groups(limit=1), self.groups(skip=1, limit=1)
        self.assertEqual(first["total"], 2)
        self.assertEqual(first["total_os"], 504)
        self.assertEqual(first["total_pendente"], 5035.03)
        self.assertEqual(first["items"][0]["quantidade_os"], 503)
        self.assertEqual(first["items"][0]["total_pendente"], 5035.03)
        self.assertEqual(second["items"][0]["chave"], "clinica:1")
        self.assertEqual(second["items"][0]["quantidade_total"], 1)
        self.assertEqual(second["total_pendente"], first["total_pendente"])
        self.assertEqual(self.groups(skip=100)["items"], [])

    def test_group_detail_matches_summary_without_cancelled_orders(self):
        group = self.groups()["items"][0]
        detail = self.query(destinatario_chave=group["chave"], incluir_resumo=True, skip=500)
        self.assertEqual(detail["total"], group["quantidade_total"])
        self.assertEqual(len(detail["items"]), 3)
        self.assertEqual(detail["resumo"]["valor_pendente"], group["total_pendente"])
        self.assertEqual(self.query(destinatario_chave="clinica:999")["total"], 0)

    def test_recipient_keys_separate_clinic_and_tutor_with_same_id(self):
        os = self.db.get(OrdemServico, 3)
        os.paciente_id = 1
        self.db.commit()
        groups = {g["chave"]: g for g in self.groups()["items"]}
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups["tutor:1"]["nome_destinatario"], "Pessoa teste")
        self.assertEqual(groups["clinica:1"]["nome_destinatario"], "Unidade teste")
        self.assertEqual(self.query(destinatario_chave="tutor:1")["items"][0]["id"], 3)

    def test_group_filters_and_empty_results(self):
        for filters in ({"search": "Animal"}, {"clinica_id": 1}, {"status": "Pago"}):
            result = self.groups(**filters)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["total_os"], 1)
            self.assertEqual(result["total_pendente"], 0)
        for filters in ({"status": "Cancelado"}, {"search": "inexistente"}, {"data_inicio": "2026-09-16"}):
            result = self.groups(**filters)
            self.assertEqual(result, dict(total=0, total_os=0, total_pendente=0.0, pendentes=0, items=[]))

    def test_group_queries_bounded_and_do_not_load_individual_orders(self):
        statements = []
        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            self.groups(limit=1)
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 2)
        self.assertTrue(all("GROUP BY" in s for s in statements))
        self.assertFalse(any("tutor_telefone" in s or "observacoes" in s for s in statements))


if __name__ == "__main__":
    unittest.main()
