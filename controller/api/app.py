"""FastAPI: rutas, CORS y lifespan.

Los handlers delegan en `Station`. `create_app(station=...)` inyecta
la estación (p. ej. en un proceso de prueba manual).

    GET  /health       snapshot de estado (sin `progress`)
    POST /prepare      202; copia /library → /cache
    POST /launch       200 + `wsUrl`; arranca la fuente de video
    POST /stop         204; cierra peer y fuente; vuelve a IDLE
    WS   /ws/control   eventos STATE; el inbound se ignora
    WS   /ws/webrtc    signaling SDP/ICE; la guardia de estado está en Station
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from controller.catalog import load_catalog
from controller.config import Settings
from controller.contract.errors import StationError, http_exception_handler, to_http_exception
from controller.contract.models import LaunchRequest, PrepareRequest, StopRequest
from controller.runtime import GameRuntime
from controller.session import Hub, Station
from controller.webrtc.session import WebrtcSession
from controller.webrtc.ice import configure_ice_hosts

log = logging.getLogger("game-station.app")


def create_station(settings: Settings | None = None) -> Station:
    settings = settings or Settings.from_env()
    try:
        os.makedirs(settings.cache_root, exist_ok=True)
    except OSError:
        pass
    catalog = load_catalog(settings.game_manifest)
    runtime = GameRuntime(settings=settings, catalog=catalog)
    return Station(
        hub=Hub(),
        stream=WebrtcSession(runtime=runtime),
        station_id=settings.station_id,
        library_root=settings.library_root,
        cache_root=settings.cache_root,
        idle_timeout_s=settings.idle_timeout_s,
        catalog=catalog,
        settings=settings,
    )


def create_app(station: Station | None = None) -> FastAPI:
    settings = Settings.from_env()
    station = station or create_station(settings)

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
        supported = station.snapshot().get("supportedGameId")
        log.info(
            "game-station ready id=%s game=%s port=%s",
            station.station_id,
            supported or "-",
            settings.http_port,
        )
        yield
        await station.stop()

    app = FastAPI(title="Airtek Game Station", version="1.0", lifespan=lifespan)
    app.state.station = station
    app.add_exception_handler(HTTPException, http_exception_handler)

    origins = settings.cors_origins
    origin_regex = settings.cors_origin_regex
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
