"""Spawn y kill de un process group. No sabe qué binario es."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Mapping

log = logging.getLogger("game-station.runtime.process")


class ProcessGroup:
    """Lista de procesos (Xvfb + juego). Pulse vive aparte y no se mata en stop."""

    def __init__(self) -> None:
        self._procs: list[asyncio.subprocess.Process] = []

    def add(self, proc: asyncio.subprocess.Process) -> None:
        self._procs.append(proc)

    async def spawn(
        self,
        argv: list[str],
        env: Mapping[str, str],
        name: str,
        cwd: str | None = None,
    ) -> asyncio.subprocess.Process:
        log.info("exec %s cmd=%s cwd=%s", name, argv, cwd or ".")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                env=dict(env),
                cwd=cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{argv[0]} no está en PATH (proc={name})"
            ) from exc
        self.add(proc)
        return proc

    async def stop(self) -> None:
        procs = list(reversed(self._procs))
        self._procs.clear()
        for proc in procs:
            if proc.returncode is not None or proc.pid is None:
                continue
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
        for proc in procs:
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                if proc.pid is not None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        proc.kill()
                await proc.wait()
        log.info("process group stopped")
