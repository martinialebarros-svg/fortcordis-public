from __future__ import annotations

import json
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any


class AgendaRealtimeManager:
    """Thread-safe pub/sub manager for agenda realtime updates."""

    def __init__(self) -> None:
        self._subscribers: list[Queue[str]] = []
        self._lock = Lock()

    def subscribe(self) -> Queue[str]:
        queue: Queue[str] = Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: Queue[str]) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def publish(self, action: str, agendamento_id: int, data: dict[str, Any] | None = None) -> None:
        payload = {
            "type": "agenda_update",
            "action": str(action or "").strip() or "updated",
            "agendamento_id": int(agendamento_id),
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        encoded = json.dumps(payload, ensure_ascii=False)

        with self._lock:
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(encoded)
            except Full:
                try:
                    subscriber.get_nowait()
                except Empty:
                    pass
                try:
                    subscriber.put_nowait(encoded)
                except Full:
                    # Skip if still full.
                    pass


agenda_realtime_manager = AgendaRealtimeManager()
