# Native libs for aiortc/PyAV: lavfi (ffmpeg), VP8 (libvpx), Opus, SRTP.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libopus0 \
        libvpx9 \
        libsrtp2-1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controller ./controller
ENV PYTHONUNBUFFERED=1
EXPOSE 8090
CMD ["uvicorn", "controller.app:app", "--host", "0.0.0.0", "--port", "8090"]
