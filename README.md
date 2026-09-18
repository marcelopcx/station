# Game Station — primer corte, fase S1

Proceso del contenedor **GAME STATION**. Hoy (S1): FSM de sesión y un
`RTCPeerConnection` que publica barras SMPTE. No es el MVP (S3: juego +
NVENC) ni G1 (Spring delante).

El contrato REST/WS de este proceso es el que S2–S5 y el Dispatcher
reutilizan. No versionar el JSON “para el prototipo”.

No sirve HTML. Cliente previsto: `apps/web`, Vite `:5173`.

Roadmap: [`../docs/guia-mvp-prototipo.md`](../docs/guia-mvp-prototipo.md).
Arquitectura de **este** código: [`../docs/architecture.md`](../docs/architecture.md).

## Qué hay en el paquete vs. qué entra después

```
station/controller/
├── app.py / machine.py / hub.py / … S0+S1 (verbos y estados se quedan)
└── webrtc/
    ├── signaling.py  ice.py         se conservan en S3/G1
    ├── session.py                   un peer; S3 no reescribe el WS
    └── media.py                     S1 = smptebars; S3 sustituye esta clase
```

| Siguiente fase | Cambio en `station/` |
| --- | --- |
| S2 | Parsear DataChannel `input` (8 bytes); overlay sobre el patrón |
| S3 | `SmpteBarsSource` → captura de display + NVENC; uinput |
| S4 | `prepare` deja de ser un sleep: `/library` → `/cache` |
| S5 | encoder en `/health`, timeout de inactividad |
| G1 | nada aquí: Spring es **cliente** de `:8090` |

## Layout S1

```
station/
├── controller/           uvicorn: controller.app:app
│   ├── app.py            composición FastAPI, CORS, rutas
│   ├── machine.py        máquina de estados; no importa aiortc
│   ├── hub.py            fan-out de /ws/control
│   ├── states.py         IDLE | PREPARING | READY | PLAYING
│   ├── errors.py         STATION_BUSY, GAME_NOT_READY, … → HTTP
│   ├── models.py         bodies Pydantic (camelCase del wire)
│   └── webrtc/
│       ├── session.py    un RTCPeerConnection
│       ├── media.py      SmpteBarsSource (lavfi) — se reemplaza en S3
│       ├── signaling.py  OFFER / ANSWER / ICE / ERROR
│       └── ice.py        candidatos + loopback en aioice
├── tests/                FSM con FakeStream (sin FFmpeg)
├── Dockerfile
├── compose.yaml
└── requirements.txt
```

```
app.py ──► Station (machine.py) ──► Hub
        │                   └──► MediaSession (Protocol)
        └──► WebrtcSession ──► media / signaling / ice
```

`Station` no importa `aiortc`. `WebrtcSession` no conoce los estados de la FSM.
Ese corte es el que permite cambiar la fuente en S3 sin tocar la FSM.

## Arranque

Local, sin Docker:

```bash
cd game-station
source .venv/bin/activate
uvicorn controller.app:app --host 127.0.0.1 --port 8090
```

Docker en el Mac (solo estación):

```bash
cd game-station
docker compose up --build
```

S1 no usa NVENC: no hace falta `--gpus`.

## Spark (S1)

La estación y el cliente viven en contenedores con **host network** para que
ICE publique las IPs de la LAN. El RTP de WebRTC es **UDP**: no viaja por el
túnel SSH. Por eso `localhost:5173` por `-L` puede mostrar `ontrack` y luego
`ice failed`.

### LAN (sin túnel)

Laptop y Spark en la **misma Wi‑Fi/Ethernet**. En el Spark:

```bash
ip -4 addr
# usá la IP privada (192.168.x.x / 10.x.x.x), no una pública tipo 156.x

sudo ufw allow 5173/tcp
sudo ufw allow 8090/tcp
sudo ufw allow proto udp from 192.168.0.0/16
sudo ufw allow proto udp from 10.0.0.0/8
```

Rebuild y abrí **en el browser** `http://<IP-LAN>:5173` (cerrá el `-L`).

Chrome bloquea WebRTC en `http://IP`. En Chrome:

1. `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
2. Agregá `http://<IP-LAN>:5173`
3. Relaunch

Firefox suele dejar el `RTCPeerConnection` en HTTP de LAN.

En el Spark, con `game-station/` y `game-client/` como carpetas hermanas:

```bash
cd game-station
docker compose -f compose.spark.yaml up --build
curl -s http://127.0.0.1:8090/health
```

Variables:

```
STATION_ID=spark-1
CORS_ORIGIN_REGEX=https?://.*
ICE_INCLUDE_LOOPBACK=0
ICE_SERVERS=stun:stun.l.google.com:19302
```

## Tests

```bash
cd game-station
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Cubren transiciones de FSM y parseo de signaling. El bitstream se verifica
en el frontend (`http://localhost:5173`) cuando exista.
