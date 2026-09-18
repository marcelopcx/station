"""Fuente de video: barras SMPTE vía FFmpeg lavfi.

    lavfi smptebars 1280×720@30  →  MediaPlayer (PyAV, format=lavfi)
                                 →  VideoStreamTrack
                                 →  MediaRelay.subscribe
                                 →  pc.addTrack

`MediaPlayer.video` es de un solo consumidor; el relay clona el track.
El encode (VP8, libvpx) lo hace aiortc en el `RTCRtpSender`, no esta clase.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiortc.contrib.media import MediaPlayer, MediaRelay

log = logging.getLogger("game-station.webrtc.media")

SMPTE_LAVFI = "smptebars=size=1280x720:rate=30"


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
        return self._relay.subscribe(self._player.video)

    def stop(self) -> None:
        player = self._player
        self._player = None
        if player is None:
            return
        if player.video:
            player.video.stop()
        if player.audio:
            player.audio.stop()
