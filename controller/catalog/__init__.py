"""Catálogo de la imagen: un manifiesto, un gameId.

No hay tabla de títulos en Python. El loader elige la imagen; esta
estación solo sabe lanzar el juego bakeado en `/opt/game/manifest.yaml`.
"""

from controller.catalog.manifest import GameCatalog, GameManifest, load_catalog

__all__ = ["GameCatalog", "GameManifest", "load_catalog"]
