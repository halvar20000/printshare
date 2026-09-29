# Roadmap — status vs. requirements spec

Spec: `../Mobile Print-App – Softwareanforderungen.md` (Dominique, 2026-09-26, IDs below refer to it).
Legend: ✅ done in P0 · 🟡 partial · ⬜ open

## Open decisions (need Thomas/Dominique)
| Topic | Options | Notes |
|---|---|---|
| App technology | **Decided 2026-09-27: native app with Expo/React Native** (`mobile/`, iOS + Android, for public use), built with EAS on Dominique's Apple developer account. The PWA stays as a browser fallback. | Share extension (iOS) + share intent (Android) via `expo-share-intent`. |
| Slice service | keep own `slicer.py` vs. base on AFKFelix/orca-slicer-api or escalopa/orcaslicer-api (spec) | Own implementation already works incl. preset flattening + COSMOS preset; switching only pays off if those projects handle arrange/thumbnails/multi-plate better. |
| Profile source | Orca desktop user presets (PR-01) vs. bundled system presets (current) | Current P0 uses bundled system presets + overrides; PR-01/02/03 needs user-preset import with `inherits` resolution (`profiles.load_user_preset` exists). |
| App name | "PrintShare" is the working name | — |

## Phase 1 – Server MVP (spec: "URL in → print starts")
| ID | Item | Status |
|---|---|---|
| MQ-01 | Printables link → server downloads files | ✅ (GraphQL; share sheet via iOS Shortcut + web page) |
| MQ-02 | Choose among several files | 🟡 app asks which file (3MF preselected); no previews, no "all files" |
| MQ-03 | Local files STL/3MF/OBJ/STEP | ✅ `POST /api/uploads` + native app (Files app, share menu) |
| MQ-04 | Print prepared 3MF / ready G-code | 🟡 3MF slices (own profile); pre-sliced G-code passthrough ⬜ |
| MQ-09 | Thingiverse | ✅ (needs app token) |
| MQ-05 | Search in the app | ✅ Printables (`searchPrints2`, live-tested) + Thingiverse (REST `/search`, needs token; live-tested 2026-09-28) — app tab *Entdecken*, sort relevance/popular/most made; paid/premium Printables models hidden |
| MQ-06 | Model details | ✅ images, author, license, stats, description, author's recommended settings (Printables), printable file count → *Drucken vorbereiten* |
| MQ-10 | Store license/author with the job | 🟡 shown on the detail page; not yet stored in the job history |
| DV-01 | Several printers | ✅ config list; online status in the app (status `kind`) |
| DV-02 | Nozzle per printer/job | 🟡 via preset names in config; per-job ⬜ |
| DV-03 | Build plate | ✅ per printer + per job (app) |
| MA-01 | Filament profile | ✅ per job from compatible Orca presets (app) |
| QU-01 | Quality as process profile | ✅ per job from compatible presets (app) |
| QU-03/04, SU-01/02/05 | walls, infill, supports, brim | ✅ per job (`JobOptions`); supports off/normal/tree, brim auto/off/outer |
| PL-02 | Auto-orient | 🟡 `auto_orient` config flag; Orca `--orient` |
| PL-04 | Arrange / copies | 🟡 `--arrange 1` always on; copies ⬜ |
| SL-01 | Async slicing + progress | 🟡 async job + step log in the app; cancel ⬜ |
| SL-02 | Summary time/filament | 🟡 time + g + m + layers; per-lane, thumbnail ⬜ |
| SL-04 | Understandable slice errors | 🟡 app maps server errors to plain German/English + technical details; Orca-specific causes (out of build volume …) ⬜ |
| DR-01 | Printer setup | ✅ config.yaml |
| DR-02 | Moonraker upload + start | ✅ real print on COSMOS + CANVAS/AFC started from the iOS app (2026-09-29); WebSocket status ⬜ (polling) |
| DR-04 | Live status | 🟡 snapshot status endpoint |
| DR-05 | Pause/resume/cancel | ✅ API + app (cancel asks); untested on real printers |
| DR-11 | SDCP adapter | ✅ (tested against fake + real CC1) |
| DO-01 | Bed leveling on/off per print | 🟡 Centauri Carbon stock (SDCP `Calibration_switch`), remembered per printer in the app; COSMOS/Klipper, Prusa, OctoPrint do it in their start G-code ⬜ |
| SL-06/07 | G-code layer viewer | ✅ server turns G-code into compact layer data (`/api/jobs/<id>/preview`, cached, gzip); app: top view per layer, line-type colours + legend toggles, previous layer faint, slider, model/plate view. 3D view ⬜ |
| SL-10 | Export G-code | 🟡 `/api/jobs/<id>/gcode`; share button in the app ⬜ |
| NF-08 | More printers | 🟡 PrusaLink + OctoPrint adapters (tested against fakes from the official APIs, 2026-09-28); quality/filament default from the Orca machine preset; Bambu LAN, Flashforge, Creality stock ⬜ |
| PR-03 | Resolve `inherits` | ✅ for system presets and user presets via `machine_file` (AFC COSMOS preset, 2026-09-29) |
| BE-01 | Queue, 1 slice at a time | ✅ `max_parallel_slices` (default 1) |
| BE-07 | Docker image + Unraid template | 🟡 GHCR multi-arch image (GitHub Actions), Unraid template `unraid/printshare.xml`, Home Assistant add-on `homeassistant/printshare`; listing in Community Applications ⬜ (needs a separate templates repo) |
| NF-03/04 | VPN only, token | 🟡 single global token; per-device tokens ⬜ |
| NF-05 | No start without confirmation | ✅ review screen + "plate empty" checkbox; API requires `confirm` |

## Phase 2 – App MVP (native app `mobile/`, 2026-09-27; PWA 2026-09-26)
| ID | Item | Status |
|---|---|---|
| SL-03 | Show profiles used + changed values | ✅ review screen |
| SL-05 | Change settings and re-slice | ✅ "Change settings" keeps link + choices |
| DR-03 | Check before start (plate empty, material) | ✅ switch + confirm dialog; server refuses start on a busy printer (409); lane material check ⬜ (needs AFC) |
| DV-04 | Warn on odd combinations | 🟡 app: PLA/Engineering, PETG/smooth PEI, Cool Plate non-PLA, CF/GF nozzle hint; build-volume check ⬜ |
| NF-04 | Token in Keychain | ✅ SecureStore (Keychain/Keystore); pairing QR via `printshare pair` |
| NF-10 | Distribution | EAS build → TestFlight (iOS, Dominique's account) / APK (Android) |
| NF-11 | German first, English prepared | ✅ app texts (server error texts still English) |
| NF-12 | Link → print in ≤ 5 steps | ✅ share → Slice → tick → Print |

## Suggested next tasks (P1)
1. Real-printer tests (both), fix what breaks. Add `mainboard_id` (UDP discovery on port 3000) for SDCP.
2. Persistent storage: SQLite for jobs/history (DR-09, MQ-07), G-code cleanup (BE-05).
3. Slice queue with concurrency 1 (BE-01), cancel (SL-01).
4. Per-job overrides in API: nozzle, plate, filament, process, supports, brim, walls, infill (section 4).
5. Pre-sliced G-code / gcode.3mf passthrough (MQ-04); file upload endpoint (MQ-03).
6. Printer control endpoints pause/resume/cancel (DR-05); Moonraker WebSocket status (DR-02/04).
7. Thumbnails: run Orca under Xvfb + Mesa (llvmpipe) or render our own preview (SL-02).
8. User-preset import (PR-01/02): upload in the app (#2) and/or Orca Cloud sync (#7). `machine_file` works today (manual config).
9. COSMOS: AFC lane selection + lane data from Moonraker (MA-02, #6). `PRINT_START … TOOL={initial_tool}` loads the lane (verified 2026-09-29).
10. ntfy / Home Assistant notifications (BE-06, DR-12).
11. Printer camera in the app (#3); G-code preview (#4): layer viewer done in 0.5.0, open: 3D view, current
    layer while printing; printer control: temperatures + graphs, fans, LED (#5).
