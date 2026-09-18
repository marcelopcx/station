import unittest

from controller.errors import GameNotReady, PrepareInProgress, StationBusy
from controller.hub import Hub
from controller.machine import Station
from controller.states import StationState
from tests.fakes import FakeStream


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


class StationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.stream = FakeStream()
        self.station = Station(Hub(), self.stream, prepare_step_s=0)

    async def test_launch_before_prepare_fails(self) -> None:
        with self.assertRaises(GameNotReady):
            await self.station.launch("s1", "g1")
        self.assertFalse(self.stream.started)

    async def test_prepare_launch_stop(self) -> None:
        await self.station.prepare("s1", "g1")
        assert self.station._prepare_task is not None
        await self.station._prepare_task
        self.assertEqual(self.station.state, StationState.READY)

        result = await self.station.launch("s1", "g1")
        self.assertEqual(result["state"], "PLAYING")
        self.assertEqual(result["wsUrl"], "/ws/webrtc")
        self.assertTrue(self.stream.started)

        with self.assertRaises(StationBusy):
            await self.station.launch("s1", "g1")

        await self.station.stop()
        self.assertEqual(self.station.state, StationState.IDLE)
        self.assertEqual(self.stream.stop_count, 1)
        self.assertFalse(self.stream.started)

    async def test_prepare_while_preparing_fails(self) -> None:
        self.station.state = StationState.PREPARING
        with self.assertRaises(PrepareInProgress):
            await self.station.prepare("s1", "g1")

    async def test_health_snapshot_uses_contract_strings(self) -> None:
        snap = self.station.snapshot()
        self.assertEqual(snap["status"], "UP")
        self.assertEqual(snap["state"], "IDLE")
        self.assertEqual(snap["stationId"], "spark-1")

    async def test_webrtc_without_playing_sends_not_playing(self) -> None:
        ws = FakeWs()
        await self.station.attach_webrtc(ws)
        self.assertTrue(ws.closed)
        self.assertEqual(ws.sent, ['{"type": "ERROR", "code": "NOT_PLAYING"}'])


if __name__ == "__main__":
    unittest.main()
