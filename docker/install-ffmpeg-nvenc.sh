#!/bin/sh
# FFmpeg con NVENC + libx264. Las libs NVIDIA (libnvidia-encode) las inyecta
# el runtime en el Spark; acá solo hacen falta los headers.
set -eu
cd /tmp
curl -fsSL -o nv-codec-headers.tar.gz \
  https://github.com/FFmpeg/nv-codec-headers/archive/refs/heads/master.tar.gz
tar -xzf nv-codec-headers.tar.gz
make -C nv-codec-headers-master install PREFIX=/usr/local

curl -fsSL -o ffmpeg.tar.gz \
  https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n7.1.tar.gz
tar -xzf ffmpeg.tar.gz
cd FFmpeg-n7.1
./configure \
  --prefix=/usr/local \
  --enable-shared \
  --disable-static \
  --disable-doc \
  --disable-ffplay \
  --enable-gpl \
  --enable-libx264 \
  --enable-nvenc \
  --enable-libxcb \
  --enable-xlib
make -j"$(nproc)"
make install
ldconfig
cd /
rm -rf /tmp/nv-codec-headers.tar.gz /tmp/nv-codec-headers-master \
  /tmp/ffmpeg.tar.gz /tmp/FFmpeg-n7.1
