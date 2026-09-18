import os
import unittest
from unittest.mock import patch

from controller.games import argv_for, needs_display


class GamesTests(unittest.TestCase):
    def test_test_pattern_has_no_process(self) -> None:
        self.assertIsNone(argv_for("test-pattern"))
        self.assertFalse(needs_display("test-pattern"))

    @patch("controller.games.os.path.isfile", return_value=False)
    def test_stk_needs_display(self, _isfile) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STK_BIN", None)
            argv = argv_for("supertuxkart")
        assert argv is not None
        self.assertEqual(argv[0], "supertuxkart")
        self.assertTrue(needs_display("supertuxkart"))

    def test_stk_bin_env(self) -> None:
        with patch.dict(os.environ, {"STK_BIN": "/opt/stk/run_game.sh"}):
            argv = argv_for("supertuxkart")
        assert argv is not None
        self.assertEqual(argv[0], "/opt/stk/run_game.sh")
        self.assertIn("--fullscreen", argv)
        self.assertNotIn("--disable-sound", argv)

    def test_unknown_falls_back_to_smpte(self) -> None:
        self.assertIsNone(argv_for("no-such-game"))
        self.assertFalse(needs_display("no-such-game"))


if __name__ == "__main__":
    unittest.main()
