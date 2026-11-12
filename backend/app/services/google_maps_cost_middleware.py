"""Claim a one-use consent before any endpoint business side effect."""
import json

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.security import get_current_user
from app.db.database import SessionLocal
from app.services.google_maps_cost_control import (
    GoogleMapsCostBlocked, bind_execution, claim_execution, finish_execution,
    identify_action, reset_execution, current_agenda_business_session,
)


def _authenticate(request):
    with SessionLocal() as session:
        # Full current-user and permissions-matrix checks, not just a valid JWT.
        return get_current_user(request=request, token=None, db=session).id


def _estimate_agenda_action(action, body):
    from app.services.google_maps_agenda_estimate import SEARCH_MODELS, estimate_search
    if action not in SEARCH_MODELS:
        return None
    # The endpoint already owns a session. A second checkout from its pool can
    # deadlock concurrent searches when each request holds the last free slot.
    session = current_agenda_business_session()
    if session is None:
        raise GoogleMapsCostBlocked('estimate_unavailable', status_code=503)
    with session.no_autoflush:
        return estimate_search(session, action, body)


class GoogleMapsCostMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or identify_action(scope["method"], scope["path"]) is None:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            user_id = await run_in_threadpool(_authenticate, request)
            messages, chunks, size = [], [], 0
            while True:
                message = await receive()
                messages.append(message)
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                chunks.append(chunk)
                size += len(chunk)
                if size > 2_000_000:
                    raise HTTPException(413, "Ação excede o tamanho máximo para confirmação de custo.")
                if not message.get("more_body", False):
                    break
            raw_body = b"".join(chunks)
            try:
                body = json.loads(raw_body) if raw_body else None
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(422, "A confirmação de custo requer uma ação JSON válida.") from None
            async def replay_receive():
                return messages.pop(0) if messages else await receive()

            query = scope.get("query_string", b"").decode("utf-8")
            if identify_action(scope["method"], scope["path"], query, body) is None:
                await self.app(scope, replay_receive, send)
                return
            execution = await run_in_threadpool(
                claim_execution, user_id, request.headers.get("X-Google-Maps-Action"),
                scope["method"], scope["path"], query, body,
            )
            execution.estimate_loader = lambda: _estimate_agenda_action(execution.request_action, body)
        except HTTPException as exc:
            await JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)(scope, receive, send)
            return

        token = bind_execution(execution)
        finished = False

        async def end_before_background(message):
            nonlocal finished
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                # A task spawned after the response must obtain its own automatic
                # policy; inherited ContextVars cannot extend user confirmation.
                try:
                    await run_in_threadpool(finish_execution, execution)
                except GoogleMapsCostBlocked:
                    # The local scope is closed first even if the durable close
                    # fails; the persisted one-use claim remains non-replayable.
                    pass
                finished = True
            await send(message)

        try:
            await self.app(scope, replay_receive, end_before_background)
        finally:
            reset_execution(token)
            if not finished:
                try:
                    await run_in_threadpool(finish_execution, execution)
                except GoogleMapsCostBlocked:
                    # Claim is already durable and cannot be replayed. Its finite
                    # deadline still applies when the ledger is unavailable.
                    pass
