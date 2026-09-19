"""Teclado y ratón hacia el DISPLAY vía XTEST.

Xvfb no lee uinput; los juegos con `SDL_VIDEODRIVER=x11` sí ven estos
eventos. Sin python-xlib o sin DISPLAY, solo log.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

log = logging.getLogger("game-station.input")

try:
    import Xlib.threaded  # noqa: F401  — antes de Display
    from Xlib import X
    from Xlib.display import Display

    _X11 = True
except ImportError:
    X = None  # type: ignore[assignment]
    Display = None  # type: ignore[misc, assignment]
    _X11 = False

# Linux KEY_* → X keycode (evdev + 8). 0 = no inyectar.
_LINUX_TO_X = 8


class X11Injector:
    def __init__(self, display: str, width: int, height: int) -> None:
        self._name = display
        self._width = max(1, width)
        self._height = max(1, height)
        self._dpy: Optional[Any] = None
        self._failed = not _X11
        self._tries = 0
        self._lock = threading.Lock()
        if not _X11:
            log.warning("input_backend=log (python-xlib no instalado)")

    def close(self) -> None:
        with self._lock:
            dpy = self._dpy
            self._dpy = None
            if dpy is not None:
                try:
                    dpy.close()
                except Exception:
                    pass

    def key(self, linux_code: int, pressed: bool) -> None:
        if linux_code <= 0:
            return
        xcode = linux_code + _LINUX_TO_X
        with self._lock:
            dpy = self._conn()
            if dpy is None or X is None:
                return
            kind = X.KeyPress if pressed else X.KeyRelease
            dpy.xtest_fake_input(kind, xcode)
            dpy.sync()

    def button(self, dom_button: int, pressed: bool) -> None:
        xbtn = _dom_to_x_button(dom_button)
        if xbtn is None:
            return
        with self._lock:
            dpy = self._conn()
            if dpy is None or X is None:
                return
            kind = X.ButtonPress if pressed else X.ButtonRelease
            dpy.xtest_fake_input(kind, xbtn)
            dpy.sync()

    def move_rel(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        with self._lock:
            dpy = self._conn()
            if dpy is None or X is None:
                return
            # detail=1 → motion relativo (XTestFakeRelativeMotionEvent)
            dpy.xtest_fake_input(X.MotionNotify, 1, x=dx, y=dy)
            dpy.sync()

    def move_abs(self, x: int, y: int) -> None:
        x = max(0, min(self._width - 1, x))
        y = max(0, min(self._height - 1, y))
        with self._lock:
            dpy = self._conn()
            if dpy is None or X is None:
                return
            dpy.xtest_fake_input(X.MotionNotify, 0, x=x, y=y)
            dpy.sync()

    def wheel(self, ticks: int) -> None:
        if ticks == 0:
            return
        xbtn = 4 if ticks > 0 else 5
        n = min(8, abs(int(ticks)))
        with self._lock:
            dpy = self._conn()
            if dpy is None or X is None:
                return
            for _ in range(n):
                dpy.xtest_fake_input(X.ButtonPress, xbtn)
                dpy.xtest_fake_input(X.ButtonRelease, xbtn)
            dpy.sync()

    def _conn(self) -> Optional[Any]:
        if self._failed or Display is None:
            return None
        if self._dpy is None:
            try:
                dpy = Display(self._name)
                if not dpy.has_extension("XTEST"):
                    dpy.close()
                    raise RuntimeError("sin extensión XTEST")
                self._dpy = dpy
                self._tries = 0
                log.info("input_backend=xtest display=%s", self._name)
            except Exception as exc:
                self._tries += 1
                if self._tries >= 5:
                    self._failed = True
                    log.warning("input_backend=log (X11 %s)", exc)
                return None
        return self._dpy


def _dom_to_x_button(dom: int) -> Optional[int]:
    # DOM 0/1/2/3/4 → X 1/2/3/8/9 (left/middle/right/back/forward)
    mapping = {0: 1, 1: 2, 2: 3, 3: 8, 4: 9}
    return mapping.get(dom)
