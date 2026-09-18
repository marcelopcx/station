"""Estados de la estación.

Los valores son el wire format de REST y de `{ type: STATE, state }`.

    IDLE ──prepare──► PREPARING ──► READY ──launch──► PLAYING
      ▲                                                │
      └──────────────── stop ──────────────────────────┘
"""

from enum import StrEnum


class StationState(StrEnum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    READY = "READY"
    PLAYING = "PLAYING"
