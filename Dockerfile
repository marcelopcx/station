# Estación S2+S3 para el Spark (linux/arm64): Xvfb + SuperTuxKart 1.5 + VP8.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
        curl \
        ffmpeg \
        libopus0 \
        libvpx9 \
        libsrtp2-1 \
        xvfb \
        x11-utils \
        mesa-utils \
        libgl1 \
        libgl1-mesa-dri \
        libglu1-mesa \
        libx11-6 \
        libxrandr2 \
        libxi6 \
        libxxf86vm1 \
        libasound2t64 \
        libasound2-plugins \
        libopenal1 \
        libpulse0 \
        pulseaudio \
        pulseaudio-utils \
        vulkan-tools \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

# Binario + data oficiales (no el paquete apt 1.4). Spark = arm64.
ARG TARGETARCH=arm64
ARG STK_VERSION=1.5
COPY docker/install-stk.sh /tmp/install-stk.sh
RUN chmod +x /tmp/install-stk.sh \
    && TARGETARCH=${TARGETARCH} STK_VERSION=${STK_VERSION} /tmp/install-stk.sh \
    && rm /tmp/install-stk.sh

WORKDIR /app
COPY requirements.txt .
# evdev compila el C extension: hace falta gcc + linux/input.h (no el header del kernel host).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
        linux-libc-dev \
    && pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && apt-get purge -y gcc python3-dev \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*
COPY controller ./controller
COPY stk-home/ /root/.config/supertuxkart/
COPY docker/pulse/system.pa /etc/pulse/system.pa
COPY docker/pulse/daemon.conf /etc/pulse/daemon.conf
COPY docker/pulse/asound.conf /etc/asound.conf
COPY docker/pulse/stk.pa /etc/pulse/stk.pa
COPY docker/pulse/client.conf /etc/pulse/client.conf
COPY docker/openal/alsoft.conf /etc/openal/alsoft.conf
COPY docker/openal/alsoft.conf /root/.alsoftrc
RUN mkdir -p /tmp/pulse /var/run/pulse /cache \
        /opt/station-library/test-pattern/1.0.0 \
        /opt/station-library/supertuxkart/1.0.0 \
    && chmod 777 /tmp/pulse /cache \
    && python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

payload = b"\0" * (32 * 1024 * 1024)
digest = sha256(payload).hexdigest()
for game in ("test-pattern", "supertuxkart"):
    root = Path("/opt/station-library") / game / "1.0.0"
    (root / "payload.bin").write_bytes(payload)
    (root / "checksum").write_text(f"sha256:{digest}\n")
print("library dummy sha256:" + digest)
PY
ENV PYTHONUNBUFFERED=1
ENV HOME=/root
ENV XDG_CONFIG_HOME=/root/.config
ENV STATION_DISPLAY=:99
ENV STATION_SIZE=1280x720
ENV STK_BIN=/opt/stk/run_game.sh
ENV PULSE_SERVER=unix:/tmp/pulse/native
ENV PULSE_SINK=stk
ENV STATION_PULSE_SOURCE=stk.monitor
ENV SDL_AUDIODRIVER=pulse
ENV ALSOFT_DRIVERS=pulse
ENV ALSOFT_CONF=/etc/openal/alsoft.conf
ENV LIBRARY_ROOT=/opt/station-library
ENV CACHE_ROOT=/cache
ENV IDLE_TIMEOUT_S=300
EXPOSE 8090
CMD ["python3", "-m", "uvicorn", "controller.app:app", "--host", "0.0.0.0", "--port", "8090"]
