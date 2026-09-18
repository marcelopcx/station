"""S4: copiar `source.path` de /library a /cache y verificar checksum.

`source.type=azure-sas` queda para post-prototipo (misma forma que `http`:
una URL firmada). Este módulo no habla con Azure.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from controller.models import Source

log = logging.getLogger("game-station.prepare")

ProgressFn = Callable[[int, str], None]

_CHUNK = 1024 * 1024
_PLACEHOLDER = {"", "00", "0"}


class PrepareError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PrepareOutcome:
    cache_hit: bool
    game_id: str
    version: str
    checksum: str
    dest: Path


def _digest_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_sha256(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    return raw


def _is_placeholder(digest: str) -> bool:
    return digest in _PLACEHOLDER or set(digest) <= {"0"}


def payload_file(root: Path) -> Path:
    if root.is_file():
        return root
    candidate = root / "payload.bin"
    if candidate.is_file():
        return candidate
    raise PrepareError("SOURCE_NOT_FOUND", f"no hay payload.bin en {root}")


def read_sidecar_checksum(root: Path) -> Optional[str]:
    for name in ("checksum", "payload.bin.sha256"):
        side = root / name if root.is_dir() else root.with_name(name)
        if side.is_file():
            return parse_sha256(side.read_text(encoding="utf-8").split()[0])
    return None


def resolve_source_path(path: str, library_root: Path) -> Path:
    given = Path(path)
    if given.exists():
        return given
    try:
        rel = Path(path).relative_to("/library")
    except ValueError:
        mapped = library_root / Path(path).name
        return mapped if mapped.exists() else given
    mapped = library_root / rel
    return mapped if mapped.exists() else given


def cache_dest(cache_root: Path, game_id: str, version: str) -> Path:
    return cache_root / game_id / version


def list_cache(cache_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if not cache_root.is_dir():
        return entries
    for game_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
        for ver_dir in sorted(p for p in game_dir.iterdir() if p.is_dir()):
            try:
                payload_file(ver_dir)
            except PrepareError:
                continue
            entries.append({"gameId": game_dir.name, "version": ver_dir.name})
    return entries


def _copy_file(src: Path, dest: Path, on_progress: ProgressFn) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = max(src.stat().st_size, 1)
    copied = 0
    with src.open("rb") as inf, tmp.open("wb") as out:
        while True:
            chunk = inf.read(_CHUNK)
            if not chunk:
                break
            out.write(chunk)
            copied += len(chunk)
            pct = min(99, int(copied * 100 / total))
            on_progress(pct, "Copiando assets")
    tmp.replace(dest)


class FilePreparer:
    """Copia local `/library` → `/cache`. `http` / `azure-sas` no se bajan aún."""

    def __init__(
        self,
        library_root: str | os.PathLike[str],
        cache_root: str | os.PathLike[str],
    ) -> None:
        self.library_root = Path(library_root)
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        game_id: str,
        version: str,
        source: Source,
        on_progress: ProgressFn,
    ) -> PrepareOutcome:
        if source.type == "azure-sas":
            # Misma forma que `http` (URL firmada). No hay SDK de Azure en este corte.
            raise PrepareError(
                "UNSUPPORTED_SOURCE",
                "azure-sas entra después del prototipo; usá source.type=local",
            )
        if source.type == "http":
            raise PrepareError(
                "UNSUPPORTED_SOURCE",
                "source.type=http no está en este corte; usá local",
            )
        if not source.path:
            raise PrepareError("SOURCE_NOT_FOUND", "source.path vacío")

        src_root = resolve_source_path(source.path, self.library_root)
        if not src_root.exists():
            raise PrepareError("SOURCE_NOT_FOUND", f"no existe {source.path}")

        src_payload = payload_file(src_root)
        expected = parse_sha256(source.checksum)
        if _is_placeholder(expected):
            sidecar = read_sidecar_checksum(src_root)
            if sidecar:
                expected = sidecar
                log.info("checksum sidecar game=%s version=%s", game_id, version)
            else:
                raise PrepareError(
                    "CHECKSUM_MISMATCH",
                    "checksum placeholder y no hay sidecar en library",
                )

        dest_root = cache_dest(self.cache_root, game_id, version)
        dest_payload = dest_root / "payload.bin"
        if dest_payload.is_file() and _digest_of(dest_payload) == expected:
            on_progress(100, "Cache hit")
            log.info(
                "prepare cacheHit=true game=%s version=%s checksum=sha256:%s",
                game_id,
                version,
                expected,
            )
            return PrepareOutcome(True, game_id, version, f"sha256:{expected}", dest_root)

        on_progress(0, "Copiando assets")
        _copy_file(src_payload, dest_payload, on_progress)
        sidecar = src_root / "checksum" if src_root.is_dir() else None
        if sidecar is not None and sidecar.is_file():
            shutil.copy2(sidecar, dest_root / "checksum")

        got = _digest_of(dest_payload)
        if got != expected:
            dest_payload.unlink(missing_ok=True)
            raise PrepareError(
                "CHECKSUM_MISMATCH",
                f"checksum sha256:{got} != sha256:{expected}",
            )
        on_progress(100, "Verificado")
        log.info(
            "prepare cacheHit=false game=%s version=%s checksum=sha256:%s",
            game_id,
            version,
            expected,
        )
        return PrepareOutcome(False, game_id, version, f"sha256:{expected}", dest_root)
