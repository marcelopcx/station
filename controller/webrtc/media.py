"""Fuentes de video/audio para `WebrtcSession`.

    SmpteBarsSource         lavfi smptebars (fallback / tests)
    DisplayCaptureSource    x11grab + Pulse monitor

El encode (H.264 NVENC / libx264, fallback VP8) lo hace aiortc en el
`RTCRtpSender`. La elección display vs SMPTE la hace el manifiesto.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from fractions import Fraction
from typing import Optional, Union

import av
from aiortc import AudioStreamTrack, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame

from controller.webrtc.encode import apply as apply_encoder, codec_name

log = logging.getLogger("game-station.webrtc.media")

apply_encoder()

SMPTE_LAVFI = "smptebars=size=1280x720:rate=60"
CAPTURE_SIZE = os.environ.get("STATION_SIZE", "1280x720")
CAPTURE_FPS = os.environ.get("STATION_FPS", "60")
PULSE_SOURCE = os.environ.get("STATION_PULSE_SOURCE", "game.monitor")

_AUDIO_RATE = 48000
_AUDIO_SAMPLES = 960  # 20 ms
_AUDIO_CH = 2
_AUDIO_BYTES = _AUDIO_SAMPLES * 2 * _AUDIO_CH  # stereo s16le
_AUDIO_TIME_BASE = Fraction(1, _AUDIO_RATE)
_VIDEO_CLOCK = 90000
_VIDEO_TIME_BASE = Fraction(1, _VIDEO_CLOCK)

_X11GRAB_OPTIONS = {
    "probesize": "32",
    "analyzeduration": "0",
    "fflags": "nobuffer",
    "flags": "low_delay",
    "thread_queue_size": "1",
    "use_wallclock_as_timestamps": "1",
}


class PulseAudioTrack(AudioStreamTrack):
    """PCM stereo 48 kHz desde `parec` (Pulse) o `ffmpeg -f pulse`."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=2)
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
                    "--latency-msec=10",
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
        log.info("encoder=%s source=smptebars 1280x720@%s", codec_name(), CAPTURE_FPS)
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


class X11GrabTrack(VideoStreamTrack):
    """x11grab en un hilo, cola de 1 frame: el encode siempre ve el último.

    MediaPlayer de aiortc encola sin límite. Si VP8 software va más lento que
    la captura, el jugador ve el pasado (input lag).
    """

    def __init__(self, display: str, *, size: str, fps: str, draw_mouse: bool) -> None:
        super().__init__()
        self._display = display
        self._size = size
        self._fps = fps
        self._draw_mouse = draw_mouse
        self._lock = threading.Lock()
        self._has = threading.Event()
        self._latest: object | None = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._container: Optional[av.container.InputContainer] = None
        self._origin: Optional[float] = None
        self._logged = False

    def start(self) -> None:
        if self._thread is not None:
            return
        options = {
            "video_size": self._size,
            "framerate": self._fps,
            "draw_mouse": "1" if self._draw_mouse else "0",
            **_X11GRAB_OPTIONS,
        }
        container = av.open(
            self._display, format="x11grab", mode="r", options=options
        )
        self._container = container
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(container,), name="x11grab", daemon=True
        )
        self._thread.start()

    def _run(self, container: av.container.InputContainer) -> None:
        streams = [s for s in container.streams if s.type == "video"]
        if not streams:
            log.warning("x11grab sin stream de video display=%s", self._display)
            try:
                container.close()
            except Exception:
                pass
            return
        decode = container.decode(*streams)
        try:
            while not self._stop.is_set():
                try:
                    frame = next(decode)
                except StopIteration:
                    break
                except av.FFmpegError as exc:
                    if getattr(exc, "errno", None) == errno.EAGAIN:
                        time.sleep(0.001)
                        continue
                    if self._stop.is_set():
                        break
                    log.warning("x11grab decode: %s", exc)
                    break
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    log.warning("x11grab: %s", exc)
                    break
                if frame is None:
                    continue
                if not self._logged:
                    self._logged = True
                    log.info(
                        "x11grab frame=%sx%s fmt=%s",
                        frame.width,
                        frame.height,
                        frame.format.name if frame.format else "?",
                    )
                try:
                    frame = frame.reformat(format="yuv420p")
                except Exception as exc:
                    log.warning("x11grab reformat: %s", exc)
                    continue
                self._push(frame)
        finally:
            self._container = None
            try:
                container.close()
            except Exception:
                pass

    def _push(self, frame: object) -> None:
        if self._stop.is_set():
            return
        with self._lock:
            self._latest = frame
            self._has.set()

    def _snapshot(self):
        while not self._stop.is_set():
            self._has.wait(timeout=0.05)
            if self._stop.is_set():
                return None
            with self._lock:
                frame = self._latest
                self._has.clear()
            if frame is not None:
                return frame
        return None

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        frame = await loop.run_in_executor(None, self._snapshot)
        if frame is None:
            raise MediaStreamError
        now = time.monotonic()
        if self._origin is None:
            self._origin = now
        frame.pts = int((now - self._origin) * _VIDEO_CLOCK)
        frame.time_base = _VIDEO_TIME_BASE
        return frame

    def stop(self) -> None:
        self._stop.set()
        self._has.set()
        container = self._container
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        super().stop()


class DisplayCaptureSource:
    """x11grab del DISPLAY + Pulse monitor. Encode: H.264 (NVENC/x264) o VP8."""

    def __init__(self, display: str = ":99", draw_mouse: bool = False) -> None:
        self._display = display
        self._draw_mouse = draw_mouse
        self._relay = MediaRelay()
        self._video: Optional[X11GrabTrack] = None
        self._audio: Optional[PulseAudioTrack] = None

    def is_running(self) -> bool:
        return self._video is not None and self._video.readyState == "live"

    def start(self) -> None:
        if self._video is not None:
            return
        log.info(
            "encoder=%s source=x11grab display=%s %s@%s",
            codec_name(),
            self._display,
            CAPTURE_SIZE,
            CAPTURE_FPS,
        )
        track = X11GrabTrack(
            self._display,
            size=CAPTURE_SIZE,
            fps=CAPTURE_FPS,
            draw_mouse=self._draw_mouse,
        )
        track.start()
        self._video = track

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
        if self._video is None:
            return None
        return self._relay.subscribe(self._video, buffered=False)

    def subscribe_audio(self):
        if self._audio is None:
            self._audio = self._start_audio()
        return self._audio

    def stop(self) -> None:
        audio = self._audio
        self._audio = None
        if audio is not None:
            audio.stop()
        video = self._video
        self._video = None
        if video is not None:
            video.stop()


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
