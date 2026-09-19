#!/bin/sh
# Semilla dummy de /library/<gameId>/<version>/payload.bin para POST /prepare.
set -eu
GAME_ID="${1:?gameId}"
VERSION="${2:-1.0.0}"
ROOT="${LIBRARY_ROOT:-/opt/station-library}"
python3 - "$GAME_ID" "$VERSION" "$ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

game_id, version, root = sys.argv[1], sys.argv[2], sys.argv[3]
payload = b"\0" * (32 * 1024 * 1024)
digest = sha256(payload).hexdigest()
dest = Path(root) / game_id / version
dest.mkdir(parents=True, exist_ok=True)
(dest / "payload.bin").write_bytes(payload)
(dest / "checksum").write_text(f"sha256:{digest}\n")
print(f"library {game_id}/{version} sha256:{digest}")
PY
