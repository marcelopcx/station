"""Fuentes de video para `WebrtcSession`.

    SmpteBarsSource         lavfi smptebars (Mac / fallback)
    DisplayCaptureSource    x11grab del DISPLAY del runtime (Spark)

El encode (VP8, libvpx) lo hace aiortc en el `RTCRtpSender`, no estas clases.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Union

from aiortc.contrib.media import MediaPlayer, MediaRelay

from controller.games import needs_display

log = logging.getLogger("game-station.webrtc.media")

SMPTE_LAVFI = "smptebars=size=1280x720:rate=30"
CAPTURE_SIZE = os.environ.get("STATION_SIZE", "1280x720")
CAPTURE_FPS = os.environ.get("STATION_FPS", "30")


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
    """x11grab del DISPLAY del runtime. Encode: lo sigue haciendo aiortc (VP8)."""

    def __init__(self, display: str = ":99") -> None:
        self._display = display
        self._relay = MediaRelay()
        self._player: Optional[MediaPlayer] = None

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

    def subscribe_video(self):
        if self._player is None or self._player.video is None:
            return None
        return self._relay.subscribe(self._player.video, buffered=False)

    def stop(self) -> None:
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
