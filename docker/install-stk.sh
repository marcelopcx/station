#!/bin/sh
# SuperTuxKart 1.5 para la imagen del Spark (linux/arm64).
# No commitear el tar.gz: se baja en el docker build y se instala en /opt/stk.
set -eu

VERSION="${STK_VERSION:-1.5}"
ARCH="${TARGETARCH:-arm64}"

case "$ARCH" in
  arm64|aarch64)
    PKG=linux-arm64
    SHA=961b4b691b44547cdcada7ba39dad1561a6e7e766c90b22ca2df1fa18aa2e477
    ;;
  amd64|x86_64)
    PKG=linux-x86_64
    SHA=57090b6c2163eb691f20104ae9712204acbb4e8341059dee0a5ff5315efc401b
    ;;
  *)
    echo "STK: TARGETARCH=$ARCH no soportado (Spark es linux/arm64)" >&2
    exit 1
    ;;
esac

URL="https://github.com/supertuxkart/stk-code/releases/download/${VERSION}/SuperTuxKart-${VERSION}-${PKG}.tar.gz"
echo "STK: downloading $URL"
curl -fL --retry 3 -o /tmp/stk.tar.gz "$URL"
echo "$SHA  /tmp/stk.tar.gz" | sha256sum -c -

mkdir -p /tmp/stk-extract
tar -xzf /tmp/stk.tar.gz -C /tmp/stk-extract
SCRIPT=$(find /tmp/stk-extract -maxdepth 3 -name run_game.sh | head -n 1)
if [ -z "$SCRIPT" ]; then
  echo "STK: no hay run_game.sh en el archive" >&2
  exit 1
fi

SRC=$(dirname "$SCRIPT")
mkdir -p /opt/stk
cp -a "$SRC"/. /opt/stk/
chmod +x /opt/stk/run_game.sh
if [ -x /opt/stk/bin/supertuxkart ] || [ -f /opt/stk/bin/supertuxkart ]; then
  chmod +x /opt/stk/bin/supertuxkart
fi
ln -sfn /opt/stk/run_game.sh /usr/local/bin/supertuxkart
rm -rf /tmp/stk.tar.gz /tmp/stk-extract
echo "STK: installed $VERSION $PKG -> /opt/stk"
