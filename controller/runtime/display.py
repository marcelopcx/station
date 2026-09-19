"""Xvfb. Resolución y DISPLAY salen de Settings, no del juego."""

from __future__ import annotations

import asyncio
import logging
import os

from controller.config import Settings
from controller.runtime.process import ProcessGroup

log = logging.getLogger("game-station.runtime.display")


class DisplayServer:
    def __init__(self, settings: Settings, procs: ProcessGroup) -> None:
        self._settings = settings
        self._procs = procs

    @property
    def name(self) -> str:
        return self._settings.display

    async def start(self) -> None:
        await self._procs.spawn(
            [
                "Xvfb",
                self._settings.display,
                "-screen",
                "0",
                f"{self._settings.size}x24",
                "-ac",
                "+extension",
                "GLX",
            ],
            env=os.environ.copy(),
            name="xvfb",
        )
        await asyncio.sleep(0.4)
        log.info("display ready %s %s", self._settings.display, self._settings.size)
