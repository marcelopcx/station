"""Paquete DataChannel `input` (8 bytes LE) e inyección como gamepad.

B0: parse_packet. B1: log. B5: uinput. type=1/2 se ignoran.
`evdev` es opcional: en el Mac `open()` cae a log.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("game-station.input")

_PACKET = struct.Struct("<BBHi")  # 8 bytes

TYPE_KEY = 1
TYPE_PAD = 3
ACTION_DOWN = 1
ACTION_UP = 2
ACTION_AXIS = 4

try:
    from evdev import AbsInfo, UInput
    from evdev import ecodes as _e

    _EVDEV = True
except ImportError:
    AbsInfo = None  # type: ignore[misc, assignment]
    UInput = None  # type: ignore[misc, assignment]
    _e = None  # type: ignore[assignment]
    _EVDEV = False


@dataclass(frozen=True)
class InputEvent:
    type: int
    action: int
    code: int
    extra: int

    @property
    def is_pad_button(self) -> bool:
        return self.type == TYPE_PAD and self.action in (ACTION_DOWN, ACTION_UP)

    @property
    def is_pad_axis(self) -> bool:
        return self.type == TYPE_PAD and self.action == ACTION_AXIS

    @property
    def pressed(self) -> bool:
        return self.action == ACTION_DOWN


def parse_packet(data: bytes) -> InputEvent | None:
    if len(data) != _PACKET.size:
        return None
    typ, action, code, extra = _PACKET.unpack(data)
    if typ not in (1, 2, 3) or action not in (1, 2, 3, 4):
        return None
    return InputEvent(typ, action, code, extra)


def _pad_maps() -> tuple[dict[int, int], dict[int, int], Any, Any] | None:
    if not _EVDEV or _e is None or AbsInfo is None:
        return None
    btn = {
        0: _e.BTN_SOUTH,
        1: _e.BTN_EAST,
        2: _e.BTN_WEST,
        3: _e.BTN_NORTH,
        4: _e.BTN_TL,
        5: _e.BTN_TR,
        6: _e.BTN_TL2,
        7: _e.BTN_TR2,
        8: _e.BTN_SELECT,
        9: _e.BTN_START,
        10: _e.BTN_THUMBL,
        11: _e.BTN_THUMBR,
        12: _e.BTN_DPAD_UP,
        13: _e.BTN_DPAD_DOWN,
        14: _e.BTN_DPAD_LEFT,
        15: _e.BTN_DPAD_RIGHT,
        16: _e.BTN_MODE,
    }
    abs_map = {
        0: _e.ABS_X,
        1: _e.ABS_Y,
        2: _e.ABS_RX,
        3: _e.ABS_RY,
        4: _e.ABS_Z,
        5: _e.ABS_RZ,
    }
    stick = AbsInfo(value=0, min=-32767, max=32767, fuzz=0, flat=128, resolution=0)
    trigger = AbsInfo(value=0, min=0, max=32767, fuzz=0, flat=0, resolution=0)
    return btn, abs_map, stick, trigger


class InputSink:
    """Pad virtual vía `/dev/uinput`, o solo log si no hay evdev/device."""

    def __init__(self) -> None:
        self._ui: Optional[Any] = None
        self._btn: dict[int, int] = {}
        self._abs: dict[int, int] = {}

    def open(self) -> None:
        if self._ui is not None:
            return
        maps = _pad_maps()
        if maps is None or UInput is None or _e is None:
            log.warning("input_backend=log (evdev no instalado)")
            return
        btn, abs_map, stick, trigger = maps
        self._btn = btn
        self._abs = abs_map
        cap = {
            _e.EV_KEY: list(btn.values()),
            _e.EV_ABS: [
                (_e.ABS_X, stick),
                (_e.ABS_Y, stick),
                (_e.ABS_RX, stick),
                (_e.ABS_RY, stick),
                (_e.ABS_Z, trigger),
                (_e.ABS_RZ, trigger),
            ],
        }
        try:
            self._ui = UInput(
                cap,
                name="Airtek Cloud Pad",
                bustype=_e.BUS_USB,
                vendor=0x045E,
                product=0x028E,
                version=0x0110,
            )
            log.info("input_backend=uinput")
        except OSError:
            self._ui = None
            log.warning("input_backend=log (/dev/uinput no disponible)")

    def close(self) -> None:
        ui = self._ui
        self._ui = None
        if ui is not None:
            ui.close()

    def handle(self, data: bytes) -> None:
        ev = parse_packet(data)
        if ev is None:
            log.warning("input: paquete inválido len=%s", len(data))
            return
        if ev.is_pad_button:
            log.info("input pad %s code=%s", "down" if ev.pressed else "up", ev.code)
            self._button(ev.code, 1 if ev.pressed else 0)
            return
        if ev.is_pad_axis:
            log.info("input axis code=%s extra=%s", ev.code, ev.extra)
            self._axis(ev.code, ev.extra)
            return

    def _button(self, code: int, value: int) -> None:
        if self._ui is None or _e is None:
            return
        btn = self._btn.get(code)
        if btn is None:
            return
        self._ui.write(_e.EV_KEY, btn, value)
        self._ui.syn()

    def _axis(self, code: int, extra: int) -> None:
        if self._ui is None or _e is None:
            return
        axis = self._abs.get(code)
        if axis is None:
            return
        lo, hi = (0, 32767) if axis in (_e.ABS_Z, _e.ABS_RZ) else (-32767, 32767)
        self._ui.write(_e.EV_ABS, axis, max(lo, min(hi, extra)))
        self._ui.syn()
