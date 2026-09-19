"""Gamepad virtual. No conoce títulos."""

from controller.input.gamepad import (
    SDL_GAMECONTROLLER_MAPPING,
    InputEvent,
    InputSink,
    parse_packet,
)

__all__ = [
    "SDL_GAMECONTROLLER_MAPPING",
    "InputEvent",
    "InputSink",
    "parse_packet",
]
