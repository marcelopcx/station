"""Manifiesto de juego (`manifest.yaml` en la imagen).

El runtime no compara `game_id == "supertuxkart"`. Aplica `command`, `env`
y `needs` de este documento.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from controller.config import Settings, interpolate
from controller.contract.errors import UnknownGame

log = logging.getLogger("game-station.catalog")


class GameNeeds(BaseModel):
    """Qué inyecta la estación. Cualquier combinación es válida.

    `gamepad`: 0 = no acepta pads; 1, 2, 3 o 4 = esa cantidad a la vez.
    `true`/`false` del YAML viejo se lee como 1 y 0.
    """

    display: bool = True
    audio: bool = True
    gamepad: Literal[0, 1, 2, 3, 4] = 0
    keyboard: bool = False
    mouse: bool = False

    @field_validator("gamepad", mode="before")
    @classmethod
    def _coerce_gamepad(cls, value: object) -> object:
        if value is None:
            return 0
        if isinstance(value, bool):
            return 1 if value else 0
        return value


class GameAudio(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    fallback_args: list[str] = Field(default_factory=list, alias="fallbackArgs")


class GameManifest(BaseModel):
    """Receta bakeada en la imagen. Un contenedor = un `id`."""

    id: str
    version: str = "1.0.0"
    kind: Literal["native", "test-pattern"] = "native"
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    workdir: str | None = None
    needs: GameNeeds = Field(default_factory=GameNeeds)
    audio: GameAudio = Field(default_factory=GameAudio)

    def argv(self, settings: Settings) -> list[str] | None:
        """Argumentos del proceso, o `None` si no hay binario (fuente sintética)."""
        if self.kind == "test-pattern" or not self.command:
            return None
        parts = [interpolate(part, settings) for part in (*self.command, *self.args)]
        return parts

    def interpolated_env(self, settings: Settings) -> dict[str, str]:
        return {key: interpolate(val, settings) for key, val in self.env.items()}


class GameCatalog:
    """Un manifiesto. `require(game_id)` falla si no es el de esta imagen."""

    def __init__(self, manifest: GameManifest) -> None:
        self.manifest = manifest

    @property
    def game_id(self) -> str:
        return self.manifest.id

    def require(self, game_id: str) -> GameManifest:
        if game_id != self.manifest.id:
            raise UnknownGame(game_id, self.manifest.id)
        return self.manifest

    @classmethod
    def load(cls, path: Path) -> GameCatalog:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"manifest inválido: {path}")
        manifest = GameManifest.model_validate(raw)
        log.info(
            "catalog game=%s version=%s kind=%s pads=%s keyboard=%s mouse=%s path=%s",
            manifest.id,
            manifest.version,
            manifest.kind,
            manifest.needs.gamepad,
            manifest.needs.keyboard,
            manifest.needs.mouse,
            path,
        )
        return cls(manifest)


def load_catalog(path: Path) -> GameCatalog | None:
    """`None` si no hay archivo (imagen runtime sin juego; tests)."""
    if not path.is_file():
        log.warning("no hay manifiesto en %s", path)
        return None
    return GameCatalog.load(path)
