#!/bin/sh
# PocketPrint3D bridge - installer for a Raspberry Pi (Raspberry Pi OS Lite 64-bit) or any Debian/Ubuntu machine.
#
#   curl -fsSL https://pocketprint3d.com/install-bridge.sh | sh
#
# What it does (you can read this file first: https://pocketprint3d.com/install-bridge.sh):
#   1. installs Docker if it isn't there yet (Docker's official script, get.docker.com)
#   2. starts the bridge container ghcr.io/halvar20000/printshare-bridge (host network, starts again after a reboot)
#   3. installs two small commands: `pocketprint3d-code` (shows the pairing code) and `pocketprint3d-update`
#      (gets a new version - runs by itself every night)
#   4. shows the pairing code to enter in the PocketPrint3D app (Settings -> Advanced -> Print from anywhere)
# Everything lives in /opt/pocketprint3d-bridge. The bridge only makes outgoing connections; nothing is opened to
# the internet. Source code: https://github.com/halvar20000/printshare
set -eu

IMAGE="ghcr.io/halvar20000/printshare-bridge:latest"
DIR="/opt/pocketprint3d-bridge"
NAME="${PP3D_NAME:-$(hostname)}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || fail "This installer is for Linux (Raspberry Pi OS, Debian, Ubuntu)."
case "$(uname -m)" in
  aarch64|arm64|x86_64|amd64) ;;
  armv7l|armv6l) fail "This system is 32-bit. Please install 'Raspberry Pi OS Lite (64-bit)' with the Raspberry Pi Imager and run this again." ;;
  *) fail "Unsupported processor: $(uname -m)" ;;
esac
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; command -v sudo >/dev/null || fail "Please run as root or install sudo."; fi

say "1/4  Docker"
if command -v docker >/dev/null 2>&1; then
  echo "Docker is already installed."
else
  echo "Installing Docker - this takes a few minutes on a Raspberry Pi ..."
  curl -fsSL https://get.docker.com | $SUDO sh
fi
$SUDO systemctl enable --now docker >/dev/null 2>&1 || true

say "2/4  PocketPrint3D bridge"
$SUDO mkdir -p "$DIR/config" "$DIR/data"
if [ ! -s "$DIR/token" ]; then
  # access token for the bridge's own web page (only used on your home network)
  head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32 | $SUDO tee "$DIR/token" >/dev/null
  $SUDO chmod 600 "$DIR/token"
fi
printf '%s\n' "$NAME" | $SUDO tee "$DIR/name" >/dev/null

# (re)creates the container - used by the installer and by the nightly update
$SUDO tee /usr/local/bin/pocketprint3d-start >/dev/null <<EOF
#!/bin/sh
set -e
docker rm -f pocketprint3d-bridge >/dev/null 2>&1 || true
docker run -d --name pocketprint3d-bridge --restart unless-stopped --network host \\
  -e PRINTSHARE_API_TOKEN="\$(cat $DIR/token)" -e PRINTSHARE_NAME="\$(cat $DIR/name)" \\
  -v $DIR/config:/config -v $DIR/data:/data $IMAGE >/dev/null
EOF

$SUDO tee /usr/local/bin/pocketprint3d-update >/dev/null <<EOF
#!/bin/sh
# gets a new bridge version if there is one (runs every night)
old=\$(docker image inspect --format '{{.Id}}' $IMAGE 2>/dev/null || true)
docker pull -q $IMAGE >/dev/null || exit 0
new=\$(docker image inspect --format '{{.Id}}' $IMAGE)
[ "\$old" = "\$new" ] && docker ps -q -f name=pocketprint3d-bridge | grep -q . && exit 0
/usr/local/bin/pocketprint3d-start && docker image prune -f >/dev/null
EOF

$SUDO tee /usr/local/bin/pocketprint3d-code >/dev/null <<EOF
#!/bin/sh
# shows the bridge's pairing code (or that it is connected)
TOKEN=\$(sudo cat $DIR/token 2>/dev/null || cat $DIR/token)
for i in \$(seq 1 60); do
  J=\$(curl -fs -H "Authorization: Bearer \$TOKEN" http://127.0.0.1:8484/api/bridge 2>/dev/null) && break
  sleep 2
done
[ -n "\${J:-}" ] || { echo "The bridge doesn't answer yet - wait a minute and run: pocketprint3d-code"; exit 1; }
field() { printf '%s' "\$J" | sed -n "s/.*\\"\$1\\":\\"\\([^\\"]*\\)\\".*/\\1/p"; }
STATE=\$(field state); CODE=\$(field code); ACCOUNT=\$(field account); ERR=\$(field error)
if [ "\$STATE" = "connected" ]; then
  echo "The bridge is connected to the account \$ACCOUNT. All set."
elif [ -n "\$CODE" ]; then
  echo
  echo "  Your pairing code:   \$CODE"
  echo
  echo "  In the PocketPrint3D app: Settings -> Advanced -> Print from anywhere -> enter the code -> Connect."
  echo "  (The code is valid for 10 minutes; afterwards run  pocketprint3d-code  again for a new one.)"
else
  echo "The bridge is starting (\$STATE) \${ERR:+- \$ERR} - run  pocketprint3d-code  again in a minute."
fi
EOF
$SUDO chmod 755 /usr/local/bin/pocketprint3d-start /usr/local/bin/pocketprint3d-update /usr/local/bin/pocketprint3d-code

echo "Downloading the bridge (about 150 MB) ..."
$SUDO docker pull -q "$IMAGE" >/dev/null
$SUDO /usr/local/bin/pocketprint3d-start

say "3/4  Updates every night"
printf '17 4 * * * root /usr/local/bin/pocketprint3d-update\n' | $SUDO tee /etc/cron.d/pocketprint3d-bridge >/dev/null
echo "A new version is installed automatically at night."

say "4/4  Pairing code"
echo "Waiting for the bridge ..."
sleep 5
$SUDO /usr/local/bin/pocketprint3d-code || true
echo
echo "Show the code again at any time with:  pocketprint3d-code"
