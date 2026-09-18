"""`FakeStream` implementa `MediaSession` sin PyAV ni `RTCPeerConnection`."""

from __future__ import annotations


class FakeStream:
    def __init__(self) -> None:
        self.started = False
        self.stop_count = 0
        self.game_id: str | None = None
        self.last_input: float | None = None
        self._encoder = "vp8"

    async def start_source(self, game_id: str) -> None:
        self.started = True
        self.game_id = game_id

    async def stop(self) -> None:
        self.started = False
        self.stop_count += 1

    async def attach(self, _ws) -> None:
        return

    def encoder_name(self) -> str | None:
        return self._encoder if self.started else None

    def last_input_monotonic(self) -> float | None:
        return self.last_input


class BoomStream(FakeStream):
    async def start_source(self, game_id: str) -> None:
        self.game_id = game_id
        raise RuntimeError("no display")
