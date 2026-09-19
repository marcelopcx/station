"""PulseAudio del contenedor. Sink genérico `game` (no el nombre de un título).

Pulse vive todo el contenedor: no se mata en `stop` de la partida. El sink
y `*.monitor` tienen que existir antes del juego y de la captura WebRTC.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path
from typing import IO, Optional

from controller.config import Settings

log = logging.getLogger("game-station.runtime.audio")


class PulseServer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pulse: Optional[asyncio.subprocess.Process] = None
        self._pulse_err: Optional[IO[bytes]] = None

    def apply_env(self, env: dict[str, str]) -> None:
        sock = self._settings.pulse_sock
        if os.path.exists(sock):
            env["PULSE_SERVER"] = f"unix:{sock}"
            env["PULSE_SINK"] = self._settings.pulse_sink

    def _alive(self) -> bool:
        return (
            self._pulse is not None
            and self._pulse.returncode is None
            and os.path.exists(self._settings.pulse_sock)
        )

    async def ensure(self) -> bool:
        if self._alive():
            os.environ["PULSE_SERVER"] = f"unix:{self._settings.pulse_sock}"
            os.environ["PULSE_SINK"] = self._settings.pulse_sink
            return True
        if shutil.which("pulseaudio") is None:
            log.warning("pulseaudio no está en PATH")
            return False
        if await self._spawn(user_mode=True):
            return True
        log.warning("pulse user-mode failed; trying --system")
        return await self._spawn(user_mode=False)

    async def _spawn(self, user_mode: bool) -> bool:
        await self._kill()
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
        settings = self._settings
        if user_mode:
            if not Path(settings.pulse_pa).is_file():
                log.warning("pulse script missing %s", settings.pulse_pa)
                return False
            argv = [
                "pulseaudio",
                "-n",
                f"--file={settings.pulse_pa}",
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
            self._pulse_err = open(settings.pulse_err, "wb")
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
            self._log_err()
            return False
        for _ in range(25):
            if os.path.exists(settings.pulse_sock):
                try:
                    os.chmod(settings.pulse_sock, 0o777)
                except OSError:
                    pass
                os.environ["PULSE_SERVER"] = f"unix:{settings.pulse_sock}"
                os.environ["PULSE_SINK"] = settings.pulse_sink
                await self._pactl_setup()
                log.info(
                    "pulse ready sink=%s sock=%s",
                    settings.pulse_sink,
                    settings.pulse_sock,
                )
                return True
            await asyncio.sleep(0.2)
        log.warning("pulse socket no apareció (%s)", settings.pulse_sock)
        self._log_err()
        await self._kill()
        return False

    async def _pactl_setup(self) -> None:
        if shutil.which("pactl") is None:
            return
        sink = self._settings.pulse_sink
        sock = self._settings.pulse_sock
        env = os.environ.copy()
        env["PULSE_SERVER"] = f"unix:{sock}"
        for args in (
            ["pactl", "set-default-sink", sink],
            ["pactl", "set-sink-mute", sink, "0"],
            ["pactl", "set-sink-volume", sink, "100%"],
            ["pactl", "set-default-source", f"{sink}.monitor"],
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

    def _log_err(self) -> None:
        try:
            if self._pulse_err:
                self._pulse_err.flush()
            text = Path(self._settings.pulse_err).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return
        tail = text[-2000:].strip()
        if tail:
            log.warning("pulse log:\n%s", tail)

    async def _kill(self) -> None:
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
