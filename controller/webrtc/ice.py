"""Candidatos ICE.

`RTCPeerConnection` usa `ICE_SERVERS` (STUN, separados por coma). Vacío =
solo `typ host`.

aioice (`get_host_addresses`) enumera NICs reales y omite loopback.
`enable_loopback_hosts` antepone `127.0.0.1` / `::1` para demos en
localhost. En el Spark (LAN) no lo actives: el browser remoto no puede
usar el loopback de la estación.

Chrome publica mDNS (`*.local`) en vez de la IP. Este proceso no resuelve
`.local`; esas líneas se descartan. El SDP del OFFER ya trae host candidates.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import aioice.ice
from aiortc import RTCConfiguration, RTCIceCandidate, RTCIceServer
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


def rtc_configuration() -> RTCConfiguration:
    servers: list[RTCIceServer] = []
    raw = os.environ.get("ICE_SERVERS", "")
    for url in raw.split(","):
        url = url.strip()
        if url:
            servers.append(RTCIceServer(urls=url))
    return RTCConfiguration(iceServers=servers)


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
