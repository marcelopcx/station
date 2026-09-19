"""Input remoto: pads uinput + teclado/ratón XTEST. No conoce títulos."""

from controller.input.gamepad import (
    SDL_GAMECONTROLLER_MAPPING,
    sdl_controller_config,
)
from controller.input.packet import InputEvent, parse_packet
from controller.input.sink import InputSink

__all__ = [
    "SDL_GAMECONTROLLER_MAPPING",
    "InputEvent",
    "InputSink",
    "parse_packet",
    "sdl_controller_config",
]
