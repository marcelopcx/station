"""Máquina de estados de la estación.

Una instancia por proceso. Las transiciones se serializan con `asyncio.Lock`.
No construye SDP ni ICE: el video se delega en un `MediaSession`.

    IDLE ──prepare──► PREPARING ──(ticks de progress)──► READY ──launch──► PLAYING
      ▲                                                                      │
      └────────────────────────────── stop ──────────────────────────────────┘

`prepare`: 11 ticks × `prepare_step_s` emiten `progress` 0..100 por el Hub.
No hay I/O de filesystem. `version` y `source` del request no se leen aquí.

`launch`: solo desde `READY`. Pasa a `PLAYING` y después llama
`start_source()` para que el REST 200 ya permita abrir `/ws/webrtc`.

`stop`: cierra el peer y la fuente, cancela un prepare en vuelo, vuelve a
`IDLE`. El proceso uvicorn no termina.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Protocol

from fastapi import WebSocket

from controller.errors import GameNotReady, PrepareInProgress, StationBusy
from controller.hub import Hub
from controller.states import StationState
from controller.webrtc.signaling import ERROR_NOT_PLAYING, dumps_error

log = logging.getLogger("game-station.machine")


class MediaSession(Protocol):
    """Fuente + peer que consume `Station`.

    `start_source` es síncrono: `MediaPlayer` abre lavfi en el caller.
    `stop` / `attach` pueden await (`pc.close()`, loop de signaling).
    """

    def start_source(self) -> None: ...

    async def stop(self) -> None: ...

    async def attach(self, ws: WebSocket) -> None: ...


class Station:
    def __init__(
        self,
        hub: Hub,
        stream: MediaSession,
        station_id: str = "spark-1",
        prepare_step_s: float = 0.2,
    ) -> None:
        self._hub = hub
        self._stream = stream
        self.station_id = station_id
        self.state = StationState.IDLE
        self.game_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.progress = 0
        self._prepare_step_s = prepare_step_s
        self._lock = asyncio.Lock()
        self._prepare_task: Optional[asyncio.Task[None]] = None

    def snapshot(self) -> dict[str, Any]:
        """Body de `GET /health`. `progress` no va aquí; sale por `/ws/control`."""
        return {
            "status": "UP",
            "stationId": self.station_id,
            "state": self.state.value,
            "gameId": self.game_id,
            "sessionId": self.session_id,
            "cache": [],
        }

    def _event(self, state: StationState, progress: int, message: str) -> dict[str, Any]:
        return {
            "type": "STATE",
            "state": state.value,
            "progress": progress,
            "message": message,
            "cacheHit": False,
        }

    async def connect_control(self, ws: WebSocket) -> None:
        await self._hub.connect(ws)

    async def disconnect_control(self, ws: WebSocket) -> None:
        await self._hub.disconnect(ws)

    async def attach_webrtc(self, ws: WebSocket) -> None:
        """Entrada de `/ws/webrtc`.

        Sin `PLAYING` no se crea `RTCPeerConnection`: `ERROR NOT_PLAYING` y close.
        """
        if self.state != StationState.PLAYING:
            await ws.send_text(dumps_error(ERROR_NOT_PLAYING))
            await ws.close()
            return
        await self._stream.attach(ws)

    async def prepare(self, session_id: str, game_id: str) -> dict[str, Any]:
        async with self._lock:
            if self.state in (StationState.PREPARING, StationState.PLAYING):
                raise PrepareInProgress()
            if self._prepare_task and not self._prepare_task.done():
                self._prepare_task.cancel()
            self.state = StationState.PREPARING
            self.session_id = session_id
            self.game_id = game_id
            self.progress = 0
            self._prepare_task = asyncio.create_task(self._run_prepare())
        log.info("state=%s session=%s game=%s", self.state, session_id, game_id)
        await self._hub.broadcast(
            self._event(StationState.PREPARING, 0, "Copiando assets")
        )
        return {"sessionId": session_id, "state": StationState.PREPARING.value}

    async def _run_prepare(self) -> None:
        try:
            for step in range(0, 11):
                if self._prepare_step_s:
                    await asyncio.sleep(self._prepare_step_s)
                progress = step * 10
                async with self._lock:
                    if self.state != StationState.PREPARING:
                        return
                    self.progress = progress
                await self._hub.broadcast(
                    self._event(StationState.PREPARING, progress, "Copiando assets")
                )
            async with self._lock:
                self.state = StationState.READY
                self.progress = 100
            log.info("state=%s", self.state)
            await self._hub.broadcast(self._event(StationState.READY, 100, "Listo"))
        except asyncio.CancelledError:
            return

    async def launch(self, session_id: str, game_id: str) -> dict[str, Any]:
        async with self._lock:
            if self.state == StationState.PLAYING:
                raise StationBusy()
            if self.state != StationState.READY:
                raise GameNotReady()
            self.state = StationState.PLAYING
            self.session_id = session_id
            self.game_id = game_id
        log.info("state=%s", self.state)
        await self._hub.broadcast(self._event(StationState.PLAYING, 100, "En partida"))
        self._stream.start_source()
        return {"state": StationState.PLAYING.value, "wsUrl": "/ws/webrtc"}

    async def stop(self) -> None:
        await self._stream.stop()
        async with self._lock:
            task = self._prepare_task
            self._prepare_task = None
            self.state = StationState.IDLE
            self.game_id = None
            self.session_id = None
            self.progress = 0
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("state=%s", self.state)
        await self._hub.broadcast(self._event(StationState.IDLE, 0, "Libre"))
