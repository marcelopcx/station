"""Excepciones de dominio y su proyección HTTP.

Cada `StationError` fija `code`, `message` y `http_status`. El handler
serializa `{ "error": { "code", "message" } }` sin el wrapper `detail`
que FastAPI añade por defecto.

    STATION_BUSY          409   launch con state == PLAYING
    PREPARE_IN_PROGRESS   409   prepare con state ∈ {PREPARING, PLAYING}
    GAME_NOT_READY        424   launch con state != READY
    BAD_REQUEST           400   base; Pydantic usa 422 en validación
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class StationError(Exception):
    code = "BAD_REQUEST"
    message = "Solicitud inválida"
    http_status = 400


class StationBusy(StationError):
    code = "STATION_BUSY"
    message = "Ya hay una partida en esta estación"
    http_status = 409


class PrepareInProgress(StationError):
    code = "PREPARE_IN_PROGRESS"
    message = "La estación está preparando o en partida"
    http_status = 409


class GameNotReady(StationError):
    code = "GAME_NOT_READY"
    message = "Hay que preparar el juego antes de lanzar"
    http_status = 424


def to_http_exception(exc: StationError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"error": {"code": exc.code, "message": exc.message}},
    )


async def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP", "message": str(exc.detail)}},
    )
