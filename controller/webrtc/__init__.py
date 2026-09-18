"""WebRTC: fuente de video, signaling JSON y un `RTCPeerConnection`.

    media.py        lavfi smptebars → MediaPlayer → VideoStreamTrack
    signaling.py    OFFER / ANSWER / ICE / ERROR
    ice.py          RTCIceCandidate ↔ JSON; loopback en aioice
    session.py      un peer; junta las tres
"""

from controller.webrtc.ice import configure_ice_hosts, enable_loopback_hosts
from controller.webrtc.session import WebrtcSession

__all__ = ["WebrtcSession", "configure_ice_hosts", "enable_loopback_hosts"]
