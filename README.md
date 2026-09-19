# Game Station — runtime genérico

Contenedor **GAME STATION**: API FastAPI `:8090`, display virtual, Pulse, pad
uinput y WebRTC. **No incluye el juego.**

El título vive en otra imagen (`games/<id>/` en la raíz del checkout),
`FROM airtek/game-station-runtime`. Un contenedor = una partida. `POST /stop`
mata la partida, no el contenedor.

El **Game Loader** (aún no está) creará N copias de estas imágenes. El
**Game Dispatcher** (Spring, G1) rutea la sesión. Este proceso se diseña
como si ya los llamara: mismo REST/WS.

Contrato HTTP: [`../docs/guia-mvp-backend.md`](../docs/guia-mvp-backend.md)
(gana si hay conflicto de JSON).

## Árbol

```
controller/
  api/         FastAPI. Cero FSM.
  contract/    models, states, errors (wire JSON)
  session/     Station + Hub. No importa aiortc.
  catalog/     un manifest.yaml por imagen
  prepare/     /library → /cache
  runtime/     Xvfb, Pulse `game`, proceso (desde el manifiesto)
  input/       uinput pad
  webrtc/      peer, captura, signaling, ICE
  config.py    env que el loader setea por contenedor
docker/
  Dockerfile
  entrypoint.sh
  seed-library.sh
  pulse/
  openal/
```

## Arranque local (sin juego)

```bash
cd game-station
source .venv/bin/activate
pip install -r requirements.txt
uvicorn controller.api.app:app --host 127.0.0.1 --port 8090
```

Sin `/opt/game/manifest.yaml` la API sube; `prepare`/`launch` de un título
fallan hasta usar una imagen de `games/`.

## Imagen + juego (desde la raíz del checkout)

```bash
./scripts/build-station.sh supertuxkart   # o wesnoth | xonotic
GAME=supertuxkart docker compose -f compose.spark.yaml up --build
```

Documentación:

| Doc | Rol |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Módulos y grafo |
| [docs/adding-a-game.md](docs/adding-a-game.md) | Cómo agregar un título |
| [docs/loader-contract.md](docs/loader-contract.md) | Qué hará el loader con N contenedores |
