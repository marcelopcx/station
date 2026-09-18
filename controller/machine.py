"""Máquina de estados de la estación.

Una instancia por proceso. Las transiciones se serializan con `asyncio.Lock`.
No construye SDP ni ICE: el video se delega en un `MediaSession`.

    IDLE ──prepare──► PREPARING ──(copia / cache)──► READY ──launch──► PLAYING
      ▲                    │                                            │
      │                    └── FAILED ── stop / timeout ────────────────┤
      └────────────────────────────── stop ─────────────────────────────┘

`prepare` (S4) copia `/library` → `/cache` y verifica checksum. `version` y
`source` sí se leen. Checksum malo → ERROR + FAILED.

`launch`: solo desde `READY`. Pasa a `PLAYING` y después llama
`await start_source(game_id)`. Si la fuente falla, `stop()` vuelve a `IDLE`.

`stop`: cierra el peer y la fuente, cancela un prepare en vuelo, vuelve a
`IDLE`. El proceso uvicorn no termina.

S5: sin paquetes `input` `idle_timeout_s` → `stop` interno. `/health` declara
el encoder.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional, Protocol

from fastapi import WebSocket

from controller.errors import GameNotReady, PrepareInProgress, StationBusy
from controller.hub import Hub
from controller.models import Source
from controller.prepare import FilePreparer, PrepareError, list_cache
from controller.states import StationState
from controller.webrtc.signaling import ERROR_NOT_PLAYING, dumps_error

log = logging.getLogger("game-station.machine")

_LIBRARY = os.environ.get("LIBRARY_ROOT", "/opt/station-library")
_CACHE = os.environ.get("CACHE_ROOT", "/cache")


class MediaSession(Protocol):
    """Fuente + peer que consume `Station`.

    `start_source` arranca display/juego/captura (puede await).
    `stop` / `attach` pueden await (`pc.close()`, loop de signaling).
    """

    async def start_source(self, game_id: str) -> None: ...

    async def stop(self) -> None: ...

    async def attach(self, ws: WebSocket) -> None: ...

    def encoder_name(self) -> Optional[str]: ...

    def last_input_monotonic(self) -> Optional[float]: ...


class Station:
    def __init__(
        self,
        hub: Hub,
        stream: MediaSession,
        station_id: str = "spark-1",
        prepare_step_s: float = 0.2,
        library_root: str | os.PathLike[str] | None = None,
        cache_root: str | os.PathLike[str] | None = None,
        idle_timeout_s: float | None = None,
        failed_idle_s: float = 2.0,
        preparer: FilePreparer | None = None,
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
        self._idle_task: Optional[asyncio.Task[None]] = None
        self._failed_task: Optional[asyncio.Task[None]] = None
        self._idle_timeout_s = (
            float(os.environ.get("IDLE_TIMEOUT_S", "300"))
            if idle_timeout_s is None
            else idle_timeout_s
        )
        self._failed_idle_s = failed_idle_s
        self._cache_root = os.fspath(cache_root or _CACHE)
        self._preparer = preparer or FilePreparer(
            library_root or _LIBRARY, self._cache_root
        )
        self._last_cache_hit = False
        self._playing_since: Optional[float] = None

    def snapshot(self) -> dict[str, Any]:
        """Body de `GET /health`. `progress` no va aquí; sale por `/ws/control`."""
        encoder = None
        if self.state == StationState.PLAYING:
            encoder = self._stream.encoder_name()
        return {
            "status": "UP",
            "stationId": self.station_id,
            "state": self.state.value,
            "gameId": self.game_id,
            "sessionId": self.session_id,
            "encoder": encoder,
            "cache": list_cache(self._preparer.cache_root),
        }

    def _event(
        self,
        state: StationState,
        progress: int,
        message: str,
        cache_hit: bool | None = None,
    ) -> dict[str, Any]:
        hit = self._last_cache_hit if cache_hit is None else cache_hit
        return {
            "type": "STATE",
            "state": state.value,
            "progress": progress,
            "message": message,
            "cacheHit": hit,
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

    async def prepare(
        self,
        session_id: str,
        game_id: str,
        version: str = "1.0.0",
        source: Source | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            if self.state in (StationState.PREPARING, StationState.PLAYING):
                raise PrepareInProgress()
            self._cancel_task(self._prepare_task)
            self._cancel_task(self._failed_task)
            self._failed_task = None
            self.state = StationState.PREPARING
            self.session_id = session_id
            self.game_id = game_id
            self.progress = 0
            self._last_cache_hit = False
            body = source or Source(
                type="local",
                path=f"/library/{game_id}/{version}",
                checksum="sha256:00",
            )
            self._prepare_task = asyncio.create_task(
                self._run_prepare(session_id, game_id, version, body)
            )
        log.info(
            "state=%s sessionId=%s game=%s version=%s",
            self.state.value,
            session_id,
            game_id,
            version,
        )
        await self._hub.broadcast(
            self._event(StationState.PREPARING, 0, "Copiando assets", False)
        )
        return {"sessionId": session_id, "state": StationState.PREPARING.value}

    async def _run_prepare(
        self, session_id: str, game_id: str, version: str, source: Source
    ) -> None:
        ticks: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_progress(pct: int, message: str) -> None:
            loop.call_soon_threadsafe(ticks.put_nowait, (pct, message))

        async def pump() -> None:
            while True:
                item = await ticks.get()
                if item is None:
                    return
                await self._emit_prepare_progress(item[0], item[1])

        pump_task = asyncio.create_task(pump())
        try:
            if self._prepare_step_s:
                await asyncio.sleep(self._prepare_step_s)
            outcome = await asyncio.to_thread(
                self._preparer.run, game_id, version, source, on_progress
            )
            await ticks.put(None)
            await pump_task
            async with self._lock:
                if self.state != StationState.PREPARING:
                    return
                self.state = StationState.READY
                self.progress = 100
                self._last_cache_hit = outcome.cache_hit
            log.info(
                "state=%s sessionId=%s cacheHit=%s encoder=none",
                self.state.value,
                session_id,
                outcome.cache_hit,
            )
            await self._hub.broadcast(
                self._event(StationState.READY, 100, "Listo", outcome.cache_hit)
            )
        except PrepareError as exc:
            await ticks.put(None)
            await pump_task
            log.warning(
                "state=FAILED sessionId=%s code=%s message=%s",
                session_id,
                exc.code,
                exc.message,
            )
            await self._enter_failed(exc.code, exc.message)
        except asyncio.CancelledError:
            await ticks.put(None)
            pump_task.cancel()
            return
        except Exception:
            await ticks.put(None)
            await pump_task
            log.exception("prepare crashed sessionId=%s", session_id)
            await self._enter_failed("PREPARE_FAILED", "prepare falló")

    async def _emit_prepare_progress(self, pct: int, message: str) -> None:
        async with self._lock:
            if self.state != StationState.PREPARING:
                return
            self.progress = pct
        await self._hub.broadcast(
            self._event(StationState.PREPARING, pct, message)
        )

    async def _enter_failed(self, code: str, message: str) -> None:
        async with self._lock:
            self.state = StationState.FAILED
            self.progress = 0
        await self._hub.broadcast(
            {"type": "ERROR", "code": code, "message": message}
        )
        await self._hub.broadcast(
            self._event(StationState.FAILED, 0, message, False)
        )
        if self._failed_idle_s < 0:
            return
        self._failed_task = asyncio.create_task(self._failed_to_idle())

    async def _failed_to_idle(self) -> None:
        try:
            if self._failed_idle_s:
                await asyncio.sleep(self._failed_idle_s)
            if self.state == StationState.FAILED:
                await self.stop()
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
            self._playing_since = time.monotonic()
        log.info(
            "state=%s sessionId=%s game=%s encoder=%s",
            self.state.value,
            session_id,
            game_id,
            self._stream.encoder_name() or "pending",
        )
        await self._hub.broadcast(
            self._event(StationState.PLAYING, 100, "En partida")
        )
        try:
            await self._stream.start_source(game_id)
        except Exception:
            log.exception(
                "start_source failed sessionId=%s game=%s", session_id, game_id
            )
            await self.stop()
            raise
        log.info(
            "state=%s sessionId=%s encoder=%s",
            self.state.value,
            session_id,
            self._stream.encoder_name() or "vp8",
        )
        self._idle_task = asyncio.create_task(self._idle_watch())
        return {"state": StationState.PLAYING.value, "wsUrl": "/ws/webrtc"}

    async def _idle_watch(self) -> None:
        timeout = self._idle_timeout_s
        if timeout <= 0:
            return
        started = self._playing_since or time.monotonic()
        try:
            while self.state == StationState.PLAYING:
                await asyncio.sleep(min(5.0, max(0.05, timeout / 4)))
                last = self._stream.last_input_monotonic()
                ref = last if last is not None else started
                idle_for = time.monotonic() - ref
                if idle_for >= timeout:
                    log.info(
                        "state=IDLE sessionId=%s reason=idle_timeout idle_s=%.0f",
                        self.session_id,
                        idle_for,
                    )
                    await self.stop()
                    return
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        self._cancel_task(self._idle_task)
        self._idle_task = None
        self._cancel_task(self._failed_task)
        self._failed_task = None
        await self._stream.stop()
        async with self._lock:
            task = self._prepare_task
            self._prepare_task = None
            self.state = StationState.IDLE
            self.game_id = None
            self.session_id = None
            self.progress = 0
            self._playing_since = None
            self._last_cache_hit = False
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        log.info("state=%s sessionId=none encoder=none", self.state.value)
        await self._hub.broadcast(self._event(StationState.IDLE, 0, "Libre", False))

    @staticmethod
    def _cancel_task(task: Optional[asyncio.Task[None]]) -> None:
        if task and not task.done():
            task.cancel()
