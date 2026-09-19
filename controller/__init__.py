"""Runtime genérico de una Game Station.

Un proceso = un contenedor = una partida. El título lo define el
`manifest.yaml` de la imagen (`/opt/game/manifest.yaml`), no este paquete.

Módulos (un rol cada uno; no importar al revés del grafo):

    api        FastAPI: CORS y rutas. Cero FSM, cero aiortc.
    contract   JSON del wire (models, states, errors).
    session    FSM prepare/launch/stop + Hub. No importa aiortc.
    catalog    Un manifiesto por imagen.
    prepare    /library → /cache + checksum.
    runtime    Xvfb, Pulse, proceso del juego (desde el manifiesto).
    input      Gamepad virtual uinput.
    webrtc     Peer, signaling, captura. No lee StationState.
    config     Variables de entorno. El loader futuro las setea por contenedor.
"""
