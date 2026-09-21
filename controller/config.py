"""Settings de la estación. Todo lo que un loader setea por contenedor.

N contenedores en host network necesitan `STATION_ID`, `STATION_HTTP_PORT`
y `STATION_DISPLAY` distintos. En bridge Docker los defaults bastan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Inmutable. `from_env()` es la fábrica de producción; los tests pasan campos."""

    station_id: str
    http_port: int
    display: str
    size: str
    fps: str
    library_root: str
    cache_root: str
    idle_timeout_s: float
    cors_origins: list[str]
    cors_origin_regex: str | None
    game_manifest: Path
    pulse_sock: str
    pulse_sink: str
    pulse_pa: str
    pulse_err: str
    pulse_source: str

    @property
    def width(self) -> str:
        w, _, h = self.size.partition("x")
        return w if w and h else "1280"

    @property
    def height(self) -> str:
        w, _, h = self.size.partition("x")
        return h if w and h else "720"

    @classmethod
    def from_env(cls) -> Settings:
        size = os.environ.get("STATION_SIZE", "1280x720").strip() or "1280x720"
        sink = os.environ.get("STATION_PULSE_SINK") or os.environ.get("PULSE_SINK") or "game"
        regex = os.environ.get("CORS_ORIGIN_REGEX", "").strip() or None
        return cls(
            station_id=os.environ.get("STATION_ID", "spark-1"),
            http_port=int(os.environ.get("STATION_HTTP_PORT", "8090")),
            display=os.environ.get("STATION_DISPLAY", ":99"),
            size=size,
            fps=os.environ.get("STATION_FPS", "60"),
            library_root=os.environ.get("LIBRARY_ROOT", "/opt/station-library"),
            cache_root=os.environ.get("CACHE_ROOT", "/cache"),
            idle_timeout_s=float(os.environ.get("IDLE_TIMEOUT_S", "300")),
            cors_origins=_csv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ),
            cors_origin_regex=regex,
            game_manifest=Path(
                os.environ.get("GAME_MANIFEST", "/opt/game/manifest.yaml")
            ),
            pulse_sock=os.environ.get("STATION_PULSE_SOCK", "/tmp/pulse/native"),
            pulse_sink=sink,
            pulse_pa=os.environ.get("STATION_PULSE_PA", "/etc/pulse/game.pa"),
            pulse_err=os.environ.get("STATION_PULSE_ERR", "/tmp/pulse.err"),
            pulse_source=os.environ.get(
                "STATION_PULSE_SOURCE", f"{sink}.monitor"
            ),
        )


def interpolate(value: str, settings: Settings) -> str:
    """Sustituye `${WIDTH}` `${HEIGHT}` `${SIZE}` `${CACHE}` `${LIBRARY}` `${DISPLAY}` `${FPS}`."""
    return (
        value.replace("${WIDTH}", settings.width)
        .replace("${HEIGHT}", settings.height)
        .replace("${SIZE}", settings.size)
        .replace("${CACHE}", settings.cache_root)
        .replace("${LIBRARY}", settings.library_root)
        .replace("${DISPLAY}", settings.display)
        .replace("${FPS}", settings.fps)
    )
