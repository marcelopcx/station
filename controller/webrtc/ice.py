"""Candidatos ICE.

`RTCPeerConnection()` se crea sin `iceServers`: solo `typ host`.

aioice (`get_host_addresses`) enumera NICs reales y omite loopback.
Sin `127.0.0.1`, un browser en `http://localhost` no alcanza el peer
(`iceConnectionState=failed` con signaling OK). `enable_loopback_hosts`
antepone `127.0.0.1` / `::1`. Idempotente.

Chrome publica mDNS (`*.local`) en vez de la IP. Este proceso no resuelve
`.local`; esas líneas se descartan. El SDP del OFFER ya trae host candidates.
"""

from __future__ import annotations

from typing import Any, Optional

import aioice.ice
from aiortc import RTCIceCandidate
from aiortc.sdp import candidate_from_sdp

_original_host_addresses = aioice.ice.get_host_addresses
_loopback_patched = False


def _host_addresses_with_loopback(use_ipv4: bool, use_ipv6: bool) -> list[str]:
    addresses = _original_host_addresses(use_ipv4, use_ipv6)
    if use_ipv4 and "127.0.0.1" not in addresses:
        addresses.insert(0, "127.0.0.1")
    if use_ipv6 and "::1" not in addresses:
        addresses.insert(0, "::1")
    return addresses


def enable_loopback_hosts() -> None:
    """Monkeypatch de `aioice.ice.get_host_addresses`. Una vez por proceso."""
    global _loopback_patched
    if _loopback_patched:
        return
    aioice.ice.get_host_addresses = _host_addresses_with_loopback
    _loopback_patched = True


def candidate_from_message(msg: dict[str, Any]) -> Optional[RTCIceCandidate]:
    """JSON inbound → `RTCIceCandidate`. `None` si vacío, mDNS o parse error."""
    raw = msg.get("candidate")
    if not raw:
        return None
    line = raw[10:] if raw.startswith("candidate:") else raw
    if ".local" in line:
        return None
    try:
        cand = candidate_from_sdp(line)
    except Exception:
        return None
    cand.sdpMid = msg.get("sdpMid")
    cand.sdpMLineIndex = msg.get("sdpMLineIndex")
    return cand


def candidate_to_message(candidate: RTCIceCandidate) -> dict[str, Any]:
    return {
        "type": "ICE",
        "candidate": f"candidate:{candidate.to_sdp()}",
        "sdpMid": candidate.sdpMid,
        "sdpMLineIndex": candidate.sdpMLineIndex,
    }
