"""Sink del DataChannel `input`.

El pad va a uinput en su hilo. X11 (teclado/ratón) va en otro. Si el
DataChannel se atrasa, solo gana el snapshot más nuevo: analog no espera
un flush de X ni un historial viejo.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from controller.input.gamepad import PadDevice, open_pads
from controller.input.packet import PadSnapshot, Snapshot, new_snapshots, parse_datagram, seq_newer
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
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._pad_job: Optional[dict[int, PadSnapshot]] = None
        self._pad_live: set[int] = set()
        self._keys: Optional[set[int]] = None
        self._buttons: Optional[int] = None
        self._abs: Optional[tuple[int, int]] = None
        self._rel_x = 0
        self._rel_y = 0
        self._wheel = 0
        self._x11_dirty = False
        self._pad_thread: Optional[threading.Thread] = None
        self._x11_thread: Optional[threading.Thread] = None

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
        self._reset_jobs()
        self._pads = open_pads(pads)
        if keyboard or mouse:
            self._x11 = X11Injector(display, width, height)
        self._stop = threading.Event()
        if self._pads:
            self._pad_thread = threading.Thread(
                target=self._run_pads, name="input-pads", daemon=True
            )
            self._pad_thread.start()
        if self._x11 is not None:
            self._x11_thread = threading.Thread(
                target=self._run_x11, name="input-x11", daemon=True
            )
            self._x11_thread.start()
        log.info(
            "input open protocol=udp-latest pads=%s keyboard=%s mouse=%s display=%s",
            pads,
            keyboard,
            mouse,
            display,
        )

    def close(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        pad_thread = self._pad_thread
        x11_thread = self._x11_thread
        self._pad_thread = None
        self._x11_thread = None
        if pad_thread is not None and pad_thread.is_alive():
            pad_thread.join(timeout=2)
        if x11_thread is not None and x11_thread.is_alive():
            x11_thread.join(timeout=2)
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
        self._reset_jobs()

    def handle(self, data: bytes) -> None:
        snaps = parse_datagram(data)
        if snaps is None:
            log.warning("input: datagrama inválido len=%s", len(data))
            return
        latest = snaps[-1]
        if self._applied_seq >= 0 and not seq_newer(latest.seq, self._applied_seq):
            return
        pending = new_snapshots(snaps, self._applied_seq)
        if not pending:
            return
        latest = pending[-1]
        rel_x = 0
        rel_y = 0
        wheel = 0
        for snap in pending:
            if not snap.has_mouse:
                continue
            if not snap.mouse_abs:
                rel_x += snap.mouse_x
                rel_y += snap.mouse_y
            wheel += snap.wheel
        with self._cond:
            self._applied_seq = latest.seq
            self.last_video_frame = latest.frame_id
            self.last_input_monotonic = time.monotonic()
            if latest.has_pads:
                self._pad_job = latest.pads
            if latest.has_keyboard and self._keyboard:
                self._keys = set(latest.keys)
                self._x11_dirty = True
            if latest.has_mouse and self._mouse:
                if latest.mouse_abs:
                    self._abs = (latest.mouse_x, latest.mouse_y)
                self._rel_x += rel_x
                self._rel_y += rel_y
                self._wheel += wheel
                self._buttons = latest.mouse_buttons
                self._x11_dirty = True
            self._cond.notify_all()

    def _reset_jobs(self) -> None:
        self._pad_job = None
        self._keys = None
        self._buttons = None
        self._abs = None
        self._rel_x = 0
        self._rel_y = 0
        self._wheel = 0
        self._x11_dirty = False

    def _run_pads(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while self._pad_job is None and not self._stop.is_set():
                    self._cond.wait(timeout=0.25)
                job = self._pad_job
                self._pad_job = None
            if job is None:
                continue
            self._emit_pads(job)

    def _emit_pads(self, pads: dict[int, PadSnapshot]) -> None:
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

    def _run_x11(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while not self._x11_dirty and not self._stop.is_set():
                    self._cond.wait(timeout=0.25)
                if not self._x11_dirty:
                    continue
                abs_pt = self._abs
                rel = (self._rel_x, self._rel_y)
                wheel = self._wheel
                buttons = self._buttons
                keys = self._keys
                self._abs = None
                self._rel_x = 0
                self._rel_y = 0
                self._wheel = 0
                self._x11_dirty = False
            x11 = self._x11
            if x11 is None:
                continue
            x11.inject(
                abs_pt=abs_pt if self._mouse else None,
                rel=rel if self._mouse else (0, 0),
                wheel=wheel if self._mouse else 0,
                buttons=buttons if self._mouse else None,
                keys=keys if self._keyboard else None,
            )
