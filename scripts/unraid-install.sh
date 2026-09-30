#!/bin/bash
# Build and (re)start the PocketPrint3D container on an Unraid host. Run as root:
#   bash /mnt/user/AI/Projects/3dprintinghandy/scripts/unraid-install.sh [printer-id]
# The first run copies ./config.yaml (or config-example.yaml) to appdata; later runs keep it.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APPDATA=/mnt/user/appdata/printshare
IMAGE=printshare:0.1

cd "$SRC"
echo "== Building $IMAGE from $SRC"
docker build -t "$IMAGE" .

# OrcaSlicer's shared libraries are checked during the build (see Dockerfile).

mkdir -p "$APPDATA/data"
if [ ! -f "$APPDATA/config.yaml" ]; then
  if [ -f config.yaml ]; then cp config.yaml "$APPDATA/config.yaml"
  else cp config-example.yaml "$APPDATA/config.yaml"; echo "!! Edit $APPDATA/config.yaml (api_token, printer IP) and run again"; exit 1
  fi
  chmod 600 "$APPDATA/config.yaml"
fi

echo "== (Re)starting container"
docker rm -f printshare >/dev/null 2>&1 || true
docker run -d --name printshare --restart unless-stopped -p 8484:8484 \
  -v "$APPDATA:/config" -v "$APPDATA/data:/data" "$IMAGE"
sleep 3
docker logs --tail 20 printshare

PRINTER="${1:-}"
if [ -n "$PRINTER" ]; then
  echo "== Printer status ($PRINTER)"
  docker exec printshare printshare status -p "$PRINTER"
fi
echo "== Done: http://$(hostname -i 2>/dev/null | awk '{print $1}'):8484"
