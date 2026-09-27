# CLAUDE.md — PrintShare (project "3dprinting from Smartphone")

Handover from the Claude Cowork session of 2026-09-26. Read this first, then
`docs/ROADMAP.md` (status vs. requirements) and
`Mobile Print-App – Softwareanforderungen.md` (full requirements spec by Dominique, German).

## What this is
A self-hosted "Bambu Handy for everyone else": send a Printables/Thingiverse link
from the phone → the server downloads the model, slices it with the OrcaSlicer
command line, uploads the G-code to the printer and starts it.
Open source (MIT), personal use first, documented on YouTube later.

- GitHub: https://github.com/halvar20000/printshare (public, branch `main`, first commit 168359d)
- This folder is the working copy on Unraid: `/mnt/user/AI/Projects/3dprintinghandy`
  (seen from the Mac as `/Volumes/AI/Projects/3dprintinghandy`). The old copy in
  `~/Developer/3dprintinghandy` on the Mac is obsolete.

## People and hardware
- **Thomas** (owner, GitHub `halvar20000`): Elegoo Centauri Carbon with **stock firmware**
  → adapter `elegoo_sdcp`. Also 2× Bambu P1S (not in scope, they have Bambu Handy).
  Unraid server "Tower" 192.168.86.230, Tailscale (`tower`), iPhone 14 Pro + Galaxy S24 Ultra.
- **Dominique** (Thomas' son, co-developer, author of the requirements spec): Centauri Carbon
  with **OpenCentauri COSMOS** firmware (Klipper + Moonraker + Mainsail on port 80), plans
  CANVAS (4 lanes via AFC). Runs his own Unraid; installs his own container.
- Communicate with Thomas in the language he writes; for dense technical topics prefer German.
  Give copy-paste-ready commands (he pastes into a plain-text editor first).

## Architecture (P0, implemented)
```
phone ─link─▶ printshare container (Unraid, port 8484) ─▶ Printables GraphQL / Thingiverse API
                   │ OrcaSlicer 2.4.2 CLI (AppImage extracted to /opt/orca)
                   └▶ elegoo_sdcp (pycentauri)  |  moonraker (HTTP /server/files/upload)
```
| File | Purpose |
|---|---|
| `printshare/fetch.py` | parse links, list model files, download (Printables GraphQL `ModelFiles` + `GetDownloadLink`, Thingiverse API w/ token, direct URL, local path for CLI) |
| `printshare/profiles.py` | index OrcaSlicer system presets (shared `ProfileLibrary.cached`), flatten `inherits`, `compatible()` presets per machine |
| `printshare/slicer.py` | build machine/process/filament JSON, run Orca CLI, extract G-code + estimates |
| `printshare/config.py` | `config.yaml` model, `cosmos` machine preset, bed type, `JobOptions` (per-job material/quality/plate/supports/brim/infill/walls) |
| `printshare/printers/elegoo.py` | stock CC via pycentauri (upload HTTP :80 `/uploadFile/upload` 1 MB chunks, WS :3030 start/status) |
| `printshare/printers/moonraker.py` | Klipper/COSMOS: tries configured URL, then :7125 |
| `printshare/pipeline.py` | `prepare_job` (download + slice, queue via `max_parallel_slices`) → `send_job`; `run_job` = both |
| `printshare/api.py` | FastAPI: app flow `/api/jobs` → review → `/send` (confirm required), options, printer control, PWA files |
| `printshare/web/` | PWA: `index.html`, `app.js` (plain JS, DE/EN texts), `app.css`, `manifest.webmanifest` (share target), `sw.js`, `icons/` (`scripts/make_icons.py`) |
| `printshare/cli.py` | `printshare print|files|status|presets|printers|serve` |
| `tests/` | fake SDCP printer + fake Moonraker (aiohttp); `test_api.py` app flow; preset tests need `ORCA_PROFILES`; real slicing needs `ORCA_ROOT` |

## Hard-won findings (do not re-learn these)
1. Orca CLI rejects flattened presets unless `"from": "system"` → otherwise
   "process not compatible with printer", exit 239/-17.
2. Orca CLI defaults `curr_bed_type` to Cool Plate (35 °C bed for PLA). We set it
   explicitly (`bed_type`, default "Textured PEI Plate" → 60 °C).
3. `--allow-newer-file` takes NO value (with "1" Orca treats "1" as a file).
4. Orca writes `00000.log` into its CWD → subprocess runs with `cwd=work`.
5. Output: `--export-3mf result.3mf` + `--outputdir`; plain `plate_1.gcode` also appears.
   Thumbnails are blank headless (no OpenGL) — P1 item.
6. Orca CLI *does* have `--arrange 1` and `--orient` (spec PL-04 says it doesn't — it does, v2.4.2).
7. COSMOS ≥ 26.07 e-stops on stock Elegoo start G-code (`M729`, `M8213`). `machine_preset: cosmos`
   replaces start/end with `PRINT_START EXTRUDER=[nozzle_temperature_initial_layer]
   BED=[bed_temperature_initial_layer_single] CHAMBER=[chamber_temperature]` / `PRINT_END`.
   Preferred long-term: official COSMOS Orca profile (https://cloud.orcaslicer.com/b/3fad3c38f25f)
   exported as JSON → `machine_file:`.
8. Stock CC upload port is **80**, not 3030 as some docs claim (pycentauri verified live).
   Thomas' CC (192.168.86.144, FW V0.3.0-o) did NOT push Attributes (MainboardID) even when
   idle → adapter now gets it via unicast UDP discovery (`M99999` to host:3000) unless
   `mainboard_id` is set in config. Broadcast discovery doesn't work from bridged containers.
9. Running slicing on the event loop froze the web server → fixed with `asyncio.to_thread`.
10. Relevant Orca preset names: machine `Elegoo Centauri Carbon 0.4 nozzle`,
    process `0.20mm Standard @Elegoo CC 0.4 nozzle`, filament `Elegoo PLA @ECC`.

## Verified so far (sandbox, 2026-09-26)
- 6/6 tests green (`ORCA_ROOT=/path/to/squashfs-root pytest -q`).
- Live Printables download + slice: Benchy → 34m52s / 11.4 g (COSMOS), 3MF input works.
- API end-to-end against fake Moonraker; web server stays responsive while slicing.
- 2026-09-26 on Unraid (after reboot): container runs; API job Benchy `start:false` → 35m32s / 11.49 g,
  `3dbenchy.gcode` (2.6 MB, 240 layers) arrived on Thomas' CC via SDCP. **NOT yet verified:** a real
  started print (SDCP), anything on COSMOS.

## Current state of the Unraid install (2026-09-26 evening)
- `docker build` is GREEN on Unraid (image `printshare:0.1`, Orca 2.4.2 `--help` runs). Needed extra
  libs (libSM/ICE/secret/wayland…) — Dockerfile now fails the build listing all missing libs (ldd check).
- Install = `bash scripts/unraid-install.sh cc-thomas` (as root on the host). Copies the gitignored
  `config.yaml` from the project folder (token, printer 192.168.86.144, mainboard_id) to
  `/mnt/user/appdata/printshare/` on first run. `APPDATA` in the script is the config location.
- Container RUNNING since the reboot (config in /mnt/user/appdata/printshare). Earlier the script hung at `mkdir -p /mnt/user/appdata/...` because Unraid's
  `shfs` (/mnt/user) had been deadlocked since 2026-09-21 (smbd + `find /mnt/user/.thumbnails -delete`;
  every create at /mnt/user top level hangs in D state; hetzner-cls backups hung too).
  Logs saved to `/boot/logs/shfs-hang-2026-09-26/`. Fixed by reboot 2026-09-26 19:36 UTC.
- Array itself is fine (all disks DISK_OK; slot 29 DISK_NP_DSBL = empty parity2 slot, normal).
- This claude-agent container has no Docker socket and only sees `/mnt/user/AI`; it CAN reach the
  LAN (printer 192.168.86.144, host 192.168.86.230).

## Smartphone app (decided 2026-09-26: PWA)
- Thomas chose a PWA over SwiftUI/Expo: iPhone + Android, no Apple account, deployable from here.
  App-MVP (spec phase 2) implemented: share/paste link → options → slice → review (time, g, layers,
  changed values) → "plate empty" checkbox → Print / Upload only; jobs list; printer tab with
  pause/resume/cancel. UI checked with headless Chromium (puppeteer-core) at 390×844, light + dark.
- Install/share need HTTPS: `tailscale serve --bg --https=8443 http://127.0.0.1:8484` on the host.
- NOT yet verified on real phones or with real slicing through the new flow (Orca can't run in the
  claude-agent container: its glibc is too old → test slicing only inside the Docker image).

## Next steps (in order)
1. Deploy the PWA (rerun `scripts/unraid-install.sh cc-thomas`), set up Tailscale Serve, install on
   both phones, test share → slice → upload-only; then a real print with Thomas at the printer.
2. After the reboot: rerun `scripts/unraid-install.sh cc-thomas`; check that the parity check and the
   hetzner-cls backup ran; then `printshare print <benchy> -p cc-thomas --no-start`, then a real
   print — for both printers (Thomas: SDCP; Dominique: COSMOS).
3. Then work down `docs/ROADMAP.md` (Phase 1 gaps from the spec first).

## Conventions
- Python ≥ 3.10, English code/comments/docs; user-facing texts German first later (NF-11).
- Keep printer and model-source integrations as swappable adapters (NF-08).
- Pin OrcaSlicer version (`ORCA_VERSION` build arg); upgrade only after reference-model tests.
- Never start a print without explicit confirmation from the user (NF-05) — web page currently
  has "Print" and "Upload only"; the app must add a confirmation step.
- Printables: only on the user's behalf, one model at a time, never re-host files.
- Commit trailer used so far: `Co-Authored-By: Claude <noreply@anthropic.com>`.
