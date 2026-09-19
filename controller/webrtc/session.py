"""Un `RTCPeerConnection` y una fuente de video/audio.

- `start_source` / `stop`: ciclo de vida de runtime + pad + fuente.
- `attach`: un peer a la vez; loop OFFER → setRemote + createAnswer; ICE trickle.

Sin fuente: `NOT_PLAYING`. Si `_pc` ya existe: `PEER_BUSY`.
No lee `StationState`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from fastapi import WebSocket, WebSocketDisconnect

from controller.input import InputSink
from controller.runtime import GameRuntime
from controller.webrtc.ice import (
    candidate_from_message,
    candidate_to_message,
    rtc_configuration,
)
from controller.webrtc.media import VideoSource, make_source
from controller.webrtc.signaling import (
    ERROR_NOT_PLAYING,
    ERROR_PEER_BUSY,
    Ice,
    Offer,
    dumps_answer,
    dumps_error,
    dumps_ice,
    parse_client_message,
)

log = logging.getLogger("game-station.webrtc")


def _prefer_vp8(pc: RTCPeerConnection) -> None:
    vp8 = [
        codec
        for codec in RTCRtpSender.getCapabilities("video").codecs
        if codec.mimeType.lower() == "video/vp8"
    ]
    if not vp8:
        return
    for transceiver in pc.getTransceivers():
        sender = transceiver.sender
        if sender and sender.track and sender.track.kind == "video":
            transceiver.setCodecPreferences(vp8)


def _prefer_opus(pc: RTCPeerConnection) -> None:
    opus = [
        codec
        for codec in RTCRtpSender.getCapabilities("audio").codecs
        if codec.mimeType.lower() == "audio/opus"
    ]
    if not opus:
        return
    for transceiver in pc.getTransceivers():
        sender = transceiver.sender
        if sender and sender.track and sender.track.kind == "audio":
            transceiver.setCodecPreferences(opus)


class WebrtcSession:
    def __init__(
        self,
        source: Optional[VideoSource] = None,
        runtime: Optional[GameRuntime] = None,
        input_sink: Optional[InputSink] = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._source: VideoSource = source or make_source(
            capture_display=False, display=":99"
        )
        self._runtime = runtime or GameRuntime()
        self._input = input_sink or InputSink()
        self._pc: Optional[RTCPeerConnection] = None
        self._ws: Optional[WebSocket] = None

    def playing_source(self) -> bool:
        return self._source.is_running()

    def encoder_name(self) -> Optional[str]:
        return "vp8" if self.playing_source() else None

    def last_input_monotonic(self) -> Optional[float]:
        return self._input.last_input_monotonic

    async def start_source(self, game_id: str) -> None:
        self._source.stop()
        log.info("start_source game=%s encoder=vp8,opus", game_id)
        manifest = self._runtime.manifest_for(game_id)
        needs = manifest.needs
        log.info(
            "input needs pads=%s keyboard=%s mouse=%s",
            needs.gamepad,
            needs.keyboard,
            needs.mouse,
        )
        self._input.open(
            pads=needs.gamepad,
            keyboard=needs.keyboard,
            mouse=needs.mouse,
            display=self._runtime.display,
            width=int(self._runtime.settings.width),
            height=int(self._runtime.settings.height),
        )
        await self._runtime.start(game_id)
        self._source = make_source(
            capture_display=self._runtime.captures_display,
            display=self._runtime.display,
            draw_mouse=needs.mouse,
        )
        self._source.start()

    async def stop(self) -> None:
        async with self._lock:
            pc = self._pc
            ws = self._ws
            self._pc = None
            self._ws = None
        if pc:
            await pc.close()
        self._source.stop()
        await self._runtime.stop()
        self._input.close()
        if ws:
            try:
                await ws.close()
            except Exception:
                pass

    async def attach(self, ws: WebSocket) -> None:
        """WebSocket ya aceptado. Bloquea en el loop de signaling hasta close o `stop()`."""
        pc = await self._try_take_peer(ws)
        if pc is None:
            return
        self._bind_peer_events(pc)
        await self._signaling_loop(pc, ws)

    async def _try_take_peer(self, ws: WebSocket) -> Optional[RTCPeerConnection]:
        async with self._lock:
            if not self._source.is_running():
                await ws.send_text(dumps_error(ERROR_NOT_PLAYING))
                await ws.close()
                return None
            if self._pc is not None:
                await ws.send_text(dumps_error(ERROR_PEER_BUSY))
                await ws.close()
                return None
            pc = RTCPeerConnection(configuration=rtc_configuration())
            self._pc = pc
            self._ws = ws
            return pc

    def _bind_peer_events(self, pc: RTCPeerConnection) -> None:
        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            log.info("connectionstate=%s", pc.connectionState)

        @pc.on("datachannel")
        def on_datachannel(channel) -> None:
            log.info("datachannel=%s", channel.label)
            if channel.label != "input":
                return

            @channel.on("message")
            def on_message(message) -> None:
                if not isinstance(message, (bytes, bytearray, memoryview)):
                    return
                self._input.handle(bytes(message))

        @pc.on("icecandidate")
        async def on_icecandidate(candidate: Optional[RTCIceCandidate]) -> None:
            if candidate is None or self._ws is None:
                return
            try:
                await self._ws.send_text(dumps_ice(candidate_to_message(candidate)))
            except Exception:
                pass

    async def _signaling_loop(self, pc: RTCPeerConnection, ws: WebSocket) -> None:
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("signaling: JSON inválido")
                    continue
                if not isinstance(msg, dict):
                    continue
                await self._handle(pc, ws, msg)
        except WebSocketDisconnect:
            pass
        finally:
            await self._release_peer(pc)

    async def _handle(self, pc: RTCPeerConnection, ws: WebSocket, msg: dict) -> None:
        parsed = parse_client_message(msg)
        if isinstance(parsed, Offer):
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=parsed.sdp, type="offer")
            )
            self._attach_tracks(pc)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await ws.send_text(dumps_answer(pc.localDescription.sdp))
            return
        if isinstance(parsed, Ice):
            cand = candidate_from_message(parsed.raw)
            if cand is None:
                return
            try:
                await pc.addIceCandidate(cand)
            except Exception:
                log.warning("ICE candidate rejected")

    def _attach_tracks(self, pc: RTCPeerConnection) -> None:
        video = self._source.subscribe_video()
        if video is not None:
            pc.addTrack(video)
        audio = self._source.subscribe_audio()
        if audio is not None:
            pc.addTrack(audio)
            log.info("webrtc audio track=opus encoder=vp8,opus")
        else:
            log.info("webrtc audio track=none encoder=vp8")
        _prefer_vp8(pc)
        _prefer_opus(pc)

    async def _release_peer(self, pc: RTCPeerConnection) -> None:
        async with self._lock:
            if self._pc is pc:
                self._pc = None
                self._ws = None
        await pc.close()
