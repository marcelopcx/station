"""WebRTC: fuente, signaling JSON y un `RTCPeerConnection`.

Importar submódulos (`ice`, `signaling`, `session`) para no arrastrar aiortc
cuando solo se parsea JSON.
"""

from controller.webrtc.ice import configure_ice_hosts, enable_loopback_hosts

__all__ = ["WebrtcSession", "configure_ice_hosts", "enable_loopback_hosts"]


def __getattr__(name: str):
    if name == "WebrtcSession":
        from controller.webrtc.session import WebrtcSession

        return WebrtcSession
    raise AttributeError(name)
