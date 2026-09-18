"""Display virtual + proceso del juego. Un launch = un process group.

Pulse vive todo el contenedor (no se mata en `stop`): el sink `stk` y
`stk.monitor` tienen que existir antes de STK y de la captura WebRTC.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path
from typing import IO, Optional

from controller.games import SIZE, argv_for

log = logging.getLogger("game-station.runtime")

DISPLAY = os.environ.get("STATION_DISPLAY", ":99")
PULSE_SOCK = os.environ.get("STATION_PULSE_SOCK", "/tmp/pulse/native")
PULSE_SINK = os.environ.get("STATION_PULSE_SINK", "stk")
PULSE_PA = os.environ.get("STATION_PULSE_PA", "/etc/pulse/stk.pa")
PULSE_ERR = os.environ.get("STATION_PULSE_ERR", "/tmp/pulse.err")

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
        self._pulse: Optional[asyncio.subprocess.Process] = None
        self._pulse_err: Optional[IO[bytes]] = None

    async def start(self, game_id: str) -> None:
        argv = argv_for(game_id)
        if argv is None:
            log.info("runtime skip display game=%s", game_id)
            return
        await self._start_display()
        has_pulse = await self._ensure_pulse()
        if game_id == "supertuxkart" and not has_pulse:
            argv = list(argv) + ["--disable-sound"]
            log.warning("pulse failed; STK --disable-sound")
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

    def _pulse_alive(self) -> bool:
        return (
            self._pulse is not None
            and self._pulse.returncode is None
            and os.path.exists(PULSE_SOCK)
        )

    async def _ensure_pulse(self) -> bool:
        if self._pulse_alive():
            os.environ["PULSE_SERVER"] = f"unix:{PULSE_SOCK}"
            os.environ["PULSE_SINK"] = PULSE_SINK
            return True
        if shutil.which("pulseaudio") is None:
            log.warning("pulseaudio no está en PATH")
            return False
        if await self._spawn_pulse(user_mode=True):
            return True
        log.warning("pulse user-mode failed; trying --system")
        return await self._spawn_pulse(user_mode=False)

    async def _spawn_pulse(self, user_mode: bool) -> bool:
        await self._kill_pulse()
        os.makedirs("/tmp/pulse", exist_ok=True)
        os.makedirs("/tmp/pulse-run", exist_ok=True)
        try:
            os.chmod("/tmp/pulse", 0o777)
            os.chmod("/tmp/pulse-run", 0o700)
        except OSError:
            pass
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = "/tmp/pulse-run"
        env["PULSE_RUNTIME_PATH"] = "/tmp/pulse"
        env["PULSE_STATE_PATH"] = "/tmp/pulse"
        env["HOME"] = env.get("HOME") or "/root"
        if user_mode:
            if not Path(PULSE_PA).is_file():
                log.warning("pulse script missing %s", PULSE_PA)
                return False
            argv = [
                "pulseaudio",
                "-n",
                f"--file={PULSE_PA}",
                "--exit-idle-time=-1",
                "--daemonize=no",
                "--use-pid-file=false",
                "--log-target=stderr",
                "--disallow-exit",
            ]
        else:
            argv = [
                "pulseaudio",
                "--system",
                "--disallow-exit",
                "--exit-idle-time=-1",
                "--use-pid-file=false",
                "--log-target=stderr",
                "--daemonize=no",
            ]
        log.info("exec pulse cmd=%s", argv)
        try:
            self._pulse_err = open(PULSE_ERR, "wb")
            self._pulse = await asyncio.create_subprocess_exec(
                *argv,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=self._pulse_err,
                start_new_session=True,
            )
        except FileNotFoundError:
            return False
        await asyncio.sleep(0.4)
        if self._pulse.returncode is not None:
            log.warning("pulse exited %s", self._pulse.returncode)
            self._log_pulse_err()
            return False
        for _ in range(25):
            if os.path.exists(PULSE_SOCK):
                try:
                    os.chmod(PULSE_SOCK, 0o777)
                except OSError:
                    pass
                os.environ["PULSE_SERVER"] = f"unix:{PULSE_SOCK}"
                os.environ["PULSE_SINK"] = PULSE_SINK
                await self._pactl_setup()
                log.info("pulse ready sink=%s sock=%s", PULSE_SINK, PULSE_SOCK)
                return True
            await asyncio.sleep(0.2)
        log.warning("pulse socket no apareció (%s)", PULSE_SOCK)
        self._log_pulse_err()
        await self._kill_pulse()
        return False

    async def _pactl_setup(self) -> None:
        if shutil.which("pactl") is None:
            return
        env = os.environ.copy()
        env["PULSE_SERVER"] = f"unix:{PULSE_SOCK}"
        for args in (
            ["pactl", "set-default-sink", PULSE_SINK],
            ["pactl", "set-sink-mute", PULSE_SINK, "0"],
            ["pactl", "set-sink-volume", PULSE_SINK, "100%"],
            ["pactl", "set-default-source", f"{PULSE_SINK}.monitor"],
        ):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except FileNotFoundError:
                return
        try:
            listed = await asyncio.create_subprocess_exec(
                "pactl",
                "list",
                "short",
                "sources",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await listed.communicate()
            log.info("pulse sources=%s", out.decode("utf-8", "replace").strip())
        except FileNotFoundError:
            return

    def _log_pulse_err(self) -> None:
        try:
            if self._pulse_err:
                self._pulse_err.flush()
            text = Path(PULSE_ERR).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        tail = text[-2000:].strip()
        if tail:
            log.warning("pulse log:\n%s", tail)

    async def _kill_pulse(self) -> None:
        proc = self._pulse
        self._pulse = None
        if proc is not None and proc.returncode is None and proc.pid is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
                await proc.wait()
        err = self._pulse_err
        self._pulse_err = None
        if err is not None:
            try:
                err.close()
            except OSError:
                pass

    async def _exec(self, argv: list[str], name: str) -> None:
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        env.setdefault("NVIDIA_DRIVER_CAPABILITIES", "all")
        if os.path.exists(PULSE_SOCK):
            env["PULSE_SERVER"] = f"unix:{PULSE_SOCK}"
            env["PULSE_SINK"] = PULSE_SINK
        if name == "supertuxkart":
            home = os.environ.get("HOME", "/root")
            env.setdefault("HOME", home)
            env.setdefault("XDG_CONFIG_HOME", os.path.join(home, ".config"))
            env["SDL_VIDEODRIVER"] = "x11"
            env["SDL_AUDIODRIVER"] = "pulse"
            env["ALSOFT_DRIVERS"] = "pulse"
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
