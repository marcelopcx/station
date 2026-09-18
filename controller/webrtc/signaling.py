"""JSON de `/ws/webrtc`.

El socket lleva SDP e ICE trickle. RTP/SRTP va por UDP tras ICE.

El browser es offerer. La estación responde `ANSWER` y trickle `ICE`.

    inbound     { type: OFFER, sdp }
                { type: ICE, candidate, sdpMid, sdpMLineIndex }
    outbound    { type: ANSWER, sdp }
                { type: ICE, candidate, sdpMid, sdpMLineIndex }
                { type: ERROR, code }   # NOT_PLAYING | PEER_BUSY

`parse_client_message` ignora tipos desconocidos y OFFER con `sdp` vacío.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Union

TYPE_OFFER = "OFFER"
TYPE_ANSWER = "ANSWER"
TYPE_ICE = "ICE"
TYPE_ERROR = "ERROR"

ERROR_NOT_PLAYING = "NOT_PLAYING"
ERROR_PEER_BUSY = "PEER_BUSY"


@dataclass(frozen=True)
class Offer:
    sdp: str


@dataclass(frozen=True)
class Ice:
    raw: dict[str, Any]


ClientMessage = Union[Offer, Ice]


def parse_client_message(msg: dict[str, Any]) -> Optional[ClientMessage]:
    typ = msg.get("type")
    if typ == TYPE_OFFER:
        sdp = msg.get("sdp")
        if not isinstance(sdp, str) or not sdp:
            return None
        return Offer(sdp=sdp)
    if typ == TYPE_ICE:
        return Ice(raw=msg)
    return None


def dumps_answer(sdp: str) -> str:
    return json.dumps({"type": TYPE_ANSWER, "sdp": sdp})


def dumps_error(code: str) -> str:
    return json.dumps({"type": TYPE_ERROR, "code": code})


def dumps_ice(payload: dict[str, Any]) -> str:
    return json.dumps(payload)
