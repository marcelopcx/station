"""Sink del DataChannel `input`.

Rutea type=3 a N pads uinput, type=1/2 a XTEST si el manifiesto lo pide.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from controller.input.gamepad import PadDevice, open_pads
from controller.input.packet import (
    POINTER_ABS,
    InputEvent,
    parse_packet,
)
from controller.input.x11 import X11Injector

log = logging.getLogger("game-station.input")


class InputSink:
    """Pads uinput + teclado/ratón X11, o solo log si no hay backend."""

    def __init__(self) -> None:
        self._pads: list[PadDevice] = []
        self._x11: Optional[X11Injector] = None
        self._keyboard = False
        self._mouse = False
        self.last_input_monotonic: Optional[float] = None

    def open(
        self,
        *,
        pads: int = 0,
        keyboard: bool = False,
        mouse: bool = False,
        display: str = ":99",
        width: int = 1280,
        height: int = 720,
    ) -> None:
        self.close()
        self._keyboard = bool(keyboard)
        self._mouse = bool(mouse)
        self.last_input_monotonic = None
        self._pads = open_pads(pads)
        if keyboard or mouse:
            self._x11 = X11Injector(display, width, height)
        log.info(
            "input open pads=%s keyboard=%s mouse=%s display=%s",
            pads,
            keyboard,
            mouse,
            display,
        )

    def close(self) -> None:
        self.last_input_monotonic = None
        for pad in self._pads:
            pad.close()
        self._pads = []
        if self._x11 is not None:
            self._x11.close()
            self._x11 = None
        self._keyboard = False
        self._mouse = False

    def handle(self, data: bytes) -> None:
        ev = parse_packet(data)
        if ev is None:
            log.warning("input: paquete inválido len=%s", len(data))
            return
        self.last_input_monotonic = time.monotonic()
        if ev.is_pad_button or ev.is_pad_axis:
            self._pad(ev)
            return
        if ev.is_key:
            self._key(ev)
            return
        if ev.is_pointer_button or ev.is_pointer_move or ev.is_pointer_wheel:
            self._pointer(ev)

    def _pad(self, ev: InputEvent) -> None:
        slot = ev.pad_index
        if slot < 0 or slot >= len(self._pads):
            log.info(
                "input pad=%s %s code=%s extra=%s (sin dispositivo)",
                slot,
                "axis" if ev.is_pad_axis else ("down" if ev.pressed else "up"),
                ev.control,
                ev.extra,
            )
            return
        pad = self._pads[slot]
        if ev.is_pad_button:
            log.info(
                "input pad=%s %s code=%s",
                slot,
                "down" if ev.pressed else "up",
                ev.control,
            )
            pad.button(ev.control, 1 if ev.pressed else 0)
            return
        log.info("input pad=%s axis code=%s extra=%s", slot, ev.control, ev.extra)
        pad.axis(ev.control, ev.extra)

    def _key(self, ev: InputEvent) -> None:
        if not self._keyboard:
            return
        log.info("input key %s code=%s", "down" if ev.pressed else "up", ev.control)
        if self._x11 is None:
            return
        self._x11.key(ev.control, ev.pressed)

    def _pointer(self, ev: InputEvent) -> None:
        if not self._mouse or self._x11 is None:
            return
        if ev.is_pointer_button:
            log.info(
                "input mouse %s button=%s",
                "down" if ev.pressed else "up",
                ev.control,
            )
            self._x11.button(ev.control, ev.pressed)
            return
        if ev.is_pointer_wheel:
            self._x11.wheel(ev.extra)
            return
        x, y = ev.unpack_xy()
        if ev.control == POINTER_ABS:
            self._x11.move_abs(x, y)
            return
        self._x11.move_rel(x, y)
