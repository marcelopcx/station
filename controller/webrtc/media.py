"""Fuentes de video/audio para `WebrtcSession`.

    SmpteBarsSource         lavfi smptebars (Mac / fallback); sin audio
    DisplayCaptureSource    x11grab + Pulse `stk.monitor` (Spark)

El encode (VP8 / Opus) lo hace aiortc en el `RTCRtpSender`, no estas clases.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from typing import Optional, Union

from aiortc import AudioStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay
from av import AudioFrame

from controller.games import needs_display

log = logging.getLogger("game-station.webrtc.media")

SMPTE_LAVFI = "smptebars=size=1280x720:rate=30"
CAPTURE_SIZE = os.environ.get("STATION_SIZE", "1280x720")
CAPTURE_FPS = os.environ.get("STATION_FPS", "30")
PULSE_SOURCE = os.environ.get("STATION_PULSE_SOURCE", "stk.monitor")

_AUDIO_RATE = 48000
_AUDIO_SAMPLES = 960  # 20 ms
_AUDIO_BYTES = _AUDIO_SAMPLES * 2  # mono s16le


class FfmpegPulseTrack(AudioStreamTrack):
    """PCM desde el CLI de ffmpeg (`-f pulse`), no el FFmpeg embebido de PyAV."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source
        self._proc: Optional[subprocess.Popen[bytes]] = None

    def start(self) -> None:
        if self._proc is not None:
            return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise FileNotFoundError("ffmpeg")
        self._proc = subprocess.Popen(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "pulse",
                "-i",
                self._source,
                "-ac",
                "1",
                "-ar",
                str(_AUDIO_RATE),
                "-f",
                "s16le",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._proc.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise RuntimeError(
                f"ffmpeg pulse exited {self._proc.returncode} source={self._source}"
            )
        log.info("audio source=pulse %s pid=%s", self._source, self._proc.pid)

    async def recv(self) -> AudioFrame:
        pts, time_base = await self.next_timestamp()
        data = await asyncio.get_running_loop().run_in_executor(None, self._read)
        frame = AudioFrame(format="s16", layout="mono", samples=_AUDIO_SAMPLES)
        frame.planes[0].update(data)
        frame.pts = pts
        frame.time_base = time_base
        frame.sample_rate = _AUDIO_RATE
        return frame

    def _read(self) -> bytes:
        proc = self._proc
        stdout = proc.stdout if proc is not None else None
        if stdout is None:
            return b"\x00" * _AUDIO_BYTES
        data = stdout.read(_AUDIO_BYTES)
        if not data:
            return b"\x00" * _AUDIO_BYTES
        if len(data) < _AUDIO_BYTES:
            data = data + b"\x00" * (_AUDIO_BYTES - len(data))
        return data

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
        """Track clonado para `addTrack`, o `None` si no hay player."""
        if self._player is None or self._player.video is None:
            return None
        return self._relay.subscribe(self._player.video, buffered=False)

    def subscribe_audio(self):
        return None

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

    def __init__(self, display: str = ":99") -> None:
        self._display = display
        self._relay = MediaRelay()
        self._player: Optional[MediaPlayer] = None
        self._audio: Optional[FfmpegPulseTrack] = None

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
                "draw_mouse": "0",
                "probesize": "32",
            },
        )
        self._start_audio()

    def _start_audio(self) -> None:
        source = os.environ.get("STATION_PULSE_SOURCE", PULSE_SOURCE)
        try:
            track = FfmpegPulseTrack(source)
            track.start()
            self._audio = track
        except Exception as exc:
            self._audio = None
            log.warning("audio skipped: %s", exc)

    def subscribe_video(self):
        if self._player is None or self._player.video is None:
            return None
        return self._relay.subscribe(self._player.video, buffered=False)

    def subscribe_audio(self):
        if self._audio is None:
            return None
        return self._relay.subscribe(self._audio, buffered=False)

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


def make_source(game_id: str, display: str) -> VideoSource:
    if not needs_display(game_id):
        return SmpteBarsSource()
    return DisplayCaptureSource(display=display)
