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
ICE publique las IPs de la LAN. El RTP de WebRTC es UDP y no pasa por el
túnel SSH ni por `-p 8090:8090`.

En el Spark, con `game-station/` y `game-client/` como carpetas hermanas:

```bash
cd game-station
docker compose -f compose.spark.yaml up --build
curl -s http://127.0.0.1:8090/health
```

Desde la laptop, Chrome tiene que abrir **localhost** (HTTP en la IP LAN
bloquea WebRTC):

```bash
ssh -L 5173:127.0.0.1:5173 usuario@spark
```

Luego `http://localhost:5173`. El front habla con la estación por
`/station` (nginx en el mismo host). Laptop y Spark tienen que estar en la
misma LAN para que el UDP del peer llegue.

Variables:

```
STATION_ID=spark-1
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

## Tests

```bash
cd game-station
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Cubren transiciones de FSM y parseo de signaling. El bitstream se verifica
en el frontend (`http://localhost:5173`) cuando exista.
