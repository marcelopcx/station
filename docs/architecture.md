# Arquitectura del runtime

Un proceso uvicorn. Expone REST + dos WebSockets. No sirve HTML. El juego
**no** está en este paquete: entra por `/opt/game/manifest.yaml` en la
imagen hija.

```
controller/
├── api/            composición FastAPI; cero transiciones
├── contract/       Pydantic + StrEnum + StationError
├── session/        Station + Hub
├── catalog/        un GameManifest
├── prepare/        library → cache
├── runtime/        display / audio / process / supervisor
├── input/          uinput pads + XTEST teclado/ratón
├── webrtc/         session, media, signaling, ice
└── config.py       Settings.from_env()
```

Grafo de imports:

```
api ──► session ──► catalog, prepare, contract
  └──► webrtc ──► runtime, input
runtime ──► catalog, config
session no importa aiortc
runtime no compara game_id con un string de título
```

## FSM

```
IDLE ──POST /prepare──► PREPARING ──► READY ──POST /launch──► PLAYING
  ▲                                                                  │
  └──────────────────────── POST /stop ──────────────────────────────┘
```

`gameId` de prepare/launch tiene que coincidir con `manifest.id`. Si no:
`400 UNKNOWN_GAME`.

## Planos

```
Browser
  │
  ├─ REST / WS control, signaling  →  esta API :8090
  │     (en G1 el Dispatcher reenvía estos mismos JSON)
  └─ RTP/SRTP WebRTC               →  ICE directo, no pasa por Spring ni nginx
```

El nginx de `game-client` es TLS del SPA + **un** upstream. No rutea N
estaciones: eso es el Dispatcher.
