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
   replaces start/end with `SET_PRINT_STATS_INFO TOTAL_LAYER=…` + `PRINT_START EXTRUDER=[nozzle_temperature_initial_layer]
   BED=[bed_temperature_initial_layer_single] CHAMBER=[chamber_temperature] TOOL={initial_tool}` / `PRINT_END`,
   and (from Dominique's COSMOS AFC profile, 2026-09-29) the tool change `T[next_extruder] PURGE_LENGTH=[flush_length]`
   instead of Elegoo's CANVAS `M6211`, ramming/parking moves 0, pause `PAUSE`. Dominique's profile used the
   legacy placeholders `[first_layer_temperature]`/`[first_layer_bed_temperature]`; we keep the Orca names.
   Preferred long-term: official COSMOS Orca profile (https://cloud.orcaslicer.com/b/3fad3c38f25f)
   exported as JSON → `machine_file:`. Up to 0.5.0 `machine_preset: cosmos` only swapped start/end (no `TOOL=`,
   Elegoo `M6211`/`M600` left in place, #6); since 0.6.0 it carries the AFC values above, so the built-in preset
   and Dominique's AFC COSMOS preset as `machine_file` (verified on the printer 2026-09-29, see below) give the
   same start/tool-change/pause code.
8. Stock CC upload port is **80**, not 3030 as some docs claim (pycentauri verified live).
   Thomas' CC (192.168.86.144, FW V0.3.0-o) did NOT push Attributes (MainboardID) even when
   idle → adapter now gets it via unicast UDP discovery (`M99999` to host:3000) unless
   `mainboard_id` is set in config. Broadcast discovery doesn't work from bridged containers.
9. Running slicing on the event loop froze the web server → fixed with `asyncio.to_thread`.
10. Relevant Orca preset names: machine `Elegoo Centauri Carbon 0.4 nozzle`,
    process `0.20mm Standard @Elegoo CC 0.4 nozzle`, filament `Elegoo PLA @ECC`.
11. CC1 FW V0.3.0-o acknowledges an SDCP start (Cmd 128, Ack 0) sent right after the upload but
    silently drops it. `elegoo.py` waits until the file is listed (Cmd 258), then checks that the
    printer leaves its resting state and retries once. Resting = IDLE 0, STOPPED 8, COMPLETED 9 — after a
    print the CC stays in COMPLETED, so "not idle" is no proof of a new start (bug seen live 2026-09-28).

## Verified so far (sandbox, 2026-09-26)
- 6/6 tests green (`ORCA_ROOT=/path/to/squashfs-root pytest -q`).
- Live Printables download + slice: Benchy → 34m52s / 11.4 g (COSMOS), 3MF input works.
- API end-to-end against fake Moonraker; web server stays responsive while slicing.
- 2026-09-26 on Unraid (after reboot): container runs; API job Benchy `start:false` → 35m32s / 11.49 g,
  `3dbenchy.gcode` (2.6 MB, 240 layers) arrived on Thomas' CC via SDCP. **NOT yet verified:** a real
  started print (SDCP), anything on COSMOS.

## First real print (reported by Thomas 2026-09-28)
- Thomas printed something on 2026-09-27 and it worked (Centauri Carbon, stock firmware / SDCP).
  Details of the path used (app / web / CLI) not recorded yet.

## First COSMOS print (Dominique, 2026-09-29)
- Centauri Carbon with COSMOS + CANVAS (AFC, 4 lanes), Moonraker `http://192.168.0.95`, Unraid template container
  `PrintShare`. Benchy sliced by PrintShare, **started from the iOS app** (local Xcode dev build, iPhone 14 Pro,
  iOS 27, built from a2614f0 = before 0.5.0): AFC unloaded the lane in the toolhead (T1), loaded T0, print runs
  as intended. No problems seen so far.
- Machine preset: Dominique's Orca user preset *"AFC COSMOS - Elegoo Centauri Carbon 0.4 nozzle - Cosmos AFC"*
  (`inherits: Elegoo Centauri Carbon 0.4 nozzle`, `single_extruder_multi_material = 1`, 4 lanes) as
  `machine_file: "/config/profiles/AFC COSMOS - Elegoo Centauri Carbon 0.4 nozzle - Cosmos AFC.json"`, no
  `machine_preset`. Its start code: `M104 S0` / `M140 S0` / `SET_PRINT_STATS_INFO TOTAL_LAYER=[total_layer_count]` /
  `PRINT_START EXTRUDER=[first_layer_temperature] BED=[first_layer_bed_temperature] CHAMBER=[chamber_temperature]
  TOOL={initial_tool}`; tool change `T[next_extruder] PURGE_LENGTH=[flush_length]` + `; FLUSH_START … ; FLUSH_END`;
  pause `PAUSE`; end `PRINT_END`.
- AFC's `PRINT_START` evaluates `TOOL=`: no separate `T0` needed. Orca only writes `T<n>` after `PRINT_START`
  when several filaments are used; with one filament the lane comes from `TOOL={initial_tool}` alone (always 0 =
  lane 1 until lane selection exists, #6). The CLI slices a 4-lane SEMM preset with a single filament fine.
- Result identical to the system preset: 240 layers, 34m52s, 11.36 g, `0.20mm Standard @Elegoo CC 0.4 nozzle`,
  `Elegoo PLA @ECC`, Textured PEI, 210/60 °C.
- Compared with a G-code from the Orca desktop (same presets, 2 colours): some process/filament values differ
  (flow ratio 1 vs 0.98, fan_min_speed 100 vs 50, gap fill nowhere vs everywhere, inner wall/travel accel …).
  Not a flattening bug: `ProfileLibrary` against the Mac's Orca 2.4.2 bundle gives exactly PrintShare's values;
  the other desktop had different (online-updated) Elegoo system profiles.
- Where Orca keeps user presets: `~/Library/Application Support/OrcaSlicer/user/default/` without login,
  `user/<uuid>/` when logged in to Orca Cloud (then synced; idea for automatic import: #7).
- Manual `machine_file` needs the "managed" mode off: empty *Printer IP address* in the Unraid template,
  otherwise `config.yaml` is regenerated on every start. The CLI (`docker exec … printshare print`) reads
  `config.yaml` on every call; the server only at start → restart the container after editing. Too complex
  for users → #2 (upload button, keep uploaded profile in managed mode).

## iOS dev build findings (2026-09-29)
- iOS 27 SDK: apps crash at launch without the UIScene life cycle
  (`UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption`); the Expo SDK 57 template (≤ 57.0.27) lacks
  it → `mobile/plugins/with-scene-lifecycle.js` (PR #1). Open `ios/PrintShare.xcworkspace`, not the
  `.xcodeproj` ("No such module 'Expo'"); `pod install` needs `LANG=en_US.UTF-8`; after `expo prebuild` set the
  team again for PrintShare + ShareExtension.
- Pairing command: the Unraid template names the container `PrintShare` (docker exec is case-sensitive),
  compose / `docker run` use `printshare` → app + docs show both (PR #1).

## Open issues from this test (GitHub)
#2 profile upload + no manual config mode · #3 camera in the app · #4 G-code preview (2D layer viewer already
in 0.5.0; 3D + live layer open) · #5 printer control (temps, graphs, fans, LED) · #6 AFC lane selection · #7 Orca Cloud profile sync.

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

## Smartphone app — native (decided 2026-09-27)
- Thomas wants a **native app for iOS + Android for public use** (user-friendly). Dominique has the Apple
  developer account. Built with **Expo SDK 57 / React Native** in `mobile/` (expo-router, `src/app/`),
  see `mobile/README.md`. Builds via EAS (`eas build`, `eas submit` → TestFlight); no Mac needed.
  Bundle id `io.github.halvar20000.printshare`, URL scheme `printshare://`.
- Share menu via `expo-share-intent` (iOS share extension + Android intent filters; needs a dev build, not Expo Go).
- Pairing: `docker exec printshare printshare pair --url http://<ip>:8484` shows a QR code
  (`printshare://connect?url=…&token=…`); the app scans it (expo-camera) and stores it in SecureStore.
- Server additions for the app: `GET /api/info`, `POST /api/uploads?name=` (raw body, links as `upload:<id>`,
  never raw paths), status `kind`, start refused with 409 while the printer is busy (DR-03).
- Verified here: tsc, expo lint, expo-doctor, `expo export` for ios/android/web; web build clicked through
  with puppeteer against a mock API. NOT yet run on a real device (needs an EAS dev build).
- Always check the SDK-versioned Expo docs before touching Expo APIs (see `mobile/AGENTS.md`).

## PWA (2026-09-26, kept as browser fallback)
- Thomas first chose a PWA: iPhone + Android, no Apple account, deployable from here.
  App-MVP (spec phase 2) implemented: share/paste link → options → slice → review (time, g, layers,
  changed values) → "plate empty" checkbox → Print / Upload only; jobs list; printer tab with
  pause/resume/cancel. UI checked with headless Chromium (puppeteer-core) at 390×844, light + dark.
- Install/share need HTTPS: `tailscale serve --bg --https=8443 http://127.0.0.1:8484` on the host.
- NOT yet verified on real phones or with real slicing through the new flow (Orca can't run in the
  claude-agent container: its glibc is too old → test slicing only inside the Docker image).

## Distribution (2026-09-27)
- Image `ghcr.io/halvar20000/printshare` (:latest + :<pyproject version>), amd64 + arm64, built by
  `.github/workflows/docker.yml` on native runners (tests first). Dockerfile picks the Orca AppImage by
  `TARGETARCH` and carries `io.hass.*` labels. The GHCR package must be set to **public** once.
- First start (`printshare serve` → `printshare/bootstrap.py`): printer from Unraid env (`PRINTER_*`) or
  HA `/data/options.json` → config.yaml regenerated each start ("managed"); no printer in the form →
  hand-written config.yaml untouched. Token kept/generated; log shows token + pairing QR
  (`PRINTSHARE_URL` / HA `server_url`, HA falls back to the supervisor network info).
- Unraid: `unraid/printshare.xml` (install via templates-user curl). HA: `repository.yaml` +
  `homeassistant/printshare/` (addon_config → /config, /data = add-on data). HA version must equal the
  pyproject version (test enforces it) and bump both for HA to offer an update.
- The HA supervisor reads every `config.{yaml,json}` in the repo as an add-on → example config is
  `config-example.yaml`; `tests/test_bootstrap.py` guards against stray ones.
- Empty env vars never clear the token (Unraid passes unused fields as empty strings).

## Model search (2026-09-27, spec MQ-05/06)
- `printshare/search.py` (adapters `PrintablesSource`, `ThingiverseSource`), API `/api/sources`, `/api/search`,
  `/api/models/{source}/{id}`; app tab `discover.tsx` + `model/[source]/[id].tsx`.
- Printables GraphQL (introspection disabled, found by probing): `searchPrints2(query, limit, offset,
  ordering: best_match|popular|makes_count|rating|latest)` → `totalCount`, `items{…premium price…}`;
  `latest` ignores the query. `print(id)` has `summary description images nozzleDiameters layerHeights
  materials weight printDuration stls`. Paid (`price`) / `premium` models are filtered out.
- Printables images: original can be 6+ MB; thumbnails at
  `<dir>/thumbs/{cover|inside}/{WxH}/<orig ext>/<stem>.jpg` (list 320x240 cover, detail 1280x960 inside).
- Thingiverse verified live 2026-09-28 on Tower (0.3.0, token set, app type "Web App", app URL = GitHub
  repo): search, details (33 images, license, stats), file list, download + slice of a thing file.
  Search hits carry no download count (only the detail call does).
- Tower now runs the Unraid-template container (0.3.0, printer id `centauri-carbon`); its API token is
  in /mnt/user/appdata/printshare/config.yaml, the project-folder config.yaml is stale.

## App releases (2026-09-28)
- EAS project `@halvar20000/printshare` (ID 29ebeeac-4fb7-451c-b335-cdacaf3a8afd, Expo account
  halvar20000). Token for CLI builds: `.expo-token` in the project root (gitignored) →
  `EXPO_TOKEN=$(cat ../.expo-token) npx eas-cli@latest build -p android --profile production --non-interactive`.
- Android upload key generated and stored by EAS (Play App Signing holds the app key). versionCode is
  remote/auto-incremented; first Play build: 0.1.0 (2), `releases/printshare-0.1.0-2.aab` (gitignored).
- Thomas has a Play developer account (3 apps published before). PrintShare 0.1.0 (2) is in
  **Play internal testing** since 2026-09-28. Before public release: privacy policy URL, data safety,
  store listing (DE/EN, screenshots, 1024×500 graphic), and a demo mode or server access for the review.
- iOS not built yet (Dominique's Apple developer account; `eas build -p ios`).

## Home / away addresses (2026-09-28)
- App `Server` has `url` (home) + optional `remoteUrl` (Tailscale). `Api` probes both via `/api/info`
  (4 s, first answer wins), caches per server, re-probes on app foreground (`resetRoutes`) and after a
  network error; only GETs are retried on the other address (never a print start / job creation).
- Pairing link `printshare://connect?url=…&token=…&remote=…`; server env `PRINTSHARE_REMOTE_URL`,
  HA option `remote_url`, CLI `printshare pair --remote-url`. Tested in the web build with an
  unreachable home IP (10.255.255.1): connects via away address in ~2 s.

## PrusaLink + OctoPrint adapters (2026-09-28, 0.4.0)
- `printers/prusalink.py`: PrusaLink v1 (spec: prusa3d/Prusa-Link-Web spec/openapi.yaml). Digest auth user
  `maker` + password from the printer screen (or X-Api-Key on old firmware). Upload `PUT
  /api/v1/files/<storage>/<name>` with `Print-After-Upload: ?1`, `Overwrite: ?1`; storage from
  `/api/v1/storage` (MK4: usb); status `/api/v1/status` + `/api/v1/job`; pause/resume `PUT
  /api/v1/job/<id>/pause|resume`, stop `DELETE /api/v1/job/<id>`. Orca 2.4.2 Prusa presets write plain
  G-code (no binary_gcode) and declare `host_type: prusalink`.
- `printers/octoprint.py`: API key; `POST /api/files/local` multipart select/print; `effectivePrint`
  false → error; `GET /api/job` + `/api/printer` (409 = printer not connected → state offline).
- Adapters normalise states (standby/printing/paused/complete/cancelled/error/attention/offline) for
  `api.printer_kind`. Only tested against fakes (`tests/fakes.py`) – no real Prusa/OctoPrint yet.
- Safety: prusalink/octoprint require an explicit Orca `printer_profile` (never the CC default); missing
  process/filament come from the machine preset's `default_print_profile` / `default_filament_profile`
  (`config._machine_defaults`). Unraid template profile fields now default to empty.

## Leveling switch + G-code preview (2026-09-28, 0.5.0)
- Leveling: `adapter.send(..., leveling=None|bool)`; only `LEVELING_TYPES = ("elegoo_sdcp",)` honour it
  (pycentauri `start_print(auto_leveling=…)` → SDCP `Calibration_switch`). `/api/printers` returns
  `leveling` (default, or null = no switch in the app); `/send` takes `leveling`; CLI `--no-leveling`.
- Preview: `printshare/gcode_preview.py` parses G0-G3 (arcs linearised), G90/91, M82/83, G92, Orca
  `;LAYER_CHANGE`/`;Z:`/`;TYPE:`; output ints in 1/20 mm, collinear points merged (no distance filter –
  it ate corners), prime line attached to layer 1, bounds without `Custom` (start code). Cached as
  `<gcode>.preview.json`; GZip middleware. Synthetic 300-layer 4.5 MB G-code → 0.95 MB JSON in 0.4 s.
  Not yet checked against a real Orca G-code from the CC — do that on Tower after the update.

## Multicolour groundwork (2026-09-29, 0.6.0) – for Dominique's COSMOS + AFC
- `printshare/model_info.py`: colours of 3MF projects – Orca/Bambu `Metadata/project_settings.config`
  (JSON `filament_colour`) + `model_settings.config` (object/part `extruder`), PrusaSlicer
  `Slic3r_PE.config` (quoted `;`-lists, `extruder_colour` wins if set) + `Slic3r_PE_model.config`;
  `paint_color`/`mmu_segmentation` on triangles = painted → all filaments used. `/api/inspect`.
- `pipeline.fetch_model`: download cache `work_dir/cache/<sha1>` (24 h) used by inspect + slicing.
- Orca CLI (source v2.4.2 OrcaSlicer.cpp): `--load-filaments "f1;f2"` replaces the project's filaments
  **by position**; the 3MF's per-object/painted assignments stay. Slicer writes one preset per model
  colour with `filament_colour` = model colour; `JobOptions.filaments` = preset per colour (None = default).
  Orca recognises its 3MFs by `<metadata name="Application">OrcaSlicer-…` (or BambuStudio-…).
- The stock Centauri profile's `change_filament_gcode` is Elegoo's CANVAS `M6211 T…` + `T[next_extruder]`;
  the `cosmos` preset now uses the AFC tool change from Dominique's profile (see finding 7).
  Still open for AFC: lane data from Moonraker (MA-02) and choosing lanes (`SET_MAP`).
- Lane mapping is planned printer-side (AFC `SET_MAP LANE=… MAP=T…`, CANVAS slot_map), not by rewriting G-code.
  pycentauri 0.9.1: CANVAS status/control only for the CC2 protocol; CC1 `slot_map` format undocumented.
- Preview v2: paths `[type, tool, x…]`, `filament_colors` from the G-code footer (`filament_colour`
  before `extruder_colour`); old cached v1 previews are rebuilt. App: colour/line-type switch, outline
  so white filament is visible.
- CI job `integration` runs all tests inside the built amd64 image (real Orca) before tags are set;
  `test_slice_two_colour_3mf_for_centauri` checks T1 + M6211 + grams per colour with the real Orca.

## Real OrcaSlicer inside this claude-agent container (2026-09-29)
- The container's glibc (Debian 12) is too old for Orca, but an Ubuntu 24.04 rootfs + proot works:
  `/tmp/u24` = ubuntu-base 24.04 + the Dockerfile's apt packages (needed `mknod` /dev/null etc. for apt),
  Orca AppImage extracted on the host into `/tmp/u24/opt/orca`, venv `/venv`; `/tmp/proot` (static, from
  proot.gitlab.io) provides /proc (chroot alone fails: Orca needs /proc/self/exe). Run all tests:
  `/tmp/proot -r /tmp/u24 -b /proc -b /dev -b /sys -b <project>:/src -w /src /bin/bash -c
  'ORCA_ROOT=/opt/orca LANG=C.UTF-8 /venv/bin/python -m pytest -q -p no:cacheprovider tests'`.
  /tmp is not persistent – rebuild it when needed (~10 min).
- Orca crashes (SIGSEGV, no output) on hand-written 3MFs that claim to be Orca/Bambu projects
  (`Application` metadata) but lack its project structure; plain 3MFs are fine. Test projects are
  therefore made by Orca itself (`--load-filament-ids 1,2 --slice 1 --export-3mf`), see `_two_colour_3mf`.
- Verified with the real Orca 2.4.2 (75/75 tests): two-colour project → CC stock `T1` + `M6211`,
  COSMOS `T1 PURGE_LENGTH=` without M6211 + `TOOL=0`, grams per colour, preview colours.

## Own printer profile from the app (issue #2, 2026-09-30, 0.7.0)
- `printshare/user_profiles.py`: upload (JSON or zip/.orca_printer bundle, 5 MB), kind detection, check that
  `inherits` resolves in Orca 2.4.2, `print_host`/`printer_agent` stripped, stored as
  `<config dir>/profiles/<kind>-<name>.json`. Assignment per printer in `<config dir>/printers.d/<id>.yaml`
  (`slicing: {machine_file: <file>, machine: <system base>}`), applied by `config.load_settings` on every
  start → survives the regenerated managed `config.yaml`. `Settings.config_dir` = folder of config.yaml.
- `SlicingConfig`: `machine_preset` is dropped when `machine_file` already has `PRINT_START` (Dominique's point).
- API `/api/profiles` (GET/POST/DELETE), `/api/printers/<id>/profile` (GET/PUT); PUT reloads `api.settings`
  (no restart). App: Settings → printer → `printer/[id].tsx` (upload, choose, standard, long-press delete).
- Real Orca test `test_uploaded_afc_cosmos_preset_slices` with Dominique's preset (`tests/data/afc_cosmos_machine.json`,
  host removed): his legacy placeholders `[first_layer_temperature]` expand fine (EXTRUDER=210 … TOOL=0).
- Not yet: choosing uploaded process/filament presets (stored and listed, not offered in the pickers).

## Lane selection for AFC (issue #6, 2026-09-30, 0.8.0)
- AFC (now `AFCProject/AFC-Klipper-Add-On`): `AFC` object lists `lanes`, `current_load`; each lane is its own
  Klipper object (`AFC_stepper lane1`, `AFC_lane …`, prefix varies) with `map` ("T0"), `load`, `prep`,
  `tool_loaded`, `material`, `color`, `filament_name`, `weight`, `status`. `moonraker._lanes()`:
  `/printer/objects/list` → query `AFC` + lane objects → `status.lanes` (`[]` without AFC).
- Lane choice is made on the review screen, after slicing: `/send` takes `lanes {"<model filament>": <tool>}`;
  `printshare/lanes.py` rewrites a copy of the G-code at send time (`T<n>` at line start, `TOOL=<n>`,
  `M6211 … T<n>`; comments/settings dump untouched). The sliced G-code stays as it is (change lanes without
  re-slicing). AFC's own map (`SET_MAP`) is deliberately not touched. Start refused (409) on an empty lane,
  400 if no lane has that tool.
- App: section "Spuren" (default: loaded lane with the profile's material and the closest colour, else T<n-1>),
  red warning + print blocked for an empty lane, yellow for a material mismatch; printers tab shows lane chips.
- Verified with the real Orca: remap on a COSMOS two-colour G-code (TOOL=2, `T3 PURGE_LENGTH=`).
- Real AFC data from Dominique's COSMOS (AFC 1.2.1, recorded 2026-09-30, `tests/data/cosmos_afc_moonraker.json`):
  Moonraker on port 80 (7125 closed); lanes `CANVAS_1`…`CANVAS_4`; each lane exists as `AFC_lane <n>` (has the
  data), `AFC_stepper <n>` and `AFC_canvas_lane <n>`, and the unit is also `AFC_canvas CANVAS_1` → take exactly
  one object per lane (`AFC_lane`, fallback `AFC_stepper`; bug fixed in 0.9.1: 13 entries instead of 4).
  The tool map is not in lane order (CANVAS_1→T3, CANVAS_2→T1, CANVAS_3→T2, CANVAS_4→T0) – always use `map`.
  Empty lane: `material: null`, `color: ""`, `prep/load: false`, `filament_status: "Not Ready"`.

## Camera in the app (issue #3, 2026-09-30, 0.9.0)
- `printshare/camera.py` + `adapter.camera() -> Camera(stream_url, snapshot_url, headers, auth)`:
  CC1 MJPEG `http://<ip>:3031/video` (verified live on Thomas' CC: 640×360 frames ≈30 KB, ~10 fps ≈ 300 KB/s,
  no snapshot URL → first frame SOI…EOI); Moonraker `/server/webcams/list` (first enabled; WebRTC services →
  snapshot only); OctoPrint `/api/settings` webcam (127.0.0.1/localhost URLs rewritten to the Pi's host);
  PrusaLink `/api/v1/cameras` + `/api/v1/cameras/snap` (digest auth).
- API `/api/printers/<id>/camera` (info), `/camera/snapshot?w=` (Pillow scaling, `no-store`),
  `/camera/stream` (MJPEG passthrough via StreamingResponse; `?token=` for image views without headers).
- App: `components/camera.tsx` (two image slots take turns → no flicker, one download per frame, only while
  focused), printers tab thumbnail (5 s), `camera/[id].tsx` fullscreen Live (WebView `<img>` MJPEG) / Still;
  away (route "remote") defaults to still images. `react-native-webview` added (native → new app build).

## Printer control (issue #5, 2026-09-30, 0.10.0)
- Adapters: `controls()` → `{"heaters": [{id, max}], "fans": [{id}], "lights": [{id}], "speed": {"modes"} |
  {"min","max"} | null, "history": bool}`, `adjust(kind, id, value)`, status adds `heaters` {id:{actual,target}},
  `fans` {id: %}, `lights` {id: bool}, `speed` (%).
- CC1 (SDCP Cmd 403 via pycentauri, `enable_control=True`): TempTargetNozzle/Hotbed/Box, TargetFanSpeed
  ModelFan/AuxiliaryFan/BoxFan, LightStatus.SecondLight, PrintSpeedPct modes 50/100/130/160 (Silent/Normal/
  Sport/Ludicrous). Status read live on Thomas' CC; **setting values not yet tried on the real printer.**
- Moonraker: objects discovered (`extruder`, `heater_bed`, `heater_generic *chamber*` or a chamber
  `temperature_sensor` = display only, `fan` via M106/M107 (PWM `int(pct*255/100+0.5)`), `fan_generic` via
  SET_FAN_SPEED, `led/neopixel/dotstar` via SET_LED, M220), max temps from `configfile.settings`, history from
  `/server/temperature_store`. Dominique's COSMOS objects: fan, fan_generic aux_fan/case_fan, led case/hotend,
  temperature_sensor chamber. OctoPrint: tool/bed/command endpoints, `?history=true`. PrusaLink: read only.
- API: `/api/printers/<id>/controls|adjust|temperatures`; adjust validates against controls; heater changes
  and fan → 0 while printing need `confirm: true` (else 409). No printer history → server logs status temps
  (`TEMP_LOG`, 30 min, polled by the app every 3 s while the screen is open).
- App: `control/[id].tsx` (button "Steuerung" on the printers tab), `components/tempchart.tsx` (react-native-svg);
  confirms during a print and for high targets (nozzle ≥ 260, bed ≥ 100). Pure JS → no new native build needed
  beyond the regular release.

## Next steps (in order)
1. Native app: iOS dev build runs on Dominique's iPhone and started a real COSMOS print (2026-09-29).
   Still open: EAS/TestFlight build for iOS (needs PR #1), share → slice flow on Thomas' phones.
2. After the reboot: rerun `scripts/unraid-install.sh cc-thomas`; check that the parity check and the
   hetzner-cls backup ran; then `printshare print <benchy> -p cc-thomas --no-start`, then a real
   print — for both printers (Thomas: SDCP ✅ 2026-09-27; Dominique: COSMOS ✅ 2026-09-29).
3. Then work down `docs/ROADMAP.md` (Phase 1 gaps from the spec first).

## Conventions
- Python ≥ 3.10, English code/comments/docs; user-facing texts German first later (NF-11).
- Keep printer and model-source integrations as swappable adapters (NF-08).
- Pin OrcaSlicer version (`ORCA_VERSION` build arg); upgrade only after reference-model tests.
- Never start a print without explicit confirmation from the user (NF-05) — web page currently
  has "Print" and "Upload only"; the app must add a confirmation step.
- Printables: only on the user's behalf, one model at a time, never re-host files.
- Commit trailer used so far: `Co-Authored-By: Claude <noreply@anthropic.com>`.
