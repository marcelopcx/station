from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from controller.hub import Hub
from controller.machine import GameNotReady, PrepareInProgress, Station, StationBusy
from controller.models import LaunchRequest, PrepareRequest, StopRequest

hub = Hub()
station = Station(hub)

app = FastAPI(title="Airtek Game Station", version="s0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "BAD_REQUEST")
    message = getattr(exc, "message", str(exc))
    status = 424 if code == "GAME_NOT_READY" else 409
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP", "message": str(exc.detail)}},
    )


@app.get("/health")
async def health():
    return station.snapshot()


@app.post("/prepare", status_code=202)
async def prepare(body: PrepareRequest):
    try:
        return await station.prepare(body.sessionId, body.gameId)
    except PrepareInProgress as exc:
        raise _http_error(exc) from exc


@app.post("/launch")
async def launch(body: LaunchRequest):
    try:
        return await station.launch(body.sessionId, body.gameId)
    except (StationBusy, GameNotReady) as exc:
        raise _http_error(exc) from exc


@app.post("/stop", status_code=204)
async def stop(body: StopRequest):
    await station.stop()
    return Response(status_code=204)


@app.websocket("/ws/control")
async def ws_control(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(ws)