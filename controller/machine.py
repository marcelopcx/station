from __future__ import annotations

import asyncio
from typing import Any, Optional

from controller.hub import Hub

IDLE = "IDLE"
PREPARING = "PREPARING"
READY = "READY"
PLAYING = "PLAYING"


class StationBusy(Exception):
    code = "STATION_BUSY"
    message = "Ya hay una partida en esta estación"


class PrepareInProgress(Exception):
    code = "PREPARE_IN_PROGRESS"
    message = "La estación está preparando o en partida"


class GameNotReady(Exception):
    code = "GAME_NOT_READY"
    message = "Hay que preparar el juego antes de lanzar"


class Station:
    def __init__(self, hub: Hub, station_id: str = "spark-1") -> None:
        self.hub = hub
        self.station_id = station_id
        self.state = IDLE
        self.game_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.progress = 0
        self._lock = asyncio.Lock()
        self._prepare_task: Optional[asyncio.Task[None]] = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": "UP",
            "stationId": self.station_id,
            "state": self.state,
            "gameId": self.game_id,
            "sessionId": self.session_id,
            "cache": [],
        }

    def _event(self, state: str, progress: int, message: str) -> dict[str, Any]:
        return {
            "type": "STATE",
            "state": state,
            "progress": progress,
            "message": message,
            "cacheHit": False,
        }

    async def prepare(self, session_id: str, game_id: str) -> dict[str, Any]:
        async with self._lock:
            if self.state in (PREPARING, PLAYING):
                raise PrepareInProgress()
            if self._prepare_task and not self._prepare_task.done():
                self._prepare_task.cancel()
            self.state = PREPARING
            self.session_id = session_id
            self.game_id = game_id
            self.progress = 0
            self._prepare_task = asyncio.create_task(self._run_prepare())
        await self.hub.broadcast(self._event(PREPARING, 0, "Copiando assets"))
        return {"sessionId": session_id, "state": PREPARING}

    async def _run_prepare(self) -> None:
        try:
            for step in range(0, 11):
                await asyncio.sleep(0.2)
                progress = step * 10
                async with self._lock:
                    if self.state != PREPARING:
                        return
                    self.progress = progress
                await self.hub.broadcast(
                    self._event(PREPARING, progress, "Copiando assets")
                )
            async with self._lock:
                self.state = READY
                self.progress = 100
            await self.hub.broadcast(self._event(READY, 100, "Listo"))
        except asyncio.CancelledError:
            return

    async def launch(self, session_id: str, game_id: str) -> dict[str, Any]:
        async with self._lock:
            if self.state == PLAYING:
                raise StationBusy()
            if self.state != READY:
                raise GameNotReady()
            self.state = PLAYING
            self.session_id = session_id
            self.game_id = game_id
        await self.hub.broadcast(self._event(PLAYING, 100, "En partida"))
        return {"state": PLAYING, "wsUrl": "/ws/webrtc"}

    async def stop(self) -> None:
        async with self._lock:
            task = self._prepare_task
            self._prepare_task = None
            self.state = IDLE
            self.game_id = None
            self.session_id = None
            self.progress = 0
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.hub.broadcast(self._event(IDLE, 0, "Libre"))