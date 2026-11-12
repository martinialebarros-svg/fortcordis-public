"""Agenda rules must not transfer document assets or retain stale settings."""
import json
import os
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "agenda-projection-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.models.configuracao import Configuracao


class AgendaConfigurationProjectionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Configuracao.__table__.create(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_rules_do_not_select_binary_assets_or_unrelated_configuration(self):
        weekly = json.dumps({"segunda": {"ativo": True, "inicio": "09:00", "fim": "17:00"}})
        holidays = json.dumps([{"data": "2026-12-25", "nome": "Feriado"}])
        exceptions = json.dumps([{"data": "2026-10-26", "ativo": False}])
        with self.factory() as db:
            db.add(Configuracao(
                logomarca_dados=b"l" * 569017,
                assinatura_dados=b"s" * 60447,
                agenda_semanal=weekly,
                agenda_feriados=holidays,
                agenda_excecoes=exceptions,
            ))
            db.commit()
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lower())
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with self.factory() as db:
                actual = agenda._obter_regras_agenda(db)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 1)
        self.assertNotIn("logomarca_dados", statements[0])
        self.assertNotIn("assinatura_dados", statements[0])
        self.assertNotIn("texto_cabecalho_laudo", statements[0])
        self.assertEqual(actual, (
            agenda.carregar_agenda_semanal(weekly),
            agenda.carregar_agenda_feriados(holidays),
            agenda.carregar_agenda_excecoes(exceptions),
        ))

    def test_defaults_when_configuration_absent_or_empty_are_preserved(self):
        expected = (
            agenda.carregar_agenda_semanal(None),
            agenda.carregar_agenda_feriados(None),
            agenda.carregar_agenda_excecoes(None),
        )
        with self.factory() as db:
            self.assertEqual(agenda._obter_regras_agenda(db), expected)
            db.add(Configuracao())
            db.commit()
            self.assertEqual(agenda._obter_regras_agenda(db), expected)

    def test_committed_rule_changes_are_seen_even_with_retained_orm_entity(self):
        with self.factory() as db:
            db.add(Configuracao())
            db.commit()
            retained = db.query(Configuracao).first()
            agenda._obter_regras_agenda(db)
            raw = json.dumps([{"data": "2026-12-25", "nome": "Atualizado"}])
            with self.engine.begin() as conn:
                conn.execute(update(Configuracao).values(agenda_feriados=raw))
            self.assertIsNone(retained.agenda_feriados)
            self.assertEqual(agenda._obter_regras_agenda(db)[1], agenda.carregar_agenda_feriados(raw))


if __name__ == "__main__":
    unittest.main()
