"""`FakeStream` implementa `MediaSession` sin PyAV ni `RTCPeerConnection`."""


class FakeStream:
    def __init__(self) -> None:
        self.started = False
        self.stop_count = 0

    def start_source(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False
        self.stop_count += 1

    async def attach(self, _ws) -> None:
        return
