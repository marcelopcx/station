# Cómo agregar un juego

El runtime no se toca. Un título nuevo es una carpeta en `games/` (raíz
del checkout `airtek_cloud_game`).

## 1. Carpeta

```
games/mi-juego/
  Dockerfile
  manifest.yaml
  install.sh     # opcional
```

## 2. `manifest.yaml`

```yaml
id: mi-juego
version: "1.0.0"
kind: native
command: ["/opt/mi-juego/bin"]
args:
  - "--width=${WIDTH}"
  - "--height=${HEIGHT}"
env:
  SDL_VIDEODRIVER: x11
  SDL_AUDIODRIVER: pulse
needs:
  display: true
  audio: true
  gamepad: true
audio:
  fallbackArgs: []
```

Placeholders: `${WIDTH}` `${HEIGHT}` `${SIZE}` `${CACHE}` `${LIBRARY}` `${DISPLAY}`.

`kind: test-pattern` no lanza proceso (fuente SMPTE). No lo uses para
títulos reales.

## 3. `Dockerfile`

```dockerfile
ARG RUNTIME_IMAGE=airtek/game-station-runtime:latest
FROM ${RUNTIME_IMAGE}
# instalá el binario
COPY manifest.yaml /opt/game/manifest.yaml
RUN station-seed-library mi-juego 1.0.0
LABEL org.airtek.role=game-station
LABEL org.airtek.game.id=mi-juego
```

`station-seed-library` deja un payload dummy para que `POST /prepare`
siga funcionando (el binario real está en la imagen).

## 4. Build

```bash
./scripts/build-station.sh mi-juego   # hay que agregar el nombre al script
GAME=mi-juego docker compose -f compose.spark.yaml up --build
```

El cliente usa `VITE_GAME_ID` = el `id` del manifiesto.

Ejemplos vivos: `games/supertuxkart`, `games/wesnoth`, `games/xonotic`.
