import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "agenda-stream-test-secret-key-1234567890")

from app.api.v1.endpoints import agenda
from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.papel import Papel, usuario_papel
from app.models.papel_permissao import PapelPermissao
from app.models.user import User


class AgendaStreamConnectionPoolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.tmpdir.name) / 'agenda-stream.db'}",
            connect_args={"check_same_thread": False},
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.1,
        )
        self.factory = sessionmaker(bind=self.engine, autoflush=False)
        for table in (User.__table__, Papel.__table__, usuario_papel, PapelPermissao.__table__):
            table.create(self.engine)

        with self.factory() as db:
            allowed_role = Papel(nome="secretaria")
            denied_role = Papel(nome="sem-acesso")
            allowed = User(email="agenda@example.test", nome="Agenda", ativo=1, papeis=[allowed_role])
            denied = User(email="negado@example.test", nome="Negado", ativo=1, papeis=[denied_role])
            inactive = User(email="inativo@example.test", nome="Inativo", ativo=0, papeis=[allowed_role])
            db.add_all([allowed, denied, inactive])
            db.flush()
            self.user_id = allowed.id
            db.add(PapelPermissao(papel_id=allowed_role.id, modulo="agenda", visualizar=1))
            db.commit()

        def override_get_db():
            with self.factory() as db:
                yield db

        self.app = FastAPI()
        self.app.dependency_overrides[get_db] = override_get_db

        @self.app.get("/api/v1/agenda/pool-probe")
        def probe(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
            return {"user_id": user.id, "query": db.execute(text("SELECT 1")).scalar_one()}

        self.app.include_router(agenda.router, prefix="/api/v1/agenda")

    def tearDown(self):
        self.engine.dispose()
        self.tmpdir.cleanup()

    def _token(self, email="agenda@example.test"):
        return jwt.encode({"sub": email}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    def _stream_scope(self):
        return {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/api/v1/agenda/stream",
            "raw_path": b"/api/v1/agenda/stream", "query_string": b"", "root_path": "",
            "headers": [(b"authorization", f"Bearer {self._token()}".encode())],
            "client": ("127.0.0.1", 12345), "server": ("test", 80),
        }

    async def test_active_stream_releases_connection_and_keeps_events_working(self):
        incoming = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        connected = asyncio.Event()
        advance = asyncio.Event()
        updated = asyncio.Event()
        frames = []

        async def send(message):
            if message["type"] != "http.response.body" or not message.get("body"):
                return
            body = message["body"].decode()
            frames.append(body)
            if body.startswith("event: connected"):
                connected.set()
                await advance.wait()
            if body.startswith("event: agenda_update"):
                updated.set()
                # Keep the stream active until the test disconnects the client.
                await asyncio.Event().wait()

        subscribers_before = len(agenda.agenda_realtime_manager._subscribers)
        stream = asyncio.create_task(self.app(self._stream_scope(), incoming.get, send))
        try:
            await asyncio.wait_for(connected.wait(), timeout=3)
            self.assertFalse(stream.done())
            self.assertEqual(self.engine.pool.checkedout(), 0)
            connected_payload = json.loads(frames[0].split("data: ", 1)[1])
            self.assertEqual(connected_payload["user_id"], self.user_id)

            async with httpx.AsyncClient(app=self.app, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/agenda/pool-probe",
                    headers={"Authorization": f"Bearer {self._token()}"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"user_id": self.user_id, "query": 1})
            self.assertEqual(self.engine.pool.checkedout(), 0)

            agenda.agenda_realtime_manager.publish("updated", 123)
            advance.set()
            await asyncio.wait_for(updated.wait(), timeout=3)
            update_payload = json.loads(frames[1].split("data: ", 1)[1])
            self.assertEqual(update_payload["agendamento_id"], 123)
            self.assertEqual(update_payload["action"], "updated")
            self.assertEqual(self.engine.pool.checkedout(), 0)
        finally:
            await incoming.put({"type": "http.disconnect"})
            advance.set()
            await asyncio.wait_for(stream, timeout=3)
        self.assertEqual(len(agenda.agenda_realtime_manager._subscribers), subscribers_before)
        self.assertEqual(self.engine.pool.checkedout(), 0)

    async def test_disconnect_during_connected_event_removes_subscriber(self):
        incoming = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        connected = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body", b"").startswith(b"event: connected"):
                connected.set()
                await asyncio.Event().wait()

        subscribers_before = len(agenda.agenda_realtime_manager._subscribers)
        stream = asyncio.create_task(self.app(self._stream_scope(), incoming.get, send))
        try:
            await asyncio.wait_for(connected.wait(), timeout=3)
            self.assertEqual(self.engine.pool.checkedout(), 0)
            self.assertEqual(len(agenda.agenda_realtime_manager._subscribers), subscribers_before + 1)
        finally:
            await incoming.put({"type": "http.disconnect"})
            await asyncio.wait_for(stream, timeout=3)
        self.assertEqual(len(agenda.agenda_realtime_manager._subscribers), subscribers_before)
        self.assertEqual(self.engine.pool.checkedout(), 0)

    async def test_stream_preserves_authentication_active_user_and_permission_checks(self):
        cases = [
            ({}, 401),
            ({"Authorization": "Bearer invalid"}, 401),
            ({"Authorization": f"Bearer {self._token('inativo@example.test')}"}, 403),
            ({"Authorization": f"Bearer {self._token('negado@example.test')}"}, 403),
        ]
        subscribers_before = len(agenda.agenda_realtime_manager._subscribers)
        async with httpx.AsyncClient(app=self.app, base_url="http://test") as client:
            for headers, status_code in cases:
                with self.subTest(status_code=status_code, headers_present=bool(headers)):
                    response = await client.get("/api/v1/agenda/stream", headers=headers)
                    self.assertEqual(response.status_code, status_code)
                    self.assertEqual(self.engine.pool.checkedout(), 0)
                    self.assertEqual(len(agenda.agenda_realtime_manager._subscribers), subscribers_before)


if __name__ == "__main__":
    unittest.main()
