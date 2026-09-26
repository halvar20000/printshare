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
| `printshare/profiles.py` | index OrcaSlicer system presets, flatten `inherits` chains |
| `printshare/slicer.py` | build machine/process/filament JSON, run Orca CLI, extract G-code + estimates |
| `printshare/config.py` | `config.yaml` model, `cosmos` machine preset, bed type |
| `printshare/printers/elegoo.py` | stock CC via pycentauri (upload HTTP :80 `/uploadFile/upload` 1 MB chunks, WS :3030 start/status) |
| `printshare/printers/moonraker.py` | Klipper/COSMOS: tries configured URL, then :7125 |
| `printshare/pipeline.py` | link → download → slice → send (blocking steps in `asyncio.to_thread`) |
| `printshare/api.py` + `web/index.html` | FastAPI + phone web page, Bearer token, in-memory jobs |
| `printshare/cli.py` | `printshare print|files|status|presets|printers|serve` |
| `tests/` | fake SDCP printer + fake Moonraker (aiohttp), real Orca slicing if `ORCA_ROOT` set |

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
- **NOT yet verified:** `docker build` on real Docker, real printers (neither SDCP nor COSMOS).

## Current state of the Unraid install (where we stopped)
- Thomas is installing the container by hand. Earlier attempt used
  `/mnt/user/AI/Projects/printshare` (did not exist). Plan now: source in this folder,
  config/data in `/mnt/user/appdata/printshare/`.
- Pitfall seen: pasting several lines into the Unraid web terminal only inserts them
  (bracketed paste) — press Enter.
- Build/run (as root on the Unraid host — the claude-agent container probably has no Docker socket):
```
cd /mnt/user/AI/Projects/3dprintinghandy
docker build -t printshare:0.1 .
mkdir -p /mnt/user/appdata/printshare/data
cp config.example.yaml /mnt/user/appdata/printshare/config.yaml   # set api_token + printer IP, delete other printer block
docker run -d --name printshare --restart unless-stopped -p 8484:8484 \
  -v /mnt/user/appdata/printshare:/config -v /mnt/user/appdata/printshare/data:/data printshare:0.1
docker exec printshare printshare status -p cc-thomas
docker exec printshare printshare print "https://www.printables.com/model/3161-3d-benchy" -p cc-thomas --no-start
```

## Next steps (in order)
1. Commit this handover (`CLAUDE.md`, `docs/`, requirements spec) and push to GitHub.
2. Get `docker build` green on Unraid; first real test with `--no-start`, then a real print —
   for both printers (Thomas: SDCP; Dominique: COSMOS).
3. Then work down `docs/ROADMAP.md` (Phase 1 gaps from the spec first).

## Conventions
- Python ≥ 3.10, English code/comments/docs; user-facing texts German first later (NF-11).
- Keep printer and model-source integrations as swappable adapters (NF-08).
- Pin OrcaSlicer version (`ORCA_VERSION` build arg); upgrade only after reference-model tests.
- Never start a print without explicit confirmation from the user (NF-05) — web page currently
  has "Print" and "Upload only"; the app must add a confirmation step.
- Printables: only on the user's behalf, one model at a time, never re-host files.
- Commit trailer used so far: `Co-Authored-By: Claude <noreply@anthropic.com>`.
