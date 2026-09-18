"""Recetas de `gameId` → argv. `None` = sin display (fuente SMPTE)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("game-station.games")

SIZE = os.environ.get("STATION_SIZE", "1280x720")
_WIDTH, _, _HEIGHT = SIZE.partition("x")
if not _WIDTH or not _HEIGHT:
    _WIDTH, _HEIGHT = "1280", "720"

_STK_BUNDLED = "/opt/stk/run_game.sh"

GAMES: dict[str, list[str] | None] = {
    "test-pattern": None,
    "glxgears": ["glxgears"],
    "vkcube": ["vkcube"],
    "supertuxkart": ["supertuxkart"],
}


def _stk_bin() -> str:
    """Binario de STK: `STK_BIN`, o el tarball en la imagen Spark, o PATH."""
    explicit = os.environ.get("STK_BIN", "").strip()
    if explicit:
        return explicit
    if os.path.isfile(_STK_BUNDLED):
        return _STK_BUNDLED
    return "supertuxkart"


def argv_for(game_id: str) -> list[str] | None:
    """Argumentos del binario, o `None` si no hay proceso (SMPTE)."""
    if game_id not in GAMES:
        log.warning("unknown gameId=%s, using test-pattern", game_id)
        return None
    if game_id == "test-pattern":
        return None
    if game_id == "supertuxkart":
        return [
            _stk_bin(),
            f"--width={_WIDTH}",
            f"--height={_HEIGHT}",
            "--disable-sound",
        ]
    argv = GAMES[game_id]
    return None if argv is None else list(argv)


def needs_display(game_id: str) -> bool:
    return argv_for(game_id) is not None
