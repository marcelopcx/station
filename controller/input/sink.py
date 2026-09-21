"""Sink del DataChannel `input` (UDP unreliable + historial).

Aplica fotografías en orden de seq. Si faltó un paquete, el actual trae
las 3 anteriores y se reconstruye el hueco sin retransmisión.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from controller.input.gamepad import PadDevice, open_pads
from controller.input.packet import PadSnapshot, Snapshot, new_snapshots, parse_datagram
from controller.input.x11 import X11Injector

log = logging.getLogger("game-station.input")

_REST_AXES = (0, 0, 0, 0, 0, 0)


class InputSink:
    """Pads uinput + teclado/ratón X11, o solo log si no hay backend."""

    def __init__(self) -> None:
        self._pads: list[PadDevice] = []
        self._x11: Optional[X11Injector] = None
        self._keyboard = False
        self._mouse = False
        self.last_input_monotonic: Optional[float] = None
        self.last_video_frame: int = 0
        self._applied_seq = -1
        self._last_keys: set[int] = set()
        self._last_buttons = 0
        self._pad_live: set[int] = set()
        self._healed = 0

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
        self.last_video_frame = 0
        self._applied_seq = -1
        self._last_keys = set()
        self._last_buttons = 0
        self._pad_live = set()
        self._healed = 0
        self._pads = open_pads(pads)
        if keyboard or mouse:
            self._x11 = X11Injector(display, width, height)
        log.info(
            "input open protocol=udp-history pads=%s keyboard=%s mouse=%s display=%s",
            pads,
            keyboard,
            mouse,
            display,
        )

    def close(self) -> None:
        self.last_input_monotonic = None
        for pad in self._pads:
            pad.apply_state(0, _REST_AXES)
            pad.close()
        self._pads = []
        self._pad_live.clear()
        if self._x11 is not None:
            self._x11.close()
            self._x11 = None
        self._keyboard = False
        self._mouse = False
        self._applied_seq = -1
        self._last_keys = set()
        self._last_buttons = 0

    def handle(self, data: bytes) -> None:
        snaps = parse_datagram(data)
        if snaps is None:
            log.warning("input: datagrama inválido len=%s", len(data))
            return
        pending = new_snapshots(snaps, self._applied_seq)
        if not pending:
            return
        self.last_input_monotonic = time.monotonic()
        first = pending[0].seq
        if self._applied_seq >= 0:
            gap = (first - self._applied_seq) & 0xFFFF
            if gap > 1:
                self._healed += gap - 1
                log.info(
                    "input heal gap=%s seq=%s..%s frame=%s",
                    gap - 1,
                    self._applied_seq,
                    pending[-1].seq,
                    pending[-1].frame_id,
                )
        for snap in pending:
            self._apply(snap)
            self._applied_seq = snap.seq
            self.last_video_frame = snap.frame_id

    def _apply(self, snap: Snapshot) -> None:
        if snap.has_pads:
            self._pads_to(snap.pads)
        if snap.has_keyboard and self._keyboard:
            self._keys_to(snap.keys)
        if snap.has_mouse and self._mouse:
            self._mouse_to(snap)

    def _pads_to(self, pads: dict[int, PadSnapshot]) -> None:
        live: set[int] = set()
        for slot, pad_snap in pads.items():
            if slot < 0 or slot >= len(self._pads):
                continue
            self._pads[slot].apply_state(pad_snap.buttons, pad_snap.axes)
            live.add(slot)
        for slot in self._pad_live - live:
            if slot < len(self._pads):
                self._pads[slot].apply_state(0, _REST_AXES)
        self._pad_live = live

    def _keys_to(self, held: set[int]) -> None:
        x11 = self._x11
        if x11 is None:
            self._last_keys = set(held)
            return
        for code in self._last_keys - held:
            x11.key(code, False)
        for code in held - self._last_keys:
            x11.key(code, True)
        self._last_keys = set(held)

    def _mouse_to(self, snap: Snapshot) -> None:
        x11 = self._x11
        if x11 is None:
            self._last_buttons = snap.mouse_buttons
            return
        if snap.mouse_abs:
            x11.move_abs(snap.mouse_x, snap.mouse_y)
        elif snap.mouse_x or snap.mouse_y:
            x11.move_rel(snap.mouse_x, snap.mouse_y)
        changed = self._last_buttons ^ snap.mouse_buttons
        if changed:
            for bit in range(5):
                if not (changed & (1 << bit)):
                    continue
                x11.button(bit, bool(snap.mouse_buttons & (1 << bit)))
            self._last_buttons = snap.mouse_buttons
        if snap.wheel:
            x11.wheel(snap.wheel)
