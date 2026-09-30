# PocketPrint3D cloud server (Hetzner)

Project `pocketprint3d` in the Hetzner Console, managed through the Cloud API (token in `.hetzner-token`,
SSH key in `.secrets/hetzner_ed25519` – both git-ignored, on Tower only).

| Part | Value |
|---|---|
| Server | CX33 (4 vCPU, 8 GB, 80 GB), Nuremberg, Ubuntu 24.04, backups on |
| Firewall | `pocketprint3d-web`: 80, 443 (tcp+udp), 22 (key only), ICMP |
| Login | user `deploy` with the key above; root login and passwords off |
| App | `compose.yaml` in `/opt/pocketprint3d`: `app` (ghcr.io/halvar20000/printshare:latest) behind `caddy` |
| TLS | Caddy, Let's Encrypt, `api.pocketprint3d.com` |
| Data | `/srv/pocketprint3d/{config,data,caddy}` |
| Updates | OS: unattended-upgrades (reboot 04:30 if needed); app: `pocketprint3d-update.timer` pulls `:latest` every 10 min |

The server is created with `cloud-init.yaml` (the SSH public key is filled in at creation). `compose.yaml` and
`Caddyfile` are copied to `/opt/pocketprint3d` afterwards.

Status: infrastructure only. The app still runs in its single-household mode; the cloud mode (accounts, several
users, limits) is the next step, see `docs/CLOUD.md`.
