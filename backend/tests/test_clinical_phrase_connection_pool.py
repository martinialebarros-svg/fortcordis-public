"""Regression proof using occupied pools and the real phrase HTTP handler."""
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "clinical-phrase-pool-test-secret-key-1234567890")

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from app.api.v1.endpoints import atendimento
from app.models.frase_atendimento_clinico import FraseAtendimentoClinico as Phrase
from app.services import clinical_phrase_service as service


class ClinicalPhraseConnectionPoolTest(unittest.TestCase):
    """A stage canary may inject an engine isolated from operational schemas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = getattr(self, "_isolated_engine", None) or create_engine(
            "sqlite:///" + str(Path(self.tmp.name) / "phrases.db"),
            connect_args={"check_same_thread": False}, poolclass=QueuePool,
            pool_size=3, max_overflow=0, pool_timeout=0.3,
        )
        self.owns_engine = not hasattr(self, "_isolated_engine")
        self.checked_out = self.peak = self.checkouts = self.dml = 0
        self.lock = threading.Lock()

        def checkout(*_):
            with self.lock:
                self.checked_out += 1
                self.checkouts += 1
                self.peak = max(self.peak, self.checked_out)

        def checkin(*_):
            with self.lock:
                self.checked_out -= 1

        def sql(_conn, _cursor, statement, *_):
            if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                with self.lock:
                    self.dml += 1

        self.listeners = [("checkout", checkout), ("checkin", checkin), ("before_cursor_execute", sql)]
        for name, fn in self.listeners:
            event.listen(self.engine, name, fn)
        Phrase.__table__.create(self.engine)
        self.payload = {"version": "1.0", "frases": [
            {"secao": "anamnese", "titulo": "Fixture A", "texto": "Texto sintético A.", "ordem": 10},
            {"secao": "anamnese", "titulo": "Fixture B", "texto": "Texto sintético B.", "ordem": 20},
            {"secao": "observacoes", "titulo": "Fixture C", "texto": "Texto sintético C.", "ordem": 30, "ativo": 0},
        ]}
        fixture = Path(self.tmp.name) / "phrases.json"
        fixture.write_text(json.dumps(self.payload), encoding="utf-8")
        self.file_patch = patch.object(service, "CLINICAL_PHRASES_FILE", fixture)
        self.file_patch.start()
        # Preseed explicitly; the concurrent GETs must perform zero DML.
        with Session(self.engine) as db:
            db.add_all([Phrase(**row, parametrizacao_origem="seed") for row in self.payload["frases"]])
            db.commit()
        self.reset_counts()

    def reset_counts(self):
        self.assertEqual(self.checked_out, 0)
        self.peak = self.checkouts = self.dml = 0

    def tearDown(self):
        try:
            self.file_patch.stop()
            self.assertEqual(self.engine.pool.checkedout(), 0)
            for name, fn in self.listeners:
                event.remove(self.engine, name, fn)
        finally:
            if self.owns_engine:
                self.engine.dispose()
            self.tmp.cleanup()

    def test_occupied_pool_reuses_session_and_preserves_query_contract(self):
        # Reserve all other slots: authentication already owns the last one.
        with self.engine.connect(), self.engine.connect(), Session(self.engine, autoflush=False) as db:
            db.execute(text("SELECT 1"))
            before = self.checkouts
            self.assertFalse(service._table_exists(db, "synthetic_absent_table"))
            context = service.montar_contexto_frases_clinicas(db, secao="anamnese", search="Fixture", skip=1, limit=1)
            self.assertEqual(context["total"], 2)
            self.assertEqual(context["frases"][0]["titulo"], "Fixture B")
            self.assertEqual(context["frases"][0]["texto"], "Texto sintético B.")
            self.assertEqual(len(service.listar_frases_clinicas(db)), 2)
            self.assertEqual(len(service.listar_frases_clinicas(db, include_inactive=True)), 3)
            self.assertFalse(context["seed"]["seeded"])
            self.assertEqual(self.checkouts, before)
        self.assertEqual(self.dml, 0)

    def test_read_does_not_commit_or_flush_pending_work(self):
        with Session(self.engine, autoflush=False) as db:
            pending = Phrase(secao="observacoes", titulo="Pending", texto="Synthetic pending")
            db.add(pending)
            db.execute(text("SELECT 1"))
            self.assertEqual(service.montar_contexto_frases_clinicas(db)["total"], 2)
            self.assertIsNone(pending.id)
            self.assertTrue(db.in_transaction())
            db.rollback()
            self.assertEqual(db.query(Phrase).count(), 3)
        self.assertEqual(self.dml, 0)

    def test_three_authenticated_requests_with_three_connections(self):
        barrier = threading.Barrier(3)
        app = FastAPI()
        app.include_router(atendimento.router, prefix="/atendimentos")

        def db_dependency():
            with Session(self.engine, autoflush=False) as db:
                yield db

        def authenticated(db=Depends(atendimento.get_db)):
            db.execute(text("SELECT 1"))
            # Every request holds its connection before any handler may start.
            barrier.wait(timeout=10)
            return SimpleNamespace(id=-1)

        app.dependency_overrides[atendimento.get_db] = db_dependency
        app.dependency_overrides[atendimento.get_current_user] = authenticated

        def request(index):
            with TestClient(app) as client:
                response = client.get("/atendimentos/frases-clinicas", params={"secao": "anamnese", "skip": index % 2, "limit": 1})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["total"], 2)
                self.assertEqual(body["frases"][0]["titulo"], "Fixture " + ("A" if index % 2 == 0 else "B"))
                return response.status_code

        with ThreadPoolExecutor(max_workers=3) as workers:
            self.assertEqual(list(workers.map(request, range(3))), [200, 200, 200])
        self.assertEqual(self.peak, 3)
        self.assertEqual(self.checkouts, 3)
        self.assertEqual(self.dml, 0)
        self.assertEqual(self.checked_out, 0)
        self.proof = {"requests": 3, "statuses": [200, 200, 200], "peak_connections": self.peak,
                      "checkouts": self.checkouts, "returned_connections": 3, "read_dml": self.dml}


if __name__ == "__main__":
    unittest.main()
