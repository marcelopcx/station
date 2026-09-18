# Game Station — primer corte, fase S1

Proceso del contenedor **GAME STATION**. Hoy (S1): FSM de sesión y un
`RTCPeerConnection` que publica barras SMPTE. No es el MVP (S2+S3: juego +
input remoto) ni G1 (Spring delante).

El contrato REST/WS de este proceso es el que S2+S3, S4, S5 y el Dispatcher
reutilizan. No versionar el JSON “para el prototipo”.

No sirve HTML. Cliente previsto: `game-client/`, Vite `:5173`.

Roadmap: [`../docs/guia-mvp-prototipo.md`](../docs/guia-mvp-prototipo.md).
Arquitectura de **este** código: [`../docs/architecture.md`](../docs/architecture.md).

## Qué hay en el paquete vs. qué entra después

```
station/controller/
├── app.py / machine.py / hub.py / … S0+S1 (verbos y estados se quedan)
└── webrtc/
    ├── signaling.py  ice.py         se conservan en S2+S3 / G1
    ├── session.py                   un peer; S2+S3 no reescribe el WS
    └── media.py                     S1 = smptebars; S2+S3 añade captura
```

| Siguiente fase | Cambio en `game-station/` |
| --- | --- |
| **S2+S3** | Parsear DC `input` (pad); `runtime.py` + captura; uinput. Guía: [`../docs/guia-s2-s3-juego-e-input.md`](../docs/guia-s2-s3-juego-e-input.md) |
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
│       ├── media.py      SmpteBarsSource (lavfi) — se reemplaza/amplía en S2+S3
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
Ese corte es el que permite cambiar la fuente en S2+S3 sin tocar la FSM.

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
ICE publique IPs reales. El RTP de WebRTC es **UDP**: no viaja por el
túnel SSH. Por eso `localhost:5173` por `-L` puede mostrar `ontrack` y luego
`ice failed`.

En el Spark, `game-station/` y `game-client/` son carpetas hermanas.

### Internet (redes distintas, IP pública)

El Spark anuncia solo la IP pública (`ICE_HOST_POLICY=public`). Chrome
necesita HTTPS para WebRTC: nginx escucha **443** con un cert autofirmado.

En el Spark:

```bash
ip -4 addr
# IP pública del Spark, p. ej. 156.255.130.66

sudo ufw allow OpenSSH
sudo ufw allow 443/tcp
sudo ufw allow 5173/tcp
sudo ufw allow 10000:65535/udp
sudo ufw --force enable
sudo ufw status

cd ~/airtek-cloud-game/game-station
git pull
cd ../game-client && git pull && cd ../game-station

export ICE_HOST_IPS=156.255.130.66
export PUBLIC_HOST=156.255.130.66
docker compose -f compose.spark.yaml up --build -d
docker compose -f compose.spark.yaml logs -f --tail=80
```

En los logs de `game-station` tiene que aparecer
`ice hosts ... ipv4=['156.255.130.66']` (sin `10.212` ni `172.x`).

En la laptop (cerrá el túnel `-L`):

1. Abrí `https://156.255.130.66`
2. Aceptá el certificado autofirmado (Avanzado → continuar)
3. Play

No uses `http://156.255.130.66:5173` en Chrome: no es secure context.

`:5173` HTTP queda para el túnel SSH. No abras `:8090` a internet; el
signaling va por `/station` en nginx.

### LAN / VPN

Misma red o VPN del Spark (`10.212.x.x`). El compose con
`ICE_HOST_POLICY=public` **no** anuncia esa IP privada. Para LAN:

```bash
ICE_HOST_POLICY=all ICE_HOST_IPS= \
  docker compose -f compose.spark.yaml up --build -d
```

```bash
sudo ufw allow proto udp from 192.168.0.0/16
sudo ufw allow proto udp from 10.0.0.0/8
```

Chrome en `http://<IP>:5173`: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`.

Variables:

```
STATION_ID=spark-1
CORS_ORIGIN_REGEX=https?://.*
ICE_INCLUDE_LOOPBACK=0
ICE_HOST_POLICY=public
ICE_HOST_IPS=156.255.130.66
ICE_SERVERS=stun:stun.l.google.com:19302
PUBLIC_HOST=156.255.130.66
```

## Tests

```bash
cd game-station
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Cubren transiciones de FSM y parseo de signaling. El bitstream se verifica
en el frontend (`http://localhost:5173`) cuando exista.
