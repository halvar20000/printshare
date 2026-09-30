# PocketPrint3D Cloud – concept

Status: **draft for discussion** (Thomas, Dominique), 2026-09-30. Nothing of this is built yet.

## Goal
"Bambu Handy for everyone else", usable by people who have never heard of Docker: install the app, create an
account, print from Printables/Thingiverse. For non-Bambu printers: Elegoo Centauri Carbon (stock firmware),
Klipper/Moonraker (e.g. COSMOS), PrusaLink, OctoPrint.

## Decisions so far (Thomas, 2026-09-30)
| | |
|---|---|
| Operator | Thomas, on **Hetzner** (EU, Germany/Finland) |
| Price | **free**, no subscriptions (an optional donation link is possible) |
| Printables | stays as today: the server downloads the model on the user's behalf |
| Self-hosted | **stays**: Unraid, Home Assistant add-on, Docker – for everyone who wants to keep it local |
| iOS app | **Swift** (Dominique, `printshare-ios`) |
| Android app | Expo / React Native (`mobile/`) |
| Contract between them | the server API, `docs/API.md` |

## The core problem
Bambu printers connect to the Bambu cloud themselves. Our printers only talk on the home network and have no
real authentication (SDCP none, Moonraker usually none). The cloud can therefore never talk to a printer directly,
and a printer must never be reachable from the internet. Something in the home has to pass things on:

- **at home: the phone** (it is on the same Wi-Fi anyway) – nothing to install;
- **away from home: a bridge** – a small always-on thing at home with an *outgoing* connection to the cloud.

Tunnels to the printer (Cloudflare, Tailscale Funnel, port forwarding) were rejected for normal users: the printer
can't run them itself, the setup is too hard, and an open printer can be heated or moved by anyone.

## Architecture

```
                 ┌──────────────────── PocketPrint3D Cloud (Hetzner) ─────────────────────┐
                 │  API (same server code, cloud mode)   accounts · printers · jobs     │
 Printables  ◀───┤  slicing workers (OrcaSlicer CLI, queue)   G-code storage (few days)  │
 Thingiverse ◀───┤  search · model details · Orca Cloud profile sync (#7)               │
                 │  bridge relay (WebSocket, outgoing from the home)                    │
                 └───────▲──────────────────────────────────────────────▲──────────────┘
                         │ HTTPS                                        │ WSS (outgoing)
                 ┌───────┴────────┐   home Wi-Fi (LAN)          ┌──────┴───────────────────┐
                 │  Phone app     │──── SDCP / HTTP ──────────▶ │  Bridge (optional):       │
                 │  iOS / Android │                             │  HA / NAS / Docker server,│
                 └────────────────┘                             │  Klipper plugin, Pi Zero, │
                          │                                     │  later ESP32 / old phone  │
                          ▼                                     └──────┬───────────────────┘
                     3D printer  ◀───────────────── SDCP / HTTP ───────┘
```

## Step 1 – cloud + the phone as relay at home
What the user does: install the app → create an account → "add printer" (the app finds it on the Wi-Fi) → print.

**Cloud (server in cloud mode):**
- Accounts (see "Login" below); every printer, job, upload and profile belongs to one account.
- Printers are stored with name, type and slicing profile – **not** their IP address (only the phone knows it).
- Slicing, search, model details, previews as today; G-code kept a few days, then deleted.
- Limits (everything is free, the server costs are Thomas'): slices per account per day, model size, parallel
  slicing jobs, job age. Clear messages when a limit is reached.

**Apps (iOS and Android):**
- Find printers on the Wi-Fi: Centauri via UDP broadcast (`M99999` on port 3000), Klipper via mDNS
  (`_moonraker._tcp`, only where Moonraker's `[zeroconf]` is enabled) or address entry, PrusaLink/OctoPrint via address entry (+ API key/password).
- Send the G-code from the cloud to the printer (download, then upload on the LAN), start it, read the status,
  pause/resume/cancel, temperatures/fans/light, camera – i.e. the printer adapters of `printshare/printers/`
  **rebuilt in the apps**.
- Away from home without a bridge: search, slice and prepare work; sending waits until the phone is home again
  (or the user adds a bridge).

**Effort / risk:** the printer protocols have to be written twice (Swift and TypeScript). Suggested order to keep
it manageable: Centauri (SDCP) and Moonraker first (Thomas' and Dominique's printers, the largest group), PrusaLink
and OctoPrint later. iOS needs the "local network" permission (`NSLocalNetworkUsageDescription`, Bonjour services).

## Step 2 – bridge for access from everywhere
A bridge keeps one **outgoing** WebSocket to the cloud (no port forwarding, no VPN) and runs the printer adapters.
The cloud sends it jobs ("download this G-code and start it", "status?", "pause"); it answers.

| Bridge | Cost for the user | Notes |
|---|---|---|
| Existing PocketPrint3D server (Unraid, HA add-on, Docker) | 0 € | same software, "connect to PocketPrint3D Cloud" switch + pairing code |
| Klipper/COSMOS plugin next to Moonraker | 0 € | runs on the printer itself, like Obico |
| Old Android phone ("bridge mode" in the app) | 0 € | needs a permanent notification (Android background limits) |
| Raspberry Pi Zero 2 W with a ready image | ~35 € | reuses the Python code almost unchanged; setup with Raspberry Pi Imager |
| ESP32-S3 "PocketPrint3D stick" | ~10 € | later, only with enough users: C++ rewrite, streaming, OTA updates |

Pairing: the bridge shows a code (web page / display / log), the user confirms it in the app (like the Orca Cloud
pairing). The bridge only ever talks to its own printers on the LAN.

## Step 3 – account features
Orca Cloud profile sync (#7, waiting for a `client_id`), job history across devices, push notifications (print
finished / error / paused), sharing a printer within a family.

## Self-hosted stays
The cloud runs **the same server code** as the self-hosted version, with a cloud mode (accounts, several users)
switched on. Self-hosted users keep one token, their own addresses and no account. A self-hosted server can
additionally act as a bridge (step 2) – but nobody has to use the cloud.

## Login
Suggestion: **email + one-time code** (no passwords to store or lose), plus **Sign in with Apple** and **Google**.
Apple requires Sign in with Apple as soon as another social login is offered, and requires account deletion
inside the app. The app keeps a session token in Keychain / Keystore, as it keeps the server token today.

## Hetzner setup (start)
| Part | Suggestion | Rough cost / month |
|---|---|---|
| Server | 1× Hetzner Cloud CX33 (4 vCPU, 8 GB) – running since 2026-09-30 as `api.pocketprint3d.com` | 10.19 € + backups 2.04 € + IPv4 0.60 € |
| Storage | Hetzner Object Storage for uploads/G-code (deleted after a few days) | ~5 € |
| Database | PostgreSQL on the same server (backups to a Storage Box) | ~4 € |
| TLS / domain | Caddy (Let's Encrypt), own domain | ~1 € |
| Monitoring | Uptime Kuma or Hetzner monitoring + e-mail alerts | 0 € |

Growth: more slicing servers behind the queue (OrcaSlicer needs ~1–2 GB RAM and one core per job, seconds to a few
minutes). Prices are estimates – check hetzner.com.

## Legal (Germany / EU)
- **Impressum** and **privacy policy** (web page + app store listings), in German and English.
- **AVV** (data processing agreement) with Hetzner – available in the Hetzner console.
- Data minimisation: no printer IPs in the cloud; uploads and G-code deleted after a few days; account deletion
  removes everything (Apple and Google require it in the app).
- Printables/Thingiverse: downloads only on the user's behalf, one model at a time, never re-hosted to others
  (per-user cache only); an honest User-Agent; rate limits so the Hetzner address doesn't get blocked.
- Safety: remote control of heaters – the confirmation rules of the API (start, cancel, temperatures while
  printing, power off only when not printing) stay mandatory in the cloud and in both apps.

## Order of work (suggestion)
| # | What | Size |
|---|---|---|
| 1 | `docs/API.md` as contract, API kept stable | S – done |
| 2 | Server: cloud mode – accounts, per-account data, limits, login | L – stage 1 done (0.15.0); job persistence open |
| 3 | Hetzner: server, domain, TLS, database, backups, monitoring | M – running (api.pocketprint3d.com); monitoring open |
| 4 | Apps: account login, cloud server as default, printer discovery on the Wi-Fi | M (×2 apps) |
| 5 | Apps: printer protocols for SDCP + Moonraker (send, start, status, control) | L (×2 apps) |
| 6 | Impressum, privacy policy, store listings, beta with a few users | M |
| 7 | Step 2: bridge mode in the existing server + pairing | M |
| 8 | Step 2: Klipper plugin, Pi image | M |
| 9 | Step 3: push notifications, Orca Cloud sync | M |

## Open questions
1. Domain name (e.g. printshare.app / .cloud / .eu – availability?).
2. Login methods: email code + Apple + Google, or fewer?
3. Limits for the free service: how many slices per day and account, maximum model size?
4. How long to keep uploads and G-code (suggestion: 7 days)?
5. Impressum: private person (address public) or an association / company?
6. Step 1 for PrusaLink/OctoPrint right away, or later?
7. Beta: who tests first (Thomas, Dominique, a few Centauri users from forums/Discord)?
