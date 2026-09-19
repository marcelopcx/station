"""Pads virtuales vía `/dev/uinput`.

Hasta 4 dispositivos Xbox 360. El mapping SDL se exporta a
`SDL_GAMECONTROLLERCONFIG` si el manifiesto pide `needs.gamepad` > 0.

`evdev` es opcional: en el Mac `open()` cae a log.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from controller.input.packet import (
    ACTION_AXIS,
    ACTION_DOWN,
    ACTION_UP,
    TYPE_KEY,
    TYPE_PAD,
    InputEvent,
    parse_packet,
)

log = logging.getLogger("game-station.input")

# GUID USB Xbox 360 (045e:028e, version 0x0110) = pad 0 de este módulo.
_SDL_BINDINGS = (
    "a:b0,b:b1,x:b2,y:b3,back:b6,start:b7,guide:b8,"
    "leftshoulder:b4,rightshoulder:b5,leftstick:b9,rightstick:b10,"
    "leftx:a0,lefty:a1,rightx:a3,righty:a4,lefttrigger:a2,righttrigger:a5,"
    "dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,platform:Linux,"
)


def _sdl_guid(product: int) -> str:
    vendor = 0x045E
    version = 0x0110
    raw = bytes(
        [
            0x03,
            0x00,
            0x00,
            0x00,
            vendor & 0xFF,
            (vendor >> 8) & 0xFF,
            0x00,
            0x00,
            product & 0xFF,
            (product >> 8) & 0xFF,
            0x00,
            0x00,
            version & 0xFF,
            (version >> 8) & 0xFF,
            0x00,
            0x00,
        ]
    )
    return raw.hex()


def sdl_controller_config(n: int) -> str:
    """Una línea SDL por pad (product id 0x028E + slot)."""
    n = max(0, min(4, int(n)))
    lines: list[str] = []
    for index in range(n):
        product = 0x028E + index
        name = "Airtek Cloud Pad" if index == 0 else f"Airtek Cloud Pad {index + 1}"
        lines.append(f"{_sdl_guid(product)},{name},{_SDL_BINDINGS}")
    return ("\n".join(lines) + "\n") if lines else ""


SDL_GAMECONTROLLER_MAPPING = sdl_controller_config(1)

try:
    from evdev import AbsInfo, UInput
    from evdev import ecodes as _e

    _EVDEV = True
except ImportError:
    AbsInfo = None  # type: ignore[misc, assignment]
    UInput = None  # type: ignore[misc, assignment]
    _e = None  # type: ignore[assignment]
    _EVDEV = False


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


class PadDevice:
    """Un pad Xbox 360 virtual."""

    def __init__(self, index: int) -> None:
        self.index = index
        self._ui: Optional[Any] = None
        self._btn: dict[int, int] = {}
        self._abs: dict[int, int] = {}
        self._hat_x = 0
        self._hat_y = 0

    def open(self) -> bool:
        maps = _pad_maps()
        if maps is None or UInput is None or _e is None:
            return False
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
                (
                    _e.ABS_HAT0X,
                    AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0),
                ),
                (
                    _e.ABS_HAT0Y,
                    AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0),
                ),
            ],
        }
        product = 0x028E + self.index
        name = "Airtek Cloud Pad" if self.index == 0 else f"Airtek Cloud Pad {self.index + 1}"
        try:
            self._ui = UInput(
                cap,
                name=name,
                bustype=_e.BUS_USB,
                vendor=0x045E,
                product=product,
                version=0x0110,
            )
            dev = getattr(self._ui, "device", None)
            path = getattr(dev, "path", None) if dev is not None else None
            log.info("input_backend=uinput pad=%s path=%s", self.index, path)
            return True
        except OSError:
            self._ui = None
            log.warning("input_backend=log pad=%s (/dev/uinput no disponible)", self.index)
            return False

    def close(self) -> None:
        ui = self._ui
        self._ui = None
        if ui is not None:
            ui.close()

    def button(self, code: int, value: int) -> None:
        if self._ui is None or _e is None:
            return
        if code in (12, 13, 14, 15):
            self._hat(code, value)
            return
        btn = self._btn.get(code)
        if btn is None:
            return
        self._ui.write(_e.EV_KEY, btn, value)
        self._ui.syn()

    def axis(self, code: int, extra: int) -> None:
        if self._ui is None or _e is None:
            return
        axis = self._abs.get(code)
        if axis is None:
            return
        lo, hi = (0, 32767) if axis in (_e.ABS_Z, _e.ABS_RZ) else (-32767, 32767)
        self._ui.write(_e.EV_ABS, axis, max(lo, min(hi, extra)))
        self._ui.syn()

    def _hat(self, code: int, value: int) -> None:
        if self._ui is None or _e is None:
            return
        pressed = value != 0
        if code == 12:
            self._hat_y = -1 if pressed else 0
        elif code == 13:
            self._hat_y = 1 if pressed else 0
        elif code == 14:
            self._hat_x = -1 if pressed else 0
        elif code == 15:
            self._hat_x = 1 if pressed else 0
        self._ui.write(_e.EV_ABS, _e.ABS_HAT0X, self._hat_x)
        self._ui.write(_e.EV_ABS, _e.ABS_HAT0Y, self._hat_y)
        self._ui.syn()


def open_pads(n: int) -> list[PadDevice]:
    n = max(0, min(4, int(n)))
    if n == 0:
        return []
    maps = _pad_maps()
    if maps is None:
        log.warning("input_backend=log (evdev no instalado)")
        return []
    pads = [PadDevice(i) for i in range(n)]
    opened = [pad for pad in pads if pad.open()]
    if opened:
        time.sleep(0.5)
    return pads


# Reexportados: el parser vive en packet.py; el sink público en sink.py.
__all__ = [
    "ACTION_AXIS",
    "ACTION_DOWN",
    "ACTION_UP",
    "InputEvent",
    "PadDevice",
    "SDL_GAMECONTROLLER_MAPPING",
    "TYPE_KEY",
    "TYPE_PAD",
    "open_pads",
    "parse_packet",
    "sdl_controller_config",
]
