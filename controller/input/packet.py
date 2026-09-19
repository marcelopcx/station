"""Paquete DataChannel `input` (8 bytes LE).

offset  tipo     significado
0       uint8    type    1=key  2=pointer  3=pad
1       uint8    action  1=down 2=up  3=move  4=axis
2–3     uint16   code    ver abajo
4–7     int32    extra   0 en botones; eje; xy empaquetado

Pad: `code` = (slot << 8) | control. slot 0..3; control botón 0..16 o eje 0..5.
Tecla: `code` = keycode Linux (KEY_*). extra=0.
Puntero: action down/up → `code` botón 0..4 (DOM). action move → code 0=rel 1=abs,
extra = int16 LE x, int16 LE y. action axis → extra = rueda (positivo = arriba).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_PACKET = struct.Struct("<BBHi")  # 8 bytes
_XY = struct.Struct("<hh")

TYPE_KEY = 1
TYPE_POINTER = 2
TYPE_PAD = 3
ACTION_DOWN = 1
ACTION_UP = 2
ACTION_MOVE = 3
ACTION_AXIS = 4

POINTER_REL = 0
POINTER_ABS = 1
MAX_PADS = 4


@dataclass(frozen=True)
class InputEvent:
    type: int
    action: int
    code: int
    extra: int

    @property
    def pad_index(self) -> int:
        if self.type != TYPE_PAD:
            return 0
        return (self.code >> 8) & 0xFF

    @property
    def control(self) -> int:
        if self.type == TYPE_PAD:
            return self.code & 0xFF
        return self.code

    @property
    def is_pad_button(self) -> bool:
        return self.type == TYPE_PAD and self.action in (ACTION_DOWN, ACTION_UP)

    @property
    def is_pad_axis(self) -> bool:
        return self.type == TYPE_PAD and self.action == ACTION_AXIS

    @property
    def is_key(self) -> bool:
        return self.type == TYPE_KEY and self.action in (ACTION_DOWN, ACTION_UP)

    @property
    def is_pointer_button(self) -> bool:
        return self.type == TYPE_POINTER and self.action in (ACTION_DOWN, ACTION_UP)

    @property
    def is_pointer_move(self) -> bool:
        return self.type == TYPE_POINTER and self.action == ACTION_MOVE

    @property
    def is_pointer_wheel(self) -> bool:
        return self.type == TYPE_POINTER and self.action == ACTION_AXIS

    @property
    def pressed(self) -> bool:
        return self.action == ACTION_DOWN

    def unpack_xy(self) -> tuple[int, int]:
        return _XY.unpack(struct.pack("<i", self.extra))


def parse_packet(data: bytes) -> InputEvent | None:
    if len(data) != _PACKET.size:
        return None
    typ, action, code, extra = _PACKET.unpack(data)
    if typ not in (TYPE_KEY, TYPE_POINTER, TYPE_PAD):
        return None
    if action not in (ACTION_DOWN, ACTION_UP, ACTION_MOVE, ACTION_AXIS):
        return None
    return InputEvent(typ, action, code, extra)
