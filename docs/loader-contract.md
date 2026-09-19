# Contrato para el Game Loader (futuro)

Este runtime **no** crea contenedores. El loader (proceso aparte) hace
`docker create/start` de N estaciones. El Dispatcher (Spring) rutea la
sesión HTTP/WS. El video WebRTC no pasa por ninguno de los dos.

## Qué hace cada uno

| Pieza | Responsabilidad |
|-------|-----------------|
| Loader | Elige imagen (`org.airtek.game.id`), crea el contenedor, setea env, `docker start/stop` |
| Dispatcher | `prepare` / `launch` / `stop` y reenvío de signaling a la estación asignada |
| Station | Una partida. API `:8090`. `POST /stop` no equivale a `docker stop` |

## Env por contenedor (host network)

| Variable | Default | Obligatorio si N>1 en host net |
|----------|---------|--------------------------------|
| `STATION_ID` | `spark-1` | sí (único) |
| `STATION_HTTP_PORT` | `8090` | sí (único) |
| `STATION_DISPLAY` | `:99` | sí (único, Xvfb) |
| `STATION_PULSE_SOCK` | `/tmp/pulse/native` | sí si comparten `/tmp` |
| `ICE_HOST_IPS` | — | IP anunciada en ICE |
| `GAME_MANIFEST` | `/opt/game/manifest.yaml` | no (va en la imagen) |

En red bridge los defaults bastan: cada contenedor tiene su namespace.

## Labels de la imagen

```
org.airtek.role=game-station
org.airtek.game.id=<id del manifiesto>
```

El loader inspecciona el label para no lanzar Wesnoth en una imagen STK.

## Ciclo

1. Loader: `docker run` de `airtek/game-station-<gameId>` con env únicas.
2. Dispatcher: espera `/health` `status=UP`, `state=IDLE`.
3. Dispatcher: `POST /prepare` → `POST /launch` (mismo `gameId` que el label).
4. Browser: signaling vía Dispatcher (G1); RTP directo a la estación.
5. Fin: Dispatcher `POST /stop`. El contenedor queda Up, `IDLE`.
6. Reciclar máquina: `docker stop` (loader), no `/stop`.
