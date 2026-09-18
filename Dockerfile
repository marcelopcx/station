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
        libopenal1 \
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
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY controller ./controller
ENV PYTHONUNBUFFERED=1
ENV STATION_DISPLAY=:99
ENV STATION_SIZE=1280x720
ENV STK_BIN=/opt/stk/run_game.sh
EXPOSE 8090
CMD ["python3", "-m", "uvicorn", "controller.app:app", "--host", "0.0.0.0", "--port", "8090"]
