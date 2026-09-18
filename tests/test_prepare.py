import hashlib
import tempfile
import unittest
from pathlib import Path

from controller.models import Source
from controller.prepare import FilePreparer, PrepareError, list_cache, parse_sha256


class PrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lib = self.root / "library" / "stk" / "1.0.0"
        self.lib.mkdir(parents=True)
        self.cache = self.root / "cache"
        self.payload = b"z" * 5000
        (self.lib / "payload.bin").write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()
        (self.lib / "checksum").write_text(f"sha256:{self.digest}\n")
        self.preparer = FilePreparer(self.root / "library", self.cache)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_sha256(self) -> None:
        self.assertEqual(parse_sha256("sha256:ABC"), "abc")
        self.assertEqual(parse_sha256("deadbeef"), "deadbeef")

    def test_copy_then_cache_hit(self) -> None:
        ticks: list[int] = []
        src = Source(
            type="local",
            path=str(self.lib),
            checksum=f"sha256:{self.digest}",
        )
        first = self.preparer.run("stk", "1.0.0", src, lambda p, _m: ticks.append(p))
        self.assertFalse(first.cache_hit)
        self.assertTrue((self.cache / "stk" / "1.0.0" / "payload.bin").is_file())
        second = self.preparer.run("stk", "1.0.0", src, lambda p, _m: ticks.append(p))
        self.assertTrue(second.cache_hit)
        self.assertEqual(
            list_cache(self.cache), [{"gameId": "stk", "version": "1.0.0"}]
        )

    def test_placeholder_uses_sidecar(self) -> None:
        src = Source(type="local", path=str(self.lib), checksum="sha256:00")
        out = self.preparer.run("stk", "1.0.0", src, lambda *_: None)
        self.assertFalse(out.cache_hit)
        self.assertTrue(out.checksum.endswith(self.digest))

    def test_mismatch(self) -> None:
        src = Source(type="local", path=str(self.lib), checksum="sha256:" + "ab" * 32)
        with self.assertRaises(PrepareError) as cm:
            self.preparer.run("stk", "1.0.0", src, lambda *_: None)
        self.assertEqual(cm.exception.code, "CHECKSUM_MISMATCH")

    def test_azure_sas_rejected(self) -> None:
        src = Source(
            type="azure-sas",
            url="https://example.blob.core.windows.net/game?sas=1",
            checksum=f"sha256:{self.digest}",
        )
        with self.assertRaises(PrepareError) as cm:
            self.preparer.run("stk", "1.0.0", src, lambda *_: None)
        self.assertEqual(cm.exception.code, "UNSUPPORTED_SOURCE")

    def test_missing_path(self) -> None:
        src = Source(
            type="local",
            path=str(self.root / "nope"),
            checksum=f"sha256:{self.digest}",
        )
        with self.assertRaises(PrepareError) as cm:
            self.preparer.run("stk", "1.0.0", src, lambda *_: None)
        self.assertEqual(cm.exception.code, "SOURCE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
