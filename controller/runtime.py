"""Display virtual + proceso del juego. Un launch = un process group."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from controller.games import SIZE, argv_for

log = logging.getLogger("game-station.runtime")

DISPLAY = os.environ.get("STATION_DISPLAY", ":99")

# GUID USB Xbox 360 (045e:028e, version 0x0110) = el pad virtual de input.py.
_SDL_PAD = (
    "030000005e0400008e02000010010000,Airtek Cloud Pad,"
    "a:b0,b:b1,x:b2,y:b3,back:b6,start:b7,guide:b8,"
    "leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,"
    "leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,"
    "dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,platform:Linux,\n"
)


class GameRuntime:
    def __init__(self, display: str = DISPLAY) -> None:
        self.display = display
        self._procs: list[asyncio.subprocess.Process] = []

    async def start(self, game_id: str) -> None:
        argv = argv_for(game_id)
        if argv is None:
            log.info("runtime skip display game=%s", game_id)
            return
        await self._start_display()
        await self._exec(argv, name=game_id)

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
        log.info("runtime stopped")

    async def _start_display(self) -> None:
        await self._exec(
            [
                "Xvfb",
                self.display,
                "-screen",
                "0",
                f"{SIZE}x24",
                "-ac",
                "+extension",
                "GLX",
            ],
            name="xvfb",
        )
        await asyncio.sleep(0.4)

    async def _exec(self, argv: list[str], name: str) -> None:
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        env.setdefault("NVIDIA_DRIVER_CAPABILITIES", "all")
        if name == "supertuxkart":
            home = os.environ.get("HOME", "/root")
            env.setdefault("HOME", home)
            env.setdefault("XDG_CONFIG_HOME", os.path.join(home, ".config"))
            env["SDL_VIDEODRIVER"] = "x11"
            env["SDL_GAMECONTROLLERCONFIG"] = _SDL_PAD
        log.info("exec %s cmd=%s display=%s", name, argv, self.display)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{argv[0]} no está en PATH (game={name}). "
                "En el Spark la imagen instala STK en /opt/stk; en el Mac usá test-pattern."
            ) from exc
        self._procs.append(proc)
