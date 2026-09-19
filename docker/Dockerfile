# Runtime genérico: API + Xvfb + Pulse + ffmpeg + WebRTC. Sin ningún juego.
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

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
        linux-libc-dev \
    && pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && apt-get purge -y gcc python3-dev \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*

COPY controller ./controller
COPY docker/entrypoint.sh /usr/local/bin/station-entrypoint
COPY docker/seed-library.sh /usr/local/bin/station-seed-library
COPY docker/pulse/system.pa /etc/pulse/system.pa
COPY docker/pulse/daemon.conf /etc/pulse/daemon.conf
COPY docker/pulse/asound.conf /etc/asound.conf
COPY docker/pulse/game.pa /etc/pulse/game.pa
COPY docker/pulse/client.conf /etc/pulse/client.conf
COPY docker/openal/alsoft.conf /etc/openal/alsoft.conf
COPY docker/openal/alsoft.conf /root/.alsoftrc
RUN chmod +x /usr/local/bin/station-entrypoint /usr/local/bin/station-seed-library \
    && mkdir -p /tmp/pulse /var/run/pulse /cache /opt/game /opt/station-library \
    && chmod 777 /tmp/pulse /cache

ENV PYTHONUNBUFFERED=1
ENV HOME=/root
ENV XDG_CONFIG_HOME=/root/.config
ENV STATION_DISPLAY=:99
ENV STATION_SIZE=1280x720
ENV STATION_HTTP_PORT=8090
ENV PULSE_SERVER=unix:/tmp/pulse/native
ENV PULSE_SINK=game
ENV STATION_PULSE_SINK=game
ENV STATION_PULSE_SOURCE=game.monitor
ENV STATION_PULSE_PA=/etc/pulse/game.pa
ENV SDL_AUDIODRIVER=pulse
ENV ALSOFT_DRIVERS=pulse
ENV ALSOFT_CONF=/etc/openal/alsoft.conf
ENV LIBRARY_ROOT=/opt/station-library
ENV CACHE_ROOT=/cache
ENV IDLE_TIMEOUT_S=300
ENV GAME_MANIFEST=/opt/game/manifest.yaml
LABEL org.airtek.role=game-station-runtime
EXPOSE 8090
HEALTHCHECK --interval=5s --timeout=3s --retries=12 --start-period=8s \
    CMD python3 -c "import os,urllib.request; p=os.environ.get('STATION_HTTP_PORT','8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=2)"
ENTRYPOINT ["/usr/local/bin/station-entrypoint"]
