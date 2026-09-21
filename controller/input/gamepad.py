"""Pads virtuales vía `/dev/uinput`.

Hasta 4 dispositivos Xbox 360. El mapping SDL se exporta a
`SDL_GAMECONTROLLERCONFIG` si el manifiesto pide `needs.gamepad` > 0.

`evdev` es opcional: en el Mac `open()` cae a log.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Sequence

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
    # Índices joydev = orden del código evdev, no el orden de este dict.
    # BTN_X del kernel es BTN_NORTH (0x133) y BTN_Y es BTN_WEST (0x134).
    # Sin BTN_TL2/TR2 los gatillos van solo por eje y Select/Start no se corren.
    # Queda igual que _SDL_BINDINGS (a:b0 … rightstick:b10).
    def code(name: str, fallback: int) -> int:
        return int(getattr(_e, name, fallback))

    btn = {
        0: code("BTN_SOUTH", 0x130),  # A  b0
        1: code("BTN_EAST", 0x131),  # B  b1
        2: code("BTN_NORTH", 0x133),  # X  b2
        3: code("BTN_WEST", 0x134),  # Y  b3
        4: code("BTN_TL", 0x136),  # LB b4
        5: code("BTN_TR", 0x137),  # RB b5
        8: code("BTN_SELECT", 0x13A),  # View b6
        9: code("BTN_START", 0x13B),  # Menu b7
        10: code("BTN_THUMBL", 0x13D),  # LS b9
        11: code("BTN_THUMBR", 0x13E),  # RS b10
        16: code("BTN_MODE", 0x13C),  # Guide b8
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


def _hat_from_mask(mask: int) -> tuple[int, int]:
    y = -1 if mask & (1 << 12) else (1 if mask & (1 << 13) else 0)
    x = -1 if mask & (1 << 14) else (1 if mask & (1 << 15) else 0)
    return x, y


class PadDevice:
    """Un pad Xbox 360 virtual."""

    def __init__(self, index: int) -> None:
        self.index = index
        self._ui: Optional[Any] = None
        self._btn: dict[int, int] = {}
        self._abs: dict[int, int] = {}
        self._hat_x = 0
        self._hat_y = 0
        self._prev_mask = 0
        self._prev_axes = [0, 0, 0, 0, 0, 0]
        self._triggers: set[int] = set()

    def open(self) -> bool:
        maps = _pad_maps()
        if maps is None or UInput is None or _e is None:
            return False
        btn, abs_map, stick, trigger = maps
        self._btn = btn
        self._abs = abs_map
        if _e is not None:
            self._triggers = {_e.ABS_Z, _e.ABS_RZ}
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

    def apply_state(self, mask: int, axes: Sequence[int]) -> None:
        if self._ui is None or _e is None:
            return
        mask = int(mask) & 0x1FFFF
        wrote = False
        for code in range(17):
            if code in (12, 13, 14, 15):
                continue
            down = 1 if (mask >> code) & 1 else 0
            prev = 1 if (self._prev_mask >> code) & 1 else 0
            if down == prev:
                continue
            btn = self._btn.get(code)
            if btn is None:
                continue
            self._ui.write(_e.EV_KEY, btn, down)
            wrote = True
        hat_x, hat_y = _hat_from_mask(mask)
        if hat_x != self._hat_x:
            self._ui.write(_e.EV_ABS, _e.ABS_HAT0X, hat_x)
            self._hat_x = hat_x
            wrote = True
        if hat_y != self._hat_y:
            self._ui.write(_e.EV_ABS, _e.ABS_HAT0Y, hat_y)
            self._hat_y = hat_y
            wrote = True
        n = min(6, len(axes))
        for i in range(n):
            axis = self._abs.get(i)
            if axis is None:
                continue
            lo, hi = (0, 32767) if axis in self._triggers else (-32767, 32767)
            val = max(lo, min(hi, int(axes[i])))
            if self._prev_axes[i] == val:
                continue
            self._ui.write(_e.EV_ABS, axis, val)
            self._prev_axes[i] = val
            wrote = True
        if wrote:
            self._ui.syn()
        self._prev_mask = mask

    def button(self, code: int, value: int) -> None:
        mask = self._prev_mask
        if value:
            mask |= 1 << code
        else:
            mask &= ~(1 << code)
        self.apply_state(mask, self._prev_axes)

    def axis(self, code: int, extra: int) -> None:
        axes = list(self._prev_axes)
        if 0 <= code < 6:
            axes[code] = extra
        self.apply_state(self._prev_mask, axes)


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


__all__ = [
    "PadDevice",
    "SDL_GAMECONTROLLER_MAPPING",
    "open_pads",
    "sdl_controller_config",
]
