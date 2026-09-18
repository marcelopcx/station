import struct
import unittest

from controller.input import (
    ACTION_AXIS,
    ACTION_DOWN,
    ACTION_UP,
    TYPE_KEY,
    TYPE_PAD,
    InputSink,
    parse_packet,
)


def pack(typ=TYPE_PAD, action=ACTION_DOWN, code=0, extra=0) -> bytes:
    return struct.pack("<BBHi", typ, action, code, extra)


class ParsePacketTests(unittest.TestCase):
    def test_button_a_down(self) -> None:
        ev = parse_packet(pack(code=0))
        assert ev is not None
        self.assertTrue(ev.is_pad_button)
        self.assertTrue(ev.pressed)
        self.assertEqual(ev.code, 0)

    def test_button_up(self) -> None:
        ev = parse_packet(pack(action=ACTION_UP, code=0))
        assert ev is not None
        self.assertFalse(ev.pressed)

    def test_axis_left_x(self) -> None:
        ev = parse_packet(pack(action=ACTION_AXIS, code=0, extra=16384))
        assert ev is not None
        self.assertTrue(ev.is_pad_axis)
        self.assertEqual(ev.extra, 16384)

    def test_axis_negative(self) -> None:
        ev = parse_packet(pack(action=ACTION_AXIS, code=1, extra=-32767))
        assert ev is not None
        self.assertEqual(ev.extra, -32767)

    def test_key_is_parsed_not_pad(self) -> None:
        ev = parse_packet(pack(typ=TYPE_KEY, code=38))
        assert ev is not None
        self.assertFalse(ev.is_pad_button)
        self.assertFalse(ev.is_pad_axis)

    def test_wrong_length(self) -> None:
        self.assertIsNone(parse_packet(b"\x03\x01"))

    def test_unknown_type(self) -> None:
        self.assertIsNone(parse_packet(pack(typ=9)))


class InputSinkTests(unittest.TestCase):
    def test_handle_pad_without_uinput(self) -> None:
        sink = InputSink()
        sink.handle(pack(code=0))
        sink.handle(pack(action=ACTION_AXIS, extra=1000))
        sink.handle(pack(typ=TYPE_KEY, code=38))
        sink.close()

    def test_handle_invalid_is_ignored(self) -> None:
        sink = InputSink()
        sink.handle(b"\x00")
        sink.close()


if __name__ == "__main__":
    unittest.main()
