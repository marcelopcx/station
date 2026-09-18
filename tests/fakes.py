"""`FakeStream` implementa `MediaSession` sin PyAV ni `RTCPeerConnection`."""


class FakeStream:
    def __init__(self) -> None:
        self.started = False
        self.stop_count = 0
        self.game_id: str | None = None

    async def start_source(self, game_id: str) -> None:
        self.started = True
        self.game_id = game_id

    async def stop(self) -> None:
        self.started = False
        self.stop_count += 1

    async def attach(self, _ws) -> None:
        return


class BoomStream(FakeStream):
    async def start_source(self, game_id: str) -> None:
        self.game_id = game_id
        raise RuntimeError("no display")
