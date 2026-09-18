import asyncio
import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from controller.errors import GameNotReady, PrepareInProgress, StationBusy
from controller.hub import Hub
from controller.machine import Station
from controller.models import Source
from controller.states import StationState
from tests.fakes import BoomStream, FakeStream


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


def _seed_library(root: Path, game_id: str = "g1", version: str = "1.0.0") -> tuple[str, str]:
    lib = root / "library" / game_id / version
    lib.mkdir(parents=True)
    payload = b"airtek-cache-payload" * 200
    (lib / "payload.bin").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (lib / "checksum").write_text(f"sha256:{digest}\n")
    cache = root / "cache"
    cache.mkdir()
    return f"sha256:{digest}", str(lib)


class StationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.checksum, self.lib_path = _seed_library(root)
        self.stream = FakeStream()
        self.station = Station(
            Hub(),
            self.stream,
            prepare_step_s=0,
            library_root=root / "library",
            cache_root=root / "cache",
            idle_timeout_s=0,
            failed_idle_s=-1,
        )
        self.source = Source(
            type="local", path=self.lib_path, checksum=self.checksum
        )

    async def asyncTearDown(self) -> None:
        await self.station.stop()
        self._tmp.cleanup()

    async def _ready(self) -> None:
        await self.station.prepare("s1", "g1", "1.0.0", self.source)
        assert self.station._prepare_task is not None
        await self.station._prepare_task

    async def test_launch_before_prepare_fails(self) -> None:
        with self.assertRaises(GameNotReady):
            await self.station.launch("s1", "g1")
        self.assertFalse(self.stream.started)

    async def test_prepare_launch_stop(self) -> None:
        await self._ready()
        self.assertEqual(self.station.state, StationState.READY)

        result = await self.station.launch("s1", "g1")
        self.assertEqual(result["state"], "PLAYING")
        self.assertEqual(result["wsUrl"], "/ws/webrtc")
        self.assertTrue(self.stream.started)
        self.assertEqual(self.stream.game_id, "g1")

        with self.assertRaises(StationBusy):
            await self.station.launch("s1", "g1")

        await self.station.stop()
        self.assertEqual(self.station.state, StationState.IDLE)
        self.assertEqual(self.stream.stop_count, 1)
        self.assertFalse(self.stream.started)

    async def test_prepare_while_preparing_fails(self) -> None:
        self.station.state = StationState.PREPARING
        with self.assertRaises(PrepareInProgress):
            await self.station.prepare("s1", "g1", "1.0.0", self.source)

    async def test_health_snapshot_uses_contract_strings(self) -> None:
        snap = self.station.snapshot()
        self.assertEqual(snap["status"], "UP")
        self.assertEqual(snap["state"], "IDLE")
        self.assertEqual(snap["stationId"], "spark-1")
        self.assertIsNone(snap["encoder"])
        self.assertEqual(snap["cache"], [])

    async def test_health_encoder_when_playing(self) -> None:
        await self._ready()
        await self.station.launch("s1", "g1")
        snap = self.station.snapshot()
        self.assertEqual(snap["encoder"], "vp8")
        self.assertEqual(snap["state"], "PLAYING")

    async def test_prepare_cache_hit_on_second_call(self) -> None:
        await self._ready()
        self.assertFalse(self.station._last_cache_hit)
        await self.station.stop()
        await self._ready()
        self.assertTrue(self.station._last_cache_hit)
        cache = self.station.snapshot()["cache"]
        self.assertEqual(cache, [{"gameId": "g1", "version": "1.0.0"}])

    async def test_checksum_mismatch_fails(self) -> None:
        bad = Source(type="local", path=self.lib_path, checksum="sha256:" + "ab" * 32)
        await self.station.prepare("s1", "g1", "1.0.0", bad)
        assert self.station._prepare_task is not None
        await self.station._prepare_task
        self.assertEqual(self.station.state, StationState.FAILED)
        self.assertIsNone(self.station.snapshot()["encoder"])

    async def test_webrtc_without_playing_sends_not_playing(self) -> None:
        ws = FakeWs()
        await self.station.attach_webrtc(ws)
        self.assertTrue(ws.closed)
        self.assertEqual(ws.sent, ['{"type": "ERROR", "code": "NOT_PLAYING"}'])

    async def test_launch_rolls_back_when_source_fails(self) -> None:
        stream = BoomStream()
        root = Path(self._tmp.name)
        station = Station(
            Hub(),
            stream,
            prepare_step_s=0,
            library_root=root / "library",
            cache_root=root / "cache",
            idle_timeout_s=0,
            failed_idle_s=-1,
        )
        await station.prepare("s1", "g1", "1.0.0", self.source)
        assert station._prepare_task is not None
        await station._prepare_task
        with self.assertRaises(RuntimeError):
            await station.launch("s1", "g1")
        self.assertEqual(station.state, StationState.IDLE)
        self.assertEqual(stream.stop_count, 1)
        self.assertFalse(stream.started)
        await station.stop()

    async def test_idle_timeout_stops_session(self) -> None:
        self.station._idle_timeout_s = 0.05
        await self._ready()
        await self.station.launch("s1", "g1")
        self.assertEqual(self.station.state, StationState.PLAYING)
        await asyncio.sleep(0.2)
        self.assertEqual(self.station.state, StationState.IDLE)
        self.assertGreaterEqual(self.stream.stop_count, 1)


class InputTimestampTests(unittest.TestCase):
    def test_handle_sets_last_input(self) -> None:
        from controller.input import ACTION_DOWN, TYPE_PAD, InputSink
        import struct

        sink = InputSink()
        self.assertIsNone(sink.last_input_monotonic)
        sink.handle(struct.pack("<BBHi", TYPE_PAD, ACTION_DOWN, 0, 0))
        self.assertIsNotNone(sink.last_input_monotonic)
        self.assertLess(time.monotonic() - sink.last_input_monotonic, 1)


if __name__ == "__main__":
    unittest.main()
