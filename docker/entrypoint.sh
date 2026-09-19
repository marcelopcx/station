#!/bin/sh
# Puerto HTTP desde STATION_HTTP_PORT (N estaciones en host network).
set -eu
PORT="${STATION_HTTP_PORT:-8090}"
exec python3 -m uvicorn controller.api.app:app --host 0.0.0.0 --port "$PORT"
