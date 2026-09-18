"""Controller de la Game Station.

Orquesta `prepare` / `launch` / `stop`. En `PLAYING` publica un
`VideoStreamTrack` por un `RTCPeerConnection`.

    app.py       FastAPI: rutas HTTP y WebSocket
    machine.py   máquina de estados
    hub.py       fan-out de `/ws/control`
    webrtc/      SDP, ICE, fuente de video, peer
"""
