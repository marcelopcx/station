"""Datagrama UDP de input (SCTP unreliable, mismo 5-tuple ICE que el vídeo).

Cada paquete es una etiqueta + N fotografías de controles (la actual y
las 3 anteriores). Si se pierde un datagrama, el siguiente trae el hueco.

offset  tipo     campo
0       uint8    MAGIC 0xA7  (clasifica: esto es input, no RTP)
1       uint8    VERSION = 3
2       uint8    count        1..4 snapshots, el más viejo primero
3       uint8    reserved
luego, por snapshot:
        uint16   seq
        uint32   frame_id     fotograma de vídeo que veía el cliente
        uint8    flags        bit0 mouse, bit1 abs, bit2 teclado, bit3 pads
        uint8    mouse buttons
        int16    mouse x
        int16    mouse y
        int8     rueda
        uint8    nkeys + uint16 KEY_* × nkeys
        uint8    npads + (uint8 slot, uint32 botones, int16[6] ejes) × npads
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = 0xA7
VERSION = 3
HISTORY = 4
FLAG_MOUSE = 1 << 0
FLAG_MOUSE_ABS = 1 << 1
FLAG_KEYBOARD = 1 << 2
FLAG_PADS = 1 << 3
MAX_KEYS = 24
MAX_PADS = 4

_DGRAM = struct.Struct("<BBBB")
_SNAP = struct.Struct("<HIBBhhb")  # seq, frame, flags, buttons, x, y, wheel
_KEY = struct.Struct("<H")
_PAD = struct.Struct("<BIhhhhhh")


@dataclass
class PadSnapshot:
    slot: int
    buttons: int
    axes: tuple[int, int, int, int, int, int]


@dataclass
class Snapshot:
    seq: int
    frame_id: int = 0
    has_mouse: bool = False
    mouse_abs: bool = False
    mouse_x: int = 0
    mouse_y: int = 0
    mouse_buttons: int = 0
    wheel: int = 0
    has_keyboard: bool = False
    keys: set[int] = field(default_factory=set)
    has_pads: bool = False
    pads: dict[int, PadSnapshot] = field(default_factory=dict)


def encode_datagram(snaps: list[Snapshot]) -> bytes:
    """Simétrico al encoder del cliente. Útil para tests."""
    items = snaps[-HISTORY:]
    if not items:
        return b""
    chunks = [_DGRAM.pack(MAGIC, VERSION, len(items), 0)]
    for snap in items:
        keys = sorted(c for c in snap.keys if c > 0)[:MAX_KEYS]
        pads = [snap.pads[s] for s in sorted(snap.pads) if 0 <= s <= 3][:MAX_PADS]
        flags = 0
        if snap.has_mouse:
            flags |= FLAG_MOUSE
        if snap.mouse_abs:
            flags |= FLAG_MOUSE_ABS
        if snap.has_keyboard:
            flags |= FLAG_KEYBOARD
        if snap.has_pads:
            flags |= FLAG_PADS
        chunks.append(
            _SNAP.pack(
                snap.seq & 0xFFFF,
                snap.frame_id & 0xFFFFFFFF,
                flags,
                snap.mouse_buttons & 0x1F,
                max(-32767, min(32767, snap.mouse_x)),
                max(-32767, min(32767, snap.mouse_y)),
                max(-8, min(8, snap.wheel)),
            )
        )
        chunks.append(bytes([len(keys)]))
        for code in keys:
            chunks.append(_KEY.pack(code & 0xFFFF))
        chunks.append(bytes([len(pads)]))
        for pad in pads:
            a = pad.axes
            chunks.append(
                _PAD.pack(
                    pad.slot & 0x03,
                    pad.buttons & 0xFFFFFFFF,
                    a[0], a[1], a[2], a[3], a[4], a[5],
                )
            )
    return b"".join(chunks)


def seq_newer(seq: int, prev: int) -> bool:
    if prev < 0:
        return True
    delta = (seq - prev) & 0xFFFF
    return 0 < delta < 0x8000


def parse_datagram(data: bytes | bytearray | memoryview) -> list[Snapshot] | None:
    if not data or data[0] != MAGIC:
        return None
    if len(data) < _DGRAM.size:
        return None
    magic, ver, count, _reserved = _DGRAM.unpack_from(data, 0)
    if magic != MAGIC or ver != VERSION or count < 1 or count > HISTORY:
        return None
    off = _DGRAM.size
    snaps: list[Snapshot] = []
    for _ in range(count):
        snap, off = _parse_snapshot(data, off)
        if snap is None:
            return None
        snaps.append(snap)
    return snaps


def _parse_snapshot(
    data: bytes | bytearray | memoryview, off: int
) -> tuple[Snapshot | None, int]:
    if off + _SNAP.size + 2 > len(data):
        return None, off
    seq, frame_id, flags, buttons, mx, my, wheel = _SNAP.unpack_from(data, off)
    off += _SNAP.size
    nkeys = data[off]
    off += 1
    if nkeys > MAX_KEYS or off + nkeys * 2 + 1 > len(data):
        return None, off
    keys: set[int] = set()
    for _ in range(nkeys):
        (code,) = _KEY.unpack_from(data, off)
        if code:
            keys.add(code)
        off += 2
    npads = data[off]
    off += 1
    if npads > MAX_PADS or off + npads * _PAD.size > len(data):
        return None, off
    pads: dict[int, PadSnapshot] = {}
    for _ in range(npads):
        slot, mask, a0, a1, a2, a3, a4, a5 = _PAD.unpack_from(data, off)
        off += _PAD.size
        if slot > 3:
            continue
        pads[slot] = PadSnapshot(slot, mask, (a0, a1, a2, a3, a4, a5))
    return (
        Snapshot(
            seq=seq,
            frame_id=frame_id,
            has_mouse=bool(flags & FLAG_MOUSE),
            mouse_abs=bool(flags & FLAG_MOUSE_ABS),
            mouse_x=mx,
            mouse_y=my,
            mouse_buttons=buttons & 0x1F,
            wheel=int(wheel),
            has_keyboard=bool(flags & FLAG_KEYBOARD),
            keys=keys,
            has_pads=bool(flags & FLAG_PADS),
            pads=pads,
        ),
        off,
    )


def new_snapshots(snaps: list[Snapshot], last_seq: int) -> list[Snapshot]:
    """Snapshots estrictamente posteriores a `last_seq`, en orden de seq."""
    out: list[Snapshot] = []
    for snap in snaps:
        if last_seq < 0 or seq_newer(snap.seq, last_seq):
            out.append(snap)
            last_seq = snap.seq
    return out
