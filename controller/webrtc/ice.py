"""Candidatos ICE.

`RTCPeerConnection` usa `ICE_SERVERS` (STUN, separados por coma). Vacío =
solo `typ host`.

aioice (`get_host_addresses`) enumera NICs reales y omite loopback.
`configure_ice_hosts` filtra esas IPs:

- `ICE_HOST_IPS` (coma): anuncia solo esas (p. ej. la IP pública del Spark).
- `ICE_HOST_POLICY=public`: descarta RFC1918, loopback y link-local.
- `ICE_INCLUDE_LOOPBACK=1`: antepone `127.0.0.1` / `::1` (demo localhost).

En internet hay que anunciar la IP pública. El browser remoto no puede
usar 10.x, 172.x de Docker ni el loopback de la estación.

Chrome publica mDNS (`*.local`) en vez de la IP. Este proceso no resuelve
`.local`; esas líneas se descartan. El SDP del OFFER ya trae host candidates.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any, Optional

import aioice.ice
from aiortc import RTCConfiguration, RTCIceCandidate, RTCIceServer
from aiortc.sdp import candidate_from_sdp

log = logging.getLogger("game-station.ice")

_original_host_addresses = aioice.ice.get_host_addresses
_hosts_patched = False


def _is_globally_routable(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _explicit_host_ips() -> list[str]:
    return [ip.strip() for ip in os.environ.get("ICE_HOST_IPS", "").split(",") if ip.strip()]


def _host_policy() -> str:
    return os.environ.get("ICE_HOST_POLICY", "all").strip().lower()


def _include_loopback() -> bool:
    return os.environ.get("ICE_INCLUDE_LOOPBACK", "1").lower() not in ("0", "false", "no")


def _select_host_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
    explicit = _explicit_host_ips()
    if explicit:
        out: list[str] = []
        for raw in explicit:
            try:
                parsed = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if use_ipv4 and parsed.version == 4:
                out.append(raw)
            elif use_ipv6 and parsed.version == 6:
                out.append(raw)
        return out

    addresses = list(_original_host_addresses(use_ipv4, use_ipv6))
    if _host_policy() == "public":
        addresses = [a for a in addresses if _is_globally_routable(a)]
    if _include_loopback():
        if use_ipv4 and "127.0.0.1" not in addresses:
            addresses.insert(0, "127.0.0.1")
        if use_ipv6 and "::1" not in addresses:
            addresses.insert(0, "::1")
    return addresses


def configure_ice_hosts() -> None:
    """Monkeypatch de `aioice.ice.get_host_addresses`. Una vez por proceso."""
    global _hosts_patched
    if _hosts_patched:
        return
    aioice.ice.get_host_addresses = _select_host_addresses
    _hosts_patched = True
    explicit = _explicit_host_ips()
    preview = _select_host_addresses(True, False)
    log.info(
        "ice hosts policy=%s explicit=%s loopback=%s ipv4=%s",
        "explicit" if explicit else _host_policy(),
        explicit or "-",
        _include_loopback(),
        preview,
    )


def enable_loopback_hosts() -> None:
    """Compat: llama `configure_ice_hosts` (el loopback sigue `ICE_INCLUDE_LOOPBACK`)."""
    configure_ice_hosts()


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
