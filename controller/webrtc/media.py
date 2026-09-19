"""Fuentes de video/audio para `WebrtcSession`.

    SmpteBarsSource         lavfi smptebars (fallback / tests)
    DisplayCaptureSource    x11grab + Pulse monitor

El encode (VP8 / Opus) lo hace aiortc en el `RTCRtpSender`, no estas clases.
La elección display vs SMPTE la hace el manifiesto (`needs.display`), no un gameId.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import shutil
import subprocess
import threading
from fractions import Fraction
from typing import Optional, Union

from aiortc import AudioStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame

log = logging.getLogger("game-station.webrtc.media")

SMPTE_LAVFI = "smptebars=size=1280x720:rate=30"
CAPTURE_SIZE = os.environ.get("STATION_SIZE", "1280x720")
CAPTURE_FPS = os.environ.get("STATION_FPS", "30")
PULSE_SOURCE = os.environ.get("STATION_PULSE_SOURCE", "game.monitor")

_AUDIO_RATE = 48000
_AUDIO_SAMPLES = 960  # 20 ms
_AUDIO_CH = 2
_AUDIO_BYTES = _AUDIO_SAMPLES * 2 * _AUDIO_CH  # stereo s16le
_AUDIO_TIME_BASE = Fraction(1, _AUDIO_RATE)


class PulseAudioTrack(AudioStreamTrack):
    """PCM stereo 48 kHz desde `parec` (Pulse) o `ffmpeg -f pulse`."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self._thread: Optional[threading.Thread] = None
        self._pts = 0
        self._heard = False

    def start(self) -> None:
        if self._proc is not None:
            return
        last: Exception | None = None
        for argv, kind in _capture_candidates(self._source):
            try:
                self._start_proc(argv, kind)
                return
            except Exception as exc:
                last = exc
                log.warning("audio %s failed: %s", kind, exc)
                self._proc = None
        raise last or FileNotFoundError("parec/ffmpeg")

    def _start_proc(self, argv: list[str], kind: str) -> None:
        env = os.environ.copy()
        sock = os.environ.get("STATION_PULSE_SOCK", "/tmp/pulse/native")
        env.setdefault("PULSE_SERVER", f"unix:{sock}")
        self._proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            self._proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            pass
        else:
            err = b""
            if self._proc.stderr:
                err = self._proc.stderr.read()[:500]
            raise RuntimeError(
                f"{kind} exited {self._proc.returncode} source={self._source} "
                f"{err.decode('utf-8', 'replace')}"
            )
        self._thread = threading.Thread(target=self._pump, name="pulse-pcm", daemon=True)
        self._thread.start()
        log.info("audio source=pulse %s via=%s pid=%s", self._source, kind, self._proc.pid)

    def _pump(self) -> None:
        proc = self._proc
        stdout = proc.stdout if proc is not None else None
        if stdout is None:
            return
        while proc is not None and proc.poll() is None:
            data = stdout.read(_AUDIO_BYTES)
            if not data:
                break
            if len(data) < _AUDIO_BYTES:
                data = data + b"\x00" * (_AUDIO_BYTES - len(data))
            if not self._heard and any(data):
                self._heard = True
                log.info("audio signal=yes source=%s", self._source)
            try:
                self._queue.put(data, timeout=0.2)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(data)
                except queue.Full:
                    pass

    def _get_frame(self) -> bytes:
        try:
            return self._queue.get(timeout=0.05)
        except queue.Empty:
            return b"\x00" * _AUDIO_BYTES

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._get_frame)
        frame = AudioFrame(format="s16", layout="stereo", samples=_AUDIO_SAMPLES)
        frame.planes[0].update(data)
        frame.pts = self._pts
        frame.time_base = _AUDIO_TIME_BASE
        frame.sample_rate = _AUDIO_RATE
        self._pts += _AUDIO_SAMPLES
        return frame

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        super().stop()


def _capture_candidates(source: str) -> list[tuple[list[str], str]]:
    out: list[tuple[list[str], str]] = []
    parec = shutil.which("parec")
    if parec:
        out.append(
            (
                [
                    parec,
                    "--raw",
                    "--format=s16le",
                    f"--rate={_AUDIO_RATE}",
                    f"--channels={_AUDIO_CH}",
                    f"--device={source}",
                    "--latency-msec=20",
                ],
                "parec",
            )
        )
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        out.append(
            (
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "pulse",
                    "-i",
                    source,
                    "-ac",
                    str(_AUDIO_CH),
                    "-ar",
                    str(_AUDIO_RATE),
                    "-f",
                    "s16le",
                    "pipe:1",
                ],
                "ffmpeg",
            )
        )
    if not out:
        raise FileNotFoundError("parec/ffmpeg")
    return out


class SmpteBarsSource:
    def __init__(self) -> None:
        self._relay = MediaRelay()
        self._player: Optional[MediaPlayer] = None

    def is_running(self) -> bool:
        return self._player is not None and self._player.video is not None

    def start(self) -> None:
        if self._player is not None:
            return
        log.info("encoder=vp8 source=smptebars 1280x720@30")
        self._player = MediaPlayer(SMPTE_LAVFI, format="lavfi")

    def subscribe_video(self):
        if self._player is None or self._player.video is None:
            return None
        return self._relay.subscribe(self._player.video, buffered=False)

    def subscribe_audio(self):
        if self._player is None or self._player.audio is None:
            return None
        return self._relay.subscribe(self._player.audio, buffered=False)

    def stop(self) -> None:
        player = self._player
        self._player = None
        if player is None:
            return
        if player.video:
            player.video.stop()
        if player.audio:
            player.audio.stop()


class DisplayCaptureSource:
    """x11grab del DISPLAY + Pulse monitor. Encode: aiortc (VP8 / Opus)."""

    def __init__(self, display: str = ":99", draw_mouse: bool = False) -> None:
        self._display = display
        self._draw_mouse = draw_mouse
        self._relay = MediaRelay()
        self._player: Optional[MediaPlayer] = None
        self._audio: Optional[PulseAudioTrack] = None

    def is_running(self) -> bool:
        return self._player is not None and self._player.video is not None

    def start(self) -> None:
        if self._player is not None:
            return
        log.info(
            "encoder=vp8 source=x11grab display=%s %s@%s",
            self._display,
            CAPTURE_SIZE,
            CAPTURE_FPS,
        )
        self._player = MediaPlayer(
            self._display,
            format="x11grab",
            options={
                "video_size": CAPTURE_SIZE,
                "framerate": CAPTURE_FPS,
                "draw_mouse": "1" if self._draw_mouse else "0",
                "probesize": "32",
            },
        )

    def _start_audio(self) -> PulseAudioTrack | None:
        source = os.environ.get("STATION_PULSE_SOURCE", PULSE_SOURCE)
        try:
            track = PulseAudioTrack(source)
            track.start()
            return track
        except Exception as exc:
            log.warning("audio skipped: %s", exc)
            return None

    def subscribe_video(self):
        if self._player is None or self._player.video is None:
            return None
        return self._relay.subscribe(self._player.video, buffered=False)

    def subscribe_audio(self):
        if self._audio is None:
            self._audio = self._start_audio()
        return self._audio

    def stop(self) -> None:
        audio = self._audio
        self._audio = None
        if audio is not None:
            audio.stop()
        player = self._player
        self._player = None
        if player is None:
            return
        if player.video:
            player.video.stop()
        if player.audio:
            player.audio.stop()


VideoSource = Union[SmpteBarsSource, DisplayCaptureSource]


def make_source(
    *,
    capture_display: bool,
    display: str,
    draw_mouse: bool = False,
) -> VideoSource:
    if not capture_display:
        return SmpteBarsSource()
    return DisplayCaptureSource(display=display, draw_mouse=draw_mouse)
