"""H.264 60 fps y bitrate alto. NVENC si el GPU está; si no, libx264 zerolatency.

aiortc trae VP8 a 500 kb/s y H.264 a 30 fps / 1 Mb/s. Eso es el lag y la
nieve, no el Grace Blackwell.
"""

from __future__ import annotations

import logging
import os
from fractions import Fraction

import av
from av.video.codeccontext import VideoCodecContext

log = logging.getLogger("game-station.webrtc.encode")

_codec_name = "h264"
_patched = False
_prefer_h264 = True


def video_fps() -> int:
    raw = os.environ.get("STATION_FPS", "60").strip() or "60"
    try:
        fps = int(raw)
    except ValueError:
        fps = 60
    return max(30, min(120, fps))


def video_bitrate() -> int:
    raw = os.environ.get("STATION_VIDEO_BITRATE", "8000000").strip() or "8000000"
    try:
        bps = int(raw)
    except ValueError:
        bps = 8_000_000
    return max(2_000_000, min(20_000_000, bps))


def codec_name() -> str:
    return _codec_name


def prefer_h264() -> bool:
    return _prefer_h264


def apply() -> None:
    """Una vez por proceso. Sube caps de aiortc y sustituye el encoder H.264."""
    global _patched, _prefer_h264
    if _patched:
        return
    fps = video_fps()
    bitrate = video_bitrate()
    try:
        from aiortc.codecs import h264, vpx
    except ImportError:
        log.warning("aiortc codecs no disponibles")
        return
    _patched = True

    vpx.DEFAULT_BITRATE = bitrate
    vpx.MIN_BITRATE = max(1_000_000, bitrate // 4)
    vpx.MAX_BITRATE = max(12_000_000, bitrate)
    vpx.MAX_FRAME_RATE = fps

    h264.DEFAULT_BITRATE = bitrate
    h264.MIN_BITRATE = max(1_000_000, bitrate // 4)
    h264.MAX_BITRATE = max(16_000_000, bitrate)
    h264.MAX_FRAME_RATE = fps

    _patch_h264_encoder(h264, fps, bitrate)
    try:
        av.CodecContext.create("libx264", "w")
        _prefer_h264 = True
    except Exception:
        _prefer_h264 = False
        log.warning("libx264 ausente; se negocia VP8 a %s bps", bitrate)
    log.info(
        "webrtc encode ready prefer=%s fps=%s bitrate=%s",
        "h264" if _prefer_h264 else "vp8",
        fps,
        bitrate,
    )


def _patch_h264_encoder(h264, fps: int, bitrate: int) -> None:
    def _encode_frame(self, frame, force_keyframe: bool):  # type: ignore[no-untyped-def]
        global _codec_name
        kind = getattr(self, "_airtek_kind", None)
        if self.codec is not None and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            or abs(self.target_bitrate - self.codec.bit_rate) / max(self.codec.bit_rate, 1)
            > 0.1
        ):
            self.codec = None
            kind = None

        created = False
        if self.codec is None:
            self.codec, kind = _open_h264(
                frame.width, frame.height, self.target_bitrate, fps
            )
            self._airtek_kind = kind
            _codec_name = kind
            created = True
            log.info(
                "encoder=%s %sx%s@%s bitrate=%s",
                kind,
                frame.width,
                frame.height,
                fps,
                self.target_bitrate,
            )

        if force_keyframe or created:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        try:
            packets = list(self.codec.encode(frame))
        except Exception as exc:
            if kind == "h264_nvenc":
                log.warning("h264_nvenc encode failed (%s); fallback libx264", exc)
                self.codec = _make_libx264(
                    frame.width, frame.height, self.target_bitrate, fps
                )
                kind = "libx264"
                self._airtek_kind = kind
                _codec_name = kind
                packets = list(self.codec.encode(frame))
            else:
                raise

        data = b"".join(bytes(pkg) for pkg in packets)
        if data:
            yield from h264.H264Encoder._split_bitstream(data)

    h264.H264Encoder._encode_frame = _encode_frame  # type: ignore[method-assign]


def _open_h264(
    width: int, height: int, bitrate: int, fps: int
) -> tuple[VideoCodecContext, str]:
    forced = os.environ.get("STATION_ENCODER", "").strip().lower()
    if forced in ("x264", "libx264"):
        return _make_libx264(width, height, bitrate, fps), "libx264"
    if forced not in ("vp8", "x264", "libx264"):
        try:
            ctx = _make_nvenc(width, height, bitrate, fps)
            return ctx, "h264_nvenc"
        except Exception as exc:
            log.warning("h264_nvenc no arrancó: %s", exc)
    return _make_libx264(width, height, bitrate, fps), "libx264"


def _make_nvenc(width: int, height: int, bitrate: int, fps: int) -> VideoCodecContext:
    ctx = av.CodecContext.create("h264_nvenc", "w")
    _fill_ctx(ctx, width, height, bitrate, fps)
    ctx.profile = "Baseline"
    ctx.gop_size = fps
    ctx.options = {
        "preset": "p1",
        "tune": "ull",
        "rc": "cbr",
        "delay": "0",
        "zerolatency": "1",
        "bf": "0",
        "repeat-headers": "1",
    }
    return ctx


def _make_libx264(width: int, height: int, bitrate: int, fps: int) -> VideoCodecContext:
    ctx = av.CodecContext.create("libx264", "w")
    _fill_ctx(ctx, width, height, bitrate, fps)
    ctx.profile = "Baseline"
    ctx.gop_size = fps
    ctx.options = {
        "preset": "ultrafast",
        "tune": "zerolatency",
        "level": "40",
        "bf": "0",
        "g": str(fps),
        "keyint_min": str(fps),
        "scenecut": "0",
        "repeat-headers": "1",
    }
    return ctx


def _fill_ctx(
    ctx: VideoCodecContext, width: int, height: int, bitrate: int, fps: int
) -> None:
    ctx.width = width
    ctx.height = height
    ctx.bit_rate = bitrate
    ctx.pix_fmt = "yuv420p"
    ctx.framerate = Fraction(fps, 1)
    ctx.time_base = Fraction(1, fps)
    ctx.max_b_frames = 0
