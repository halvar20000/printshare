# PocketPrint3D bridge – concept (2026-10-02)

Status: **steps 2–6 built** – cloud side in 0.24.0 (`printshare/cloud/bridges.py`, `cloud/hub.py`), bridge mode of the
server in 0.25.0 (`printshare/bridge/`), cloud forwarding in 0.26.0, Android app (Settings → Erweitert → "Unterwegs
drucken"), packaging in 0.27.0: `printshare bridge`, `Dockerfile.bridge` → `ghcr.io/halvar20000/printshare-bridge`
(amd64 + arm64, CI smoke test), HA add-on options `cloud_bridge` / `lan_subnet`, Unraid fields, web page card
"Unterwegs drucken" (code + state), `deploy/bridge/docker-compose.yml`. Open: step 1 (Bambu, after Sunday's probe),
step 7 (Pi image), a real phone + real printer test.

## 1. Goal

The cloud app should reach the printers at home **from everywhere** – e.g. Thomas' Centauri Carbon (stock firmware)
and his two Bambu P1S (LAN mode) – without port forwarding, tunnels or a printer reachable from the internet. Something
at home has to keep an **outgoing** connection to the cloud and talk to the printers on the LAN: the bridge.

Product principle (CLAUDE.md): a bridge is **optional**. Without one, the phone sends to the printer at home, as today.
Users who want remote access get a guided step ("Auch unterwegs drucken?"): install one thing, enter a code, done.

## 2. Decision: our own bridge = the existing server in bridge mode

| Option | Why not (as the foundation) |
|---|---|
| OctoPrint | one USB/serial printer per instance; no Centauri (SDCP) support; Bambu only through a plugin that emulates a serial printer; beginners would install OctoPrint + plugins per printer |
| Klipper / Moonraker | one Klipper printer per instance, no SDCP/Bambu |
| OctoFarm, FDM Monster | manage OctoPrint instances only |
| Home Assistant integrations (ha-bambulab, Elegoo) | status and switches yes, but no uniform "upload G-code + start"; third-party code we don't control |
| Bambuddy, Mainsail, Prusa Connect | one brand each |
| OctoEverywhere, SimplyPrint, Printago | closed cloud services, not a building block |

No open local platform drives SDCP, Bambu LAN, Klipper, PrusaLink and OctoPrint side by side. Our server already has
tested adapters for four of them (`printshare/printers/`), plus camera, controls, power (Home Assistant), Spoolman and
AI failure detection. The bridge is therefore **the same Python package** with a bridge mode – no second code base.
OctoPrint/Moonraker plugins come later as optional "mini bridges" for exactly one printer (section 11).

## 3. Overview

```
 Phone app ──HTTPS──▶ api.pocketprint3d.com (cloud mode)
 (iOS/Android)           │  accounts · slicing · jobs · bridge hub
                         │
                         ▲ WSS, opened BY the bridge (outgoing only), one per bridge
                         │
               PocketPrint3D bridge (at home: Unraid/Docker, HA add-on, Pi Zero 2 W, …)
               ├─ elegoo_sdcp ──▶ Centauri Carbon            (UDP 3000, WS 3030, HTTP 80)
               ├─ bambu_lan   ──▶ P1S #1, P1S #2             (MQTT TLS 8883, FTPS 990)
               ├─ moonraker   ──▶ Klipper / COSMOS           (HTTP 80 / 7125)
               ├─ prusalink / octoprint
               └─ (optional) Home Assistant power, Spoolman, Obico ML API, camera
```

- The cloud never opens a connection into the home. It can only send the **fixed commands** of section 6 over the
  bridge's own WebSocket.
- Printer addresses and credentials (PrusaLink password, OctoPrint key, Bambu access code) are stored **on the bridge
  only** (section 7).

## 4. Bridge modes and packaging

| Package | For whom | Notes |
|---|---|---|
| **Existing server** (Unraid template, HA add-on, Docker) + switch "Mit PocketPrint3D Cloud verbinden" | self-hosters (Thomas, Dominique) | full server incl. Orca; local app/web keep working; its printers additionally appear in the cloud account |
| **Slim image** `ghcr.io/halvar20000/printshare-bridge` | Docker/NAS users who use the cloud | same package without OrcaSlicer (slicing is in the cloud): python:slim, ~100 MB, amd64/arm64/armv7 |
| **HA add-on option** | Home Assistant users | the existing add-on with `cloud_bridge: true`, or a slim add-on variant |
| **Raspberry Pi image** (0.34.0, `pi-image/`) | people without anything running at home | Raspberry Pi OS Lite 64-bit (pi-gen, trixie) + Docker + the bridge image preloaded; LAN cable, no setup; found and paired by the app on the Wi-Fi (section 5a); status page `http://pocketprint3d.local` |
| OctoPrint plugin / Moonraker component | people who run those already | later; bridge for that one printer |

Start: `printshare serve` with `PRINTSHARE_BRIDGE=1` (or config `bridge: {enabled: true}`) for the full server;
`printshare bridge` = bridge only (no slicing endpoints, small local status page on port 8484: pairing code, printers,
connection state, log).

## 5. Pairing

1. The bridge (first start, or "neu verbinden") calls `POST /api/bridge/pair/start` with its `bridge_id` (random UUID,
   kept in `<config dir>/bridge.yaml`), its version and its **public key** (X25519, section 7). The cloud answers with a
   **pairing code** (8 characters, `K7Q4-M2ZX`, unambiguous alphabet, 10 min TTL) and a poll secret.
2. The bridge shows the code: local status page, container log, HA add-on page, later the Pi's web page (+ QR code
   `printshare://bridge?code=…`).
3. In the app: Settings → "Brücke verbinden" → enter or scan the code → `POST /api/bridges/pair {code, name}`
   (logged-in user). The cloud binds the bridge to the account.
4. The bridge polls `POST /api/bridge/pair/poll {poll secret}` (every 3 s) and receives its **bridge token** (long-lived,
   random 32 bytes; the cloud stores only its SHA-256). Stored in `bridge.yaml` (0600).
5. Unpairing: app "Brücke entfernen" (`DELETE /api/bridges/{id}`, token revoked, live socket closed) or on the bridge
   ("Verbindung trennen" deletes the token).

### 5a. Ready-made bridge on the Wi-Fi (0.34.0)

A **bridge-only** install (`PRINTSHARE_BRIDGE_ONLY=1`: the bridge image and the Raspberry Pi image) can be paired without
typing anything:
- `GET /api/bridge/hello` (no token) → `{"pocketprint3d": "bridge", "version", "name", "bridge_id", "state", "paired",
  "account": "t***@example.org", "bridge_only", "pairable"}`. The app probes every address of the phone's /24 on ports 80
  and 8484 (plus `pocketprint3d.local`), like the printer search.
- `GET /api/bridge/local-code` (no token) → `{"code", "expires_in", "name"}`; the app then calls `POST /api/bridges/pair`
  with it. Handed out only when all of these hold: bridge-only install, not paired, a code is shown; the client is on a
  private/loopback/link-local address; no `X-Forwarded-For`/`Forwarded`/`X-Real-IP` header (no reverse proxy); and the
  `Host` header is an IP address, `localhost`, `*.local` or the machine's host name (DNS rebinding: a web page on
  evil.example pointed at the bridge can't read it). No CORS headers. Someone on the home network could pair an
  unpaired bridge with their own account – the same as reading the code from its page; the owner sees the bridge isn't
  in their account and presses "Brücke entfernen"/re-pairs. Full servers (Unraid, HA) never hand the code out without
  their token.
- `GET /bridge` (and `/` on a bridge-only install): status page – connected (account masked) or the code under the same
  rules, reloads every 10 s.

The Pi image (`pi-image/stage-pp3d`, built by `.github/workflows/pi-image.yml` with usimd/pi-gen-action on an arm64
runner, release `pi-image-v<version>` → `pocketprint3d-bridge-pi.img.xz`): host name `pocketprint3d`, user `pp3d`
**locked** (no password), SSH off; `pocketprint3d-firstboot.service` loads the preloaded image, creates the token and
starts the container (host network, `PRINTSHARE_PORT=80`); `pocketprint3d-update.timer` pulls `:latest` nightly;
unattended-upgrades for the OS; Docker logs capped (SD card).

Rate limits like the login codes: 5 code attempts per account per 15 min, 20 pair starts per IP per hour. Several
bridges per account are allowed (e.g. home + workshop).

## 6. Connection and commands

**Socket:** `wss://api.pocketprint3d.com/api/bridge/ws`, header `Authorization: Bearer <bridge token>`. One socket per
bridge (a new one replaces the old). Ping every 25 s; reconnect with backoff 1 s → 60 s plus jitter. First frame from
the bridge: `hello {bridge_id, version, printers: [...]}`; the cloud answers `welcome {min_version}` or closes with a
reason (revoked, too old).

**Frames** (JSON text; binary frames later for camera streams):
```
request   {"id": "r17", "type": "req", "method": "printer.status", "params": {"printer": "cc"}}
response  {"id": "r17", "type": "res", "ok": true, "result": {...}}
          {"id": "r17", "type": "res", "ok": false, "error": {"code": "offline", "message": "printer not reachable"}}
event     {"type": "event", "event": "printer.state", "data": {"printer": "cc", "kind": "active", "progress": 42}}
```
Requests go cloud → bridge (each with a timeout); events go bridge → cloud. The bridge rejects unknown methods
(`unknown_method`) – the list below is the whole surface.

| Method | Params | Bridge does | Timeout |
|---|---|---|---|
| `printers.list` | – | its printers: id, name, type, Orca machine, capabilities (camera, controls, power, lanes, leveling) | 10 s |
| `printer.status` | printer | `adapter.status()` (same shape as `GET /api/printers/{id}/status`) | 15 s |
| `printer.control` | printer, action pause/resume/cancel | `adapter.control()` | 30 s |
| `printer.controls` / `printer.adjust` | printer; kind, id, value, confirm | as `/controls`, `/adjust` (same confirm rules) | 15 s |
| `printer.temperatures` | printer | as `/temperatures` | 15 s |
| `printer.camera.snapshot` | printer, w (≤ 1280) | one JPEG, base64, ≤ 400 KB | 15 s |
| `printer.power` | printer, on? | Home Assistant power (config on the bridge) | 20 s |
| `job.send` | printer, job, start, leveling, lanes, spool_id, confirm | downloads `GET /api/bridge/jobs/{job}/gcode?lanes=…` with its token, uploads to the printer, starts it if `start` | 15 min |
| `watch.state` / `watch.mute` | printer | AI failure detection (runs on the bridge, it has the camera) | 10 s |
| `discover` | – | finds printers on its LAN (section 9) | 30 s |
| `printer.add` / `printer.update` / `printer.remove` | config, sealed secrets | stores the printer locally (section 7) | 30 s |

Events: `printer.state` (kind changes, progress every 5 %, finished/error – later for push notifications),
`watch.alert`, `job.progress` (upload steps), `printers.changed`.

**Cloud API for the apps:** the existing printer endpoints stay the contract. Today they answer 409 "local only" in
the cloud; for a printer with a `bridge_id` the cloud forwards them over the hub instead:
`GET /api/printers/{id}/status|controls|temperatures|camera/snapshot`, `POST /control|adjust|power`,
`POST /api/jobs/{id}/send`, `GET/POST /watch/...`. New: `GET /api/bridges` (name, online, version, last_seen,
printers), `POST /api/bridges/pair`, `DELETE /api/bridges/{id}`, `POST /api/bridges/{id}/discover`,
`POST /api/bridges/{id}/printers` (add with sealed secrets). Bridge offline → 503 `bridge_offline` with a clear text.

## 7. Security

- **Outgoing only.** The bridge connects to one configured cloud base URL (default `https://api.pocketprint3d.com`);
  it never fetches other URLs on behalf of the cloud. G-code comes only from `/api/bridge/jobs/{job}/gcode` of its own
  account (the cloud checks job owner = bridge owner).
- **Whitelist.** Only the methods of section 6; no "HTTP request to X", no shell, no file access beyond G-code upload.
- **NF-05:** `job.send` with `start: true` and heater/fan changes during a print need `confirm: true`, which the cloud
  only sets when the app request carried it (user tapped "Drucken" in the confirmation dialog). The bridge logs every
  start with user and job.
- **Secrets stay at home, end-to-end:** when a printer is added from the app, its address and the PrusaLink password /
  OctoPrint key / Bambu access code are encrypted in the app with the bridge's public key and passed through the cloud
  as an opaque blob. The cloud stores neither the secrets nor the printer addresses. The private key never leaves
  `bridge.yaml`. Scheme **"pp3d-seal-v1"** (`printshare/bridge/seal.py`), chosen so that every platform has the parts
  built in (Swift CryptoKit, `@noble/curves` + `@noble/ciphers` + `@noble/hashes` in JS, `cryptography` in Python):
  ephemeral X25519 key pair `e`; `shared = X25519(e, bridge public key)`; `key = HKDF-SHA256(shared, salt = e.public ‖
  bridge public key, info = "pp3d-seal-v1", 32 bytes)`; `blob = base64(e.public ‖ ChaCha20-Poly1305(key, nonce = 12 zero
  bytes, JSON))`. The key is new for every message, so the fixed nonce is safe. Plaintext JSON: `{"address", "password"?,
  "api_key"?, "access_code"?}`.
- **Tokens:** bridge token stored hashed in the cloud, revocable from the app; pairing codes short-lived and rate limited.
- **Limits:** G-code ≤ 200 MB, one `job.send` per printer at a time, camera snapshots ≤ 1 per 2 s per printer,
  requests per bridge per minute capped. Versions: the cloud can refuse bridges below `min_version` (security fixes).
- **Logging:** no secrets, no full addresses in the cloud log; bridge log local.

## 8. Bambu Lab in LAN mode (P1S, P1P, X1, A1)

The bridge is where Bambu support fits best: MQTT over TLS and FTPS are a few lines in Python, while the phone would
need another native module.

- Printer side: **LAN Only + Developer Mode** (newer firmware with "Authorization Control" only allows third-party
  control then – this cuts the printer off from Bambu Handy/cloud; to be verified on Thomas' P1S, Sunday 2026-10-04,
  `scripts/bambu_probe.py`).
- Adapter `printshare/printers/bambu.py` (`bambu_lan`): MQTT `8883` (TLS, Bambu's own CA; user `bblp`, password =
  access code), subscribe `device/<serial>/report`, `{"pushing": {"command": "pushall"}}` for full state; upload via
  implicit FTPS `990` to the SD card; start with `{"print": {"command": "project_file", "url": "ftp:///<file>", …}}`
  (Bambu expects a .3mf with G-code inside → the bridge wraps the sliced G-code into a minimal 3MF); pause/resume/stop
  via `print.command`. AMS trays become `lanes` (same shape as AFC/CANVAS, `ams_mapping`).
- Slicing: Orca has Bambu P1S presets (`Bambu Lab P1S 0.4 nozzle`), so the cloud slices as for any printer.
- Camera: P1 series = JPEG stream on TCP 6000 (TLS, access-code auth), X1 = RTSP – snapshot first.
- Discovery: SSDP `NOTIFY` on UDP 2021 (`DevModel.bambu.com`, `DevName…`, serial in `USN`); fallback: hosts with ports
  8883 + 990 open whose TLS certificate is issued by "BBL CA" – the certificate CN is the serial number (checked on
  Thomas' network 2026-10-02: 192.168.86.20 and .53, serials `01P0…`).

**Built (0.35.0):** `printshare/printers/bambu.py`, type `bambu_lan` (host + access code as `password`; serial read from
the TLS certificate). Verified on a P1S in LAN-only + developer mode (FW 01.09.01.00): status, AMS lanes, upload and a
real print with `ams_mapping`. A P1S on FW 01.08.01.00 in cloud mode answers status and the light command too; print
start in cloud mode not tested yet. Camera (port 6000) still open.

## 9. Discovery on the bridge

`printshare/discovery.py`, a Python port of `mobile/src/lib/lan/discover.ts` plus Bambu: SDCP `M99999` broadcast
(UDP 3000), Moonraker `/server/info` (80, 7125; COSMOS by its macros), PrusaLink 401 realm "Printer API", OctoPrint web
page, Bambu SSDP/certificate. The bridge sees broadcasts and multicast reliably (it is always on the LAN, unlike the
phone or a bridged Docker container – Docker users need `network_mode: host` for broadcasts, the slim image documents
that; the HTTP scan works either way). Results go to the app (`discover`), the user taps, enters a code/password if
needed, done.

## 10. Apps

- Settings → "Brücke verbinden" (code entry + QR scan), list of bridges (online/offline, version, printers),
  "Brücke entfernen".
- Printers of a bridge are marked "über Brücke"; status/control/camera/send go through the cloud API (the code path the
  app already uses for own servers). A bridge printer has no LAN address on the phone in v1; later: prefer the LAN
  directly when the phone is home and the printer answers (faster upload), else the bridge.
- "Drucker hinzufügen" on a bridge: the list comes from `POST /api/bridges/{id}/discover` (same UI as the Wi-Fi search).
- Android (Expo, me) and iOS (Swift, Dominique) build against the same endpoints; sealed boxes: `tweetnacl` (JS) and
  "pp3d-seal-v1" (section 7) is built from CryptoKit parts (Curve25519.KeyAgreement, HKDF, ChaChaPoly).

## 11. Later

- Camera live stream through the bridge (binary frames, a few fps, only while the screen is open, bandwidth cap).
- Push notifications from bridge events (print finished, error, failure alert) – FCM/APNs in the cloud.
- OctoPrint plugin and Moonraker component as single-printer bridges (they speak the same socket protocol).
- Old Android phone as a bridge (foreground service), ESP32 stick (C++) only with many users.
- Sharing a bridge's printers within a family account.

## 12. Order of work

| # | Step | Size |
|---|---|---|
| 1 | Bambu probe on one P1S (Sunday), then `bambu_lan` adapter + discovery in the self-hosted server | M |
| 2 | Cloud: `bridges` table, pairing endpoints, WebSocket hub (in-process; one server is enough for now), job G-code endpoint for bridges | M |
| 3 | Bridge client in the server package: pairing, socket loop, method dispatch to the adapters, sealed-box secrets | M |
| 4 | Cloud forwarding of the existing printer endpoints for bridge printers; 503 `bridge_offline` | S |
| 5 | Android app: "Brücke verbinden", bridge printers, add printer via bridge discovery; `docs/API.md` | M |
| 6 | Slim image (multi-arch) + HA add-on option + Unraid template field; docs/website | S |
| 7 | Pi Zero 2 W image | M |

Tests: a fake cloud hub and the existing printer fakes (`tests/fakes.py`) + a fake Bambu (MQTT/FTPS) in pytest; the
whole path (app → cloud → bridge → fake printer) in the web-build harness like the cloud tests.

## 13. Open questions

- Does the P1S in Developer Mode accept `project_file` with a plain-G-code 3MF, and does it keep working with Bambu
  Handy switched off? (Sunday's probe.)
- Camera streaming cost on the Hetzner server (traffic is included up to 20 TB/month – likely fine).
- Bridge updates: the slim image auto-updates via the user's container manager; the Pi image needs its own updater.
