"""Fan-out de `/ws/control`.

Serializa `{ type: STATE, state, progress, message, cacheHit }` y lo
envía a todos los sockets. No interpreta el payload. El RTP no pasa por
aquí.

`_lock` cubre el set de clientes. `broadcast` copia la lista bajo el lock
y hace `send_text` fuera, para no bloquear `connect`/`disconnect`. Los
sockets que fallan se descartan en un segundo acquire.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("game-station.hub")


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        log.info("control clients=%s", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        message = json.dumps(payload)
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
