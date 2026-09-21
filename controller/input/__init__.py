"""Input remoto: pads uinput + teclado/ratón XTEST. No conoce títulos."""

from controller.input.gamepad import (
    SDL_GAMECONTROLLER_MAPPING,
    sdl_controller_config,
)
from controller.input.packet import Snapshot, parse_datagram
from controller.input.sink import InputSink

__all__ = [
    "SDL_GAMECONTROLLER_MAPPING",
    "InputSink",
    "Snapshot",
    "parse_datagram",
    "sdl_controller_config",
]
