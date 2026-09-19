"""Orquesta display + audio + proceso según el manifiesto.

No hay `if game_id == ...`. El título solo existe en `catalog`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from controller.catalog import GameCatalog, GameManifest
from controller.config import Settings, interpolate
from controller.input.gamepad import sdl_controller_config
from controller.runtime.audio import PulseServer
from controller.runtime.display import DisplayServer
from controller.runtime.process import ProcessGroup

log = logging.getLogger("game-station.runtime")


class GameRuntime:
    """Un launch = un process group (Xvfb + juego). Pulse sobrevive al stop."""

    def __init__(
        self,
        settings: Settings | None = None,
        catalog: GameCatalog | None = None,
    ) -> None:
        self._settings = settings or Settings.from_env()
        self._catalog = catalog
        self._procs = ProcessGroup()
        self._display = DisplayServer(self._settings, self._procs)
        self._pulse = PulseServer(self._settings)
        self._manifest: Optional[GameManifest] = None

    @property
    def settings(self) -> Settings:
        return self._settings

    def manifest_for(self, game_id: str) -> GameManifest:
        return self._resolve(game_id)

    @property
    def display(self) -> str:
        return self._display.name

    @property
    def captures_display(self) -> bool:
        if self._manifest is None:
            return False
        return self._manifest.needs.display and self._manifest.kind != "test-pattern"

    async def start(self, game_id: str) -> None:
        manifest = self._resolve(game_id)
        self._manifest = manifest
        argv = manifest.argv(self._settings)
        if argv is None:
            log.info("runtime skip display game=%s kind=%s", game_id, manifest.kind)
            return
        await self._display.start()
        has_pulse = True
        if manifest.needs.audio:
            has_pulse = await self._pulse.ensure()
            if not has_pulse and manifest.audio.fallback_args:
                extra = [
                    interpolate(arg, self._settings)
                    for arg in manifest.audio.fallback_args
                ]
                argv = list(argv) + extra
                log.warning("pulse failed; fallback args=%s", extra)
        await self._spawn_game(argv, manifest)

    async def stop(self) -> None:
        await self._procs.stop()
        self._manifest = None

    def _resolve(self, game_id: str) -> GameManifest:
        if self._catalog is not None:
            return self._catalog.require(game_id)
        raise RuntimeError(
            f"no hay manifiesto en esta imagen; no se puede lanzar {game_id}"
        )

    async def _spawn_game(self, argv: list[str], manifest: GameManifest) -> None:
        env = os.environ.copy()
        env["DISPLAY"] = self._settings.display
        env.setdefault("NVIDIA_DRIVER_CAPABILITIES", "all")
        self._pulse.apply_env(env)
        env.update(manifest.interpolated_env(self._settings))
        if manifest.needs.gamepad:
            env.setdefault(
                "SDL_GAMECONTROLLERCONFIG",
                sdl_controller_config(manifest.needs.gamepad),
            )
        await self._procs.spawn(
            argv,
            env=env,
            name=manifest.id,
            cwd=manifest.workdir,
        )
