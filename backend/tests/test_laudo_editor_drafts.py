"""Disposable SQLite/HTTP proofs for private new-echo editing workspaces."""

import copy
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "synthetic-draft-workspace-test-secret-123456789")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from app.api.v1.endpoints import laudo_editor_drafts
from app.core import security
from app.db.database import Base, get_db
from app.models.laudo import Exame, Laudo
from app.models.laudo_editor_draft import LaudoEditorDraft, LaudoEditorDraftRequest
from app.models.paciente import Paciente
from app.models.papel import Papel
from app.models.papel_permissao import PapelPermissao
from app.models.tutor import Tutor
from app.models.user import User
from app.services.laudo_editor_draft_service import _is_write_collision, validate_snapshot


def snapshot():
    return {
        "schema_version": 1, "editor": "new-echo",
        "paciente": {"id": 901, "nome": "TESTE SINTÉTICO", "especie": "Gato", "peso": "4,80"},
        "medidas": {"DIVEd": "19.55", "Onda_E": "0", "Onda_A": "", "E_A": None,
                    "Diastolica_ondas": "fundidas", "confirmed_unit_DIVEd": "mm",
                    "AE_Ao_metodo": "felino_2d_eixo_curto_diastole_inicial"},
        "qualitativa": {"funcao": "Texto literal.\nCom segunda linha e acentos."},
        "conteudo": {"conclusao": "RASCUNHO SINTÉTICO — NÃO EMITIR"},
        "imagens": [{"id": "preview-1", "tempId": 12, "nome": "teste.jpg", "uploaded": True,
                     "ordem": 0, "incluirNoPdf": False, "descricao": "Legenda literal"}],
        "sessionId": "image-session-synthetic", "aba": "qualitativa",
    }


class EditorDraftHTTPTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="echo-draft-http-")
        self.engine = create_engine(f"sqlite:///{self.directory.name}/test.db",
                                    connect_args={"check_same_thread": False, "timeout": 10})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        with self.sessions() as db:
            editor = Papel(id=1, nome="medico")
            reader = Papel(id=2, nome="leitor")
            admin = Papel(id=3, nome="admin")
            db.add_all([editor, reader, admin])
            db.add_all([
                User(id=1, nome="Synthetic editor", email="editor@example.invalid", ativo=1, papeis=[editor]),
                User(id=2, email="other@example.invalid", ativo=1, papeis=[editor]),
                User(id=3, email="reader@example.invalid", ativo=1, papeis=[reader]),
                User(id=4, email="inactive@example.invalid", ativo=0, papeis=[editor]),
                User(id=5, email="admin@example.invalid", ativo=1, papeis=[admin]),
            ])
            db.add_all([
                PapelPermissao(papel_id=1, modulo="laudos", visualizar=1, editar=1, excluir=0),
                PapelPermissao(papel_id=2, modulo="laudos", visualizar=1, editar=0, excluir=0),
            ])
            db.add(Tutor(id=901, nome="TESTE TUTOR PRESERVADO", ativo=1))
            db.add(Paciente(id=901, nome="TESTE PACIENTE PRESERVADO", especie="Felina", tutor_id=901,
                            peso_kg=4.8, ativo=1))
            db.add(Laudo(id=901, paciente_id=901, veterinario_id=1, tipo="ecocardiograma", titulo="TESTE EMITIDO",
                         descricao="Conteúdo emitido", diagnostico="Conclusão emitida", status="Finalizado"))
            db.add(Exame(id=901, paciente_id=901, laudo_id=901, tipo_exame="ecocardiograma", status="Concluido"))
            db.commit()

        def isolated_db():
            with self.sessions() as db:
                yield db

        self.app = FastAPI()
        self.app.include_router(laudo_editor_drafts.router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(self.app)
        self.auth = patch.object(security, "_decode_token_and_load_user",
                                 side_effect=lambda db, token: db.get(User, {
                                     "editor": 1, "other": 2, "reader": 3, "inactive": 4, "admin": 5,
                                 }[token]))
        self.auth.start()
        self.draft_id = str(uuid4())
        self.url = f"/api/v1/laudos/editor-drafts/{self.draft_id}"

    def tearDown(self):
        self.auth.stop()
        self.client.close()
        self.engine.dispose()
        self.directory.cleanup()

    @staticmethod
    def headers(token="editor"):
        ids = {"editor": 1, "other": 2, "reader": 3, "inactive": 4, "admin": 5}
        return {"Authorization": f"Bearer {token}", "X-Editor-Owner-Id": str(ids[token])} if token else {}

    def body(self, revision=0, *, request_id=None, content=None, context="new:agendamento:1766"):
        return {"expected_revision": revision, "request_id": request_id or str(uuid4()),
                "context_key": context, "snapshot": snapshot() if content is None else content}

    def save(self, body=None, token="editor"):
        return self.client.put(self.url, json=body or self.body(), headers=self.headers(token))

    def read(self, token="editor"):
        return self.client.get(self.url, headers=self.headers(token))

    def close(self, revision, request_id=None, token="editor"):
        return self.client.post(self.url + "/close", headers=self.headers(token),
                                json={"expected_revision": revision, "request_id": request_id or str(uuid4())})

    def all_non_workspace_data(self):
        """Every pre-existing table must stay byte/value-equivalent after autosave."""
        with self.engine.connect() as connection:
            return {table.name: [tuple(row) for row in connection.execute(select(table))]
                    for table in Base.metadata.sorted_tables
                    if not table.name.startswith("laudo_editor_draft")}

    def test_raw_roundtrip_preserves_clinical_literals_and_only_private_tables_change(self):
        original = self.all_non_workspace_data()
        payload = self.body()
        untouched = copy.deepcopy(payload)
        saved = self.save(payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        response = saved.json()
        self.assertEqual(set(response), {"draft_id", "revision", "context_key", "snapshot", "updated_at"})
        self.assertEqual(response["revision"], 1)
        self.assertEqual(response["snapshot"], payload["snapshot"])
        self.assertEqual(saved.headers["cache-control"], "no-store")
        self.assertEqual(self.read().headers["cache-control"], "no-store")
        self.assertEqual(self.read().json(), response)
        self.assertEqual(self.all_non_workspace_data(), original)
        self.assertEqual(payload, untouched)
        with self.sessions() as db:
            self.assertEqual(db.query(LaudoEditorDraft).count(), 1)
            self.assertEqual(db.query(LaudoEditorDraftRequest).count(), 1)

    def test_retry_is_idempotent_and_old_retry_does_not_rewind_a_newer_snapshot(self):
        first = self.body()
        initial = self.save(first).json()
        self.assertEqual(self.save(first).json(), initial)
        second = self.body(1)
        second["snapshot"]["conteudo"]["conclusao"] = "Segunda revisão literal"
        latest = self.save(second).json()
        self.assertEqual(latest["revision"], 2)
        self.assertEqual(self.save(first).json(), initial)
        self.assertEqual(self.read().json(), latest)
        with self.sessions() as db:
            self.assertEqual(db.query(LaudoEditorDraftRequest).count(), 2)

    def test_reused_request_id_with_different_content_or_revision_is_conflict(self):
        first = self.body()
        initial = self.save(first).json()
        for change in ("content", "revision", "context"):
            changed = copy.deepcopy(first)
            if change == "content":
                changed["snapshot"]["medidas"]["DIVEd"] = "999"
            elif change == "revision":
                changed["expected_revision"] = 1
            else:
                changed["context_key"] = "new:agendamento:999"
            with self.subTest(change=change):
                self.assertEqual(self.save(changed).status_code, 409)
        self.assertEqual(self.read().json(), initial)

    def test_stale_revision_unknown_revision_and_context_change_do_not_overwrite(self):
        self.assertEqual(self.save(self.body(3)).status_code, 409)
        first = self.save().json()
        for body in (self.body(0), self.body(20), self.body(1, context="new:other")):
            self.assertEqual(self.save(body).status_code, 409)
        self.assertEqual(self.read().json(), first)

    def test_two_tabs_same_revision_only_one_new_request_wins(self):
        self.save()
        barrier = threading.Barrier(2)

        def put_one(value):
            content = snapshot()
            content["medidas"]["DIVEd"] = value
            body = self.body(1, content=content)
            with TestClient(self.app) as client:
                barrier.wait(timeout=5)
                return client.put(self.url, json=body, headers=self.headers()).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(put_one, ("20", "21")))
        self.assertEqual(sorted(results), [200, 409])
        current = self.read().json()
        self.assertEqual(current["revision"], 2)
        self.assertIn(current["snapshot"]["medidas"]["DIVEd"], {"20", "21"})

    def test_same_uuid_is_private_per_author_including_admin(self):
        owner_result = self.save().json()
        for token in ("other", "reader", "admin"):
            with self.subTest(token=token):
                response = self.read(token)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("TESTE", response.text)
                self.assertEqual(self.close(1, token=token).status_code, 404 if token != "reader" else 403)
        other_content = snapshot()
        other_content["conteudo"]["conclusao"] = "Outro autor"
        other = self.save(self.body(content=other_content), token="other")
        self.assertEqual(other.status_code, 200)
        self.assertEqual(self.read().json(), owner_result)
        self.assertEqual(self.read("other").json()["snapshot"], other_content)

    def test_simultaneous_retry_returns_the_same_result_once(self):
        self.save()
        barrier = threading.Barrier(2)
        body = self.body(1)

        def put_same(_):
            with TestClient(self.app) as client:
                barrier.wait(timeout=5)
                response = client.put(self.url, json=body, headers=self.headers())
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(put_same, range(2)))
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(self.read().json()["revision"], 2)
        with self.sessions() as db:
            self.assertEqual(db.query(LaudoEditorDraftRequest).count(), 2)

    def test_real_auth_dependency_and_matrix_are_preserved(self):
        for route in self.app.routes:
            if getattr(route, "path", "").startswith("/api/v1/laudos/editor-drafts"):
                self.assertTrue(any(d.call is security.get_current_user for d in route.dependant.dependencies))
        self.assertEqual(self.read(None).status_code, 401)
        self.assertEqual(self.save(token=None).status_code, 401)
        self.assertEqual(self.save(token="inactive").status_code, 403)
        self.assertEqual(self.save(token="reader").status_code, 403)
        with self.sessions() as db:
            db.query(PapelPermissao).filter(PapelPermissao.papel_id == 1).update({"visualizar": 0})
            db.commit()
        self.assertEqual(self.read().status_code, 403)
        self.assertEqual(self.save().status_code, 200)

    def test_expected_owner_header_is_required_positive_and_does_not_grant_access(self):
        self.save()
        before = self.all_non_workspace_data()
        for expected_owner, status in ((None, 422), ("0", 422), ("-1", 422), ("invalid", 422), ("2", 403)):
            headers = {"Authorization": "Bearer editor"}
            if expected_owner is not None:
                headers["X-Editor-Owner-Id"] = expected_owner
            requests = (
                ("GET", self.url, None),
                ("PUT", self.url, self.body(1)),
                ("POST", self.url + "/close", {"expected_revision": 1, "request_id": str(uuid4())}),
            )
            for method, url, body in requests:
                with self.subTest(expected_owner=expected_owner, method=method):
                    response = self.client.request(method, url, headers=headers, json=body)
                    self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.read().json()["revision"], 1)
        self.assertEqual(self.all_non_workspace_data(), before)
        # Header alone never authenticates a request.
        self.assertEqual(self.client.get(self.url, headers={"X-Editor-Owner-Id": "1"}).status_code, 401)

    def test_changed_cookie_user_cannot_read_write_or_close_a_stale_open_editor(self):
        self.save()
        before = self.all_non_workspace_data()
        cookie_name = security.settings.AUTH_COOKIE_NAME
        headers = self.headers("editor")
        # A valid new cookie belongs to user2 while an old tab still has user1.
        with patch.object(security.settings, "AUTH_PROVIDER", "supabase"), \
                patch.object(laudo_editor_drafts, "get_editor_draft", side_effect=AssertionError("workspace read")), \
                patch.object(laudo_editor_drafts, "save_editor_draft", side_effect=AssertionError("workspace write")), \
                patch.object(laudo_editor_drafts, "close_editor_draft", side_effect=AssertionError("workspace close")):
            self.client.cookies.set(cookie_name, "other")
            try:
                for method, url, body in (
                    ("GET", self.url, None),
                    ("PUT", self.url, self.body(1)),
                    ("POST", self.url + "/close", {"expected_revision": 1, "request_id": str(uuid4())}),
                ):
                    with self.subTest(method=method):
                        response = self.client.request(method, url, headers=headers, json=body)
                        self.assertEqual(response.status_code, 403, response.text)
                        self.assertNotIn("TESTE", response.text)
            finally:
                self.client.cookies.clear()
        self.assertEqual(self.all_non_workspace_data(), before)
        self.assertEqual(self.read().json()["revision"], 1)
        with self.sessions() as db:
            self.assertEqual(db.query(LaudoEditorDraft).count(), 1)
            self.assertEqual(db.query(LaudoEditorDraftRequest).count(), 1)

    def test_soft_close_is_idempotent_preserves_snapshot_and_rejects_late_autosave(self):
        original = self.all_non_workspace_data()
        save_body = self.body()
        self.save(save_body)
        self.assertEqual(self.close(3).status_code, 409)
        closing_id = str(uuid4())
        closed = self.close(1, closing_id)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertTrue(closed.json()["closed"])
        self.assertEqual(closed.headers["cache-control"], "no-store")
        self.assertEqual(closed.json()["revision"], 2)
        self.assertEqual(self.close(1, closing_id).json(), closed.json())
        self.assertEqual(self.read().status_code, 410)
        self.assertEqual(self.save(save_body).status_code, 409)
        self.assertEqual(self.save(self.body(2)).status_code, 409)
        self.assertEqual(self.close(2).status_code, 409)
        self.assertEqual(self.close(2, closing_id).status_code, 409)
        with self.sessions() as db:
            record = db.query(LaudoEditorDraft).one()
            self.assertEqual(json.loads(record.snapshot_json), save_body["snapshot"])
            self.assertIsNotNone(record.closed_at)
        self.assertEqual(self.all_non_workspace_data(), original)

    def test_request_id_cannot_change_operation(self):
        saved_body = self.body()
        self.save(saved_body)
        self.assertEqual(self.close(1, saved_body["request_id"]).status_code, 409)
        self.assertEqual(self.read().status_code, 200)

    def test_snapshot_validation_rejects_files_credentials_size_depth_and_non_new_editors(self):
        cases = [
            ({"schema_version": 2, "editor": "new-echo"}, 422),
            ({"schema_version": True, "editor": "new-echo"}, 422),
            ({"schema_version": 1, "editor": "edit-echo"}, 422),
        ]
        for key, value in (
            ("file", {"name": "x.jpg"}), ("dataUrl", ""), ("access_token", "DO-NOT-ECHO-SECRET"),
            ("token", "DO-NOT-ECHO-SECRET"), ("authorization", "DO-NOT-ECHO-SECRET"),
            ("nested", {"cookie": "DO-NOT-ECHO-SECRET"}),
            ("text", "Bearer DO-NOT-ECHO-SECRET"),
            ("text", "eyJ0ZXN0.c3ludGhldGlj.c2lnbmF0dXJl"),
            ("text", "sk-proj-synthetic-not-a-real-key"),
            ("preview", "data:image/png;base64,AAAA"), ("preview", "blob:https://example.invalid/test"),
            ("nested", {"lastModified": 12, "name": "a.jpg", "size": 3, "type": "image/jpeg"}),
        ):
            content = snapshot()
            content[key] = value
            cases.append((content, 422))
        content = snapshot()
        content["oversize"] = "á" * (256 * 1024)
        cases.append((content, 413))
        content = snapshot()
        child = content
        for _ in range(22):
            child["child"] = {}
            child = child["child"]
        cases.append((content, 422))
        for content, status_code in cases:
            with self.subTest(content_keys=list(content), expected=status_code):
                response = self.save(self.body(content=content))
                self.assertEqual(response.status_code, status_code, response.text[:500])
                self.assertNotIn("DO-NOT-ECHO-SECRET", response.text)
        self.assertEqual(self.read().status_code, 404)

    def test_snapshot_key_and_node_limits_fail_before_persistence(self):
        for content in (
            {**snapshot(), "many": {f"k{index}": "" for index in range(10_001)}},
            {**snapshot(), "many": [0] * 20_001},
        ):
            self.assertEqual(self.save(self.body(content=content)).status_code, 422)
        self.assertEqual(self.read().status_code, 404)

    def test_non_utf8_or_non_finite_snapshot_is_a_safe_validation_error(self):
        for value in ("\ud800", float("inf"), float("nan")):
            content = snapshot()
            content["invalid"] = value
            with self.subTest(value=repr(value)), self.assertRaises(Exception) as raised:
                validate_snapshot(content)
            self.assertEqual(raised.exception.status_code, 422)

    def test_database_outage_is_not_misreported_as_another_tab(self):
        error = OperationalError("synthetic", {}, RuntimeError("synthetic database unavailable"))
        self.assertFalse(_is_write_collision(error))
        with patch("app.services.laudo_editor_draft_service._owned", side_effect=[None]), \
                patch("sqlalchemy.orm.Session.flush", side_effect=error):
            result = self.save()
        self.assertEqual(result.status_code, 503, result.text)
        self.assertNotIn("synthetic", result.text)
        self.assertEqual(self.read().status_code, 404)

    def test_transport_metadata_is_strict_and_snapshot_validation_never_logs_values(self):
        for key, value in (("expected_revision", True), ("expected_revision", -1),
                           ("expected_revision", "0"), ("context_key", "patient name"),
                           ("context_key", "x" * 201), ("request_id", "invalid")):
            with self.subTest(key=key, value=value):
                body = self.body()
                body[key] = value
                self.assertEqual(self.save(body).status_code, 422)
        body = self.body()
        body["status"] = "Finalizado"
        self.assertEqual(self.save(body).status_code, 422)
        bad_url = "/api/v1/laudos/editor-drafts/not-a-uuid"
        self.assertEqual(self.client.get(bad_url, headers=self.headers()).status_code, 422)


class EditorDraftMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = BACKEND / "migrations/versions/20261101_105_laudo_editor_drafts.py"
        spec = importlib.util.spec_from_file_location("echo_editor_draft_migration", path)
        cls.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.migration)

    def test_upgrade_is_idempotent_additive_and_preserves_clinical_tables(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE laudos (id INTEGER PRIMARY KEY, descricao TEXT)"))
                connection.execute(text("INSERT INTO laudos VALUES (1, 'PRESERVADO')"))
                self.migration.upgrade(connection, "sqlite")
                values = {"owner_id": 7, "draft_id": str(uuid4()), "context_key": "new:standalone",
                          "revision": 1, "snapshot_json": json.dumps(snapshot()), "updated_at": datetime(2026, 11, 1)}
                row_id = connection.execute(LaudoEditorDraft.__table__.insert().values(**values)).inserted_primary_key[0]
                self.migration.upgrade(connection, "sqlite")
                self.assertEqual(connection.execute(text("SELECT descricao FROM laudos WHERE id=1")).scalar(), "PRESERVADO")
                self.assertEqual(connection.execute(select(LaudoEditorDraft.__table__.c.id)).scalar(), row_id)
                constraints = inspect(connection).get_unique_constraints("laudo_editor_drafts")
                self.assertTrue(any(item["column_names"] == ["owner_id", "draft_id"] for item in constraints))
                self.assertEqual(set(inspect(connection).get_table_names()),
                                 {"laudos", "laudo_editor_drafts", "laudo_editor_draft_requests"})
        finally:
            engine.dispose()

    def test_postgresql_migration_denies_direct_public_and_client_role_access(self):
        connection = Mock()
        connection.execute.return_value.scalar.return_value = True
        with patch.object(LaudoEditorDraft.__table__, "create") as create_draft, \
                patch.object(LaudoEditorDraftRequest.__table__, "create") as create_receipt:
            self.migration.upgrade(connection, "postgresql")
        create_draft.assert_called_once_with(connection, checkfirst=True)
        create_receipt.assert_called_once_with(connection, checkfirst=True)
        statements = [str(call.args[0]) for call in connection.execute.call_args_list]
        for table in ("laudo_editor_drafts", "laudo_editor_draft_requests"):
            self.assertIn(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY', statements)
            self.assertIn(f'REVOKE ALL ON "{table}" FROM PUBLIC', statements)
            for role in ("anon", "authenticated"):
                self.assertIn(f'REVOKE ALL ON "{table}" FROM "{role}"', statements)
        self.assertFalse(any("GRANT " in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()
