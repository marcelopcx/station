"""FastAPI: rutas, CORS y lifespan.

Los handlers delegan en `Station`. `create_app(station=...)` permite
inyectar un doble y no abrir FFmpeg en tests.

    GET  /health       snapshot de estado (sin `progress`)
    POST /prepare      202; copia /library → /cache (S4)
    POST /launch       200 + `wsUrl`; arranca la fuente de video
    POST /stop         204; cierra peer y fuente; vuelve a IDLE
    WS   /ws/control   eventos STATE; el inbound se ignora
    WS   /ws/webrtc    signaling SDP/ICE; la guardia de estado está en Station

CORS: `CORS_ORIGINS` (lista separada por comas; default Vite :5173).
`STATION_ID` entra en `/health` (default `spark-1`).

`/ws/control` lee en loop: si el handler retorna, FastAPI no detecta el
close del cliente.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from controller.errors import StationError, http_exception_handler, to_http_exception
from controller.hub import Hub
from controller.machine import Station
from controller.models import LaunchRequest, PrepareRequest, StopRequest
from controller.webrtc import WebrtcSession, configure_ice_hosts

log = logging.getLogger("game-station.app")

_DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", _DEFAULT_CORS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_station() -> Station:
    cache = os.environ.get("CACHE_ROOT", "/cache")
    library = os.environ.get("LIBRARY_ROOT", "/opt/station-library")
    try:
        os.makedirs(cache, exist_ok=True)
    except OSError:
        pass
    return Station(
        hub=Hub(),
        stream=WebrtcSession(),
        station_id=os.environ.get("STATION_ID", "spark-1"),
        library_root=library,
        cache_root=cache,
    )


def create_app(station: Station | None = None) -> FastAPI:
    station = station or create_station()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        gs = logging.getLogger("game-station")
        gs.setLevel(logging.INFO)
        if not any(isinstance(h, logging.StreamHandler) for h in gs.handlers):
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(levelname)s %(name)s %(message)s")
            )
            gs.addHandler(handler)
        configure_ice_hosts()
        log.info("game-station ready id=%s", station.station_id)
        yield
        await station.stop()

    app = FastAPI(title="Airtek Game Station", version="s5", lifespan=lifespan)
    app.state.station = station
    app.add_exception_handler(HTTPException, http_exception_handler)

    origins = cors_origins()
    origin_regex = os.environ.get("CORS_ORIGIN_REGEX", "").strip() or None
    log.info("cors origins=%s regex=%s", origins, origin_regex)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return station.snapshot()

    @app.post("/prepare", status_code=202)
    async def prepare(body: PrepareRequest):
        try:
            return await station.prepare(
                body.sessionId, body.gameId, body.version, body.source
            )
        except StationError as exc:
            raise to_http_exception(exc) from exc

    @app.post("/launch")
    async def launch(body: LaunchRequest):
        try:
            return await station.launch(body.sessionId, body.gameId)
        except StationError as exc:
            raise to_http_exception(exc) from exc

    @app.post("/stop", status_code=204)
    async def stop(body: StopRequest):
        await station.stop()
        return Response(status_code=204)

    @app.websocket("/ws/control")
    async def ws_control(ws: WebSocket):
        await station.connect_control(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            await station.disconnect_control(ws)

    @app.websocket("/ws/webrtc")
    async def ws_webrtc(ws: WebSocket):
        await ws.accept()
        await station.attach_webrtc(ws)

    return app


app = create_app()
