# Roadmap — status vs. requirements spec

Spec: `../Mobile Print-App – Softwareanforderungen.md` (Dominique, 2026-09-26, IDs below refer to it).
Legend: ✅ done in P0 · 🟡 partial · ⬜ open

## Open decisions (need Thomas/Dominique)
| Topic | Options | Notes |
|---|---|---|
| App technology | **Decided 2026-09-26: PWA** served by the container (iPhone + Android, no Apple account). Native shell (SwiftUI/Expo) can come later on the same API. | Android share via Web Share Target (needs HTTPS → Tailscale Serve); iPhone share via Shortcut. |
| Slice service | keep own `slicer.py` vs. base on AFKFelix/orca-slicer-api or escalopa/orcaslicer-api (spec) | Own implementation already works incl. preset flattening + COSMOS preset; switching only pays off if those projects handle arrange/thumbnails/multi-plate better. |
| Profile source | Orca desktop user presets (PR-01) vs. bundled system presets (current) | Current P0 uses bundled system presets + overrides; PR-01/02/03 needs user-preset import with `inherits` resolution (`profiles.load_user_preset` exists). |
| App name | "PrintShare" is the working name | — |

## Phase 1 – Server MVP (spec: "URL in → print starts")
| ID | Item | Status |
|---|---|---|
| MQ-01 | Printables link → server downloads files | ✅ (GraphQL; share sheet via iOS Shortcut + web page) |
| MQ-02 | Choose among several files | 🟡 app asks which file (3MF preselected); no previews, no "all files" |
| MQ-03 | Local files STL/3MF/OBJ/STEP | 🟡 CLI local path + direct URL; no upload endpoint yet |
| MQ-04 | Print prepared 3MF / ready G-code | 🟡 3MF slices (own profile); pre-sliced G-code passthrough ⬜ |
| MQ-09 | Thingiverse | ✅ (needs app token) |
| DV-01 | Several printers | ✅ config list; online status ⬜ |
| DV-02 | Nozzle per printer/job | 🟡 via preset names in config; per-job ⬜ |
| DV-03 | Build plate | ✅ per printer + per job (app) |
| MA-01 | Filament profile | ✅ per job from compatible Orca presets (app) |
| QU-01 | Quality as process profile | ✅ per job from compatible presets (app) |
| QU-03/04, SU-01/02/05 | walls, infill, supports, brim | ✅ per job (`JobOptions`); supports off/normal/tree, brim auto/off/outer |
| PL-02 | Auto-orient | 🟡 `auto_orient` config flag; Orca `--orient` |
| PL-04 | Arrange / copies | 🟡 `--arrange 1` always on; copies ⬜ |
| SL-01 | Async slicing + progress | 🟡 async job + step log in the app; cancel ⬜ |
| SL-02 | Summary time/filament | 🟡 time + g + m + layers; per-lane, thumbnail ⬜ |
| SL-04 | Understandable slice errors | 🟡 last 25 Orca log lines |
| DR-01 | Printer setup | ✅ config.yaml |
| DR-02 | Moonraker upload + start | ✅ (tested against fake) ; WebSocket status ⬜ (polling) |
| DR-04 | Live status | 🟡 snapshot status endpoint |
| DR-05 | Pause/resume/cancel | ✅ API + app (cancel asks); untested on real printers |
| DR-11 | SDCP adapter | ✅ (tested against fake) |
| PR-03 | Resolve `inherits` | ✅ for system presets |
| BE-01 | Queue, 1 slice at a time | ✅ `max_parallel_slices` (default 1) |
| BE-07 | Docker image + Unraid template | 🟡 Dockerfile + compose; CA template ⬜ |
| NF-03/04 | VPN only, token | 🟡 single global token; per-device tokens ⬜ |
| NF-05 | No start without confirmation | ✅ review screen + "plate empty" checkbox; API requires `confirm` |

## Phase 2 – App MVP (PWA, 2026-09-26)
| ID | Item | Status |
|---|---|---|
| SL-03 | Show profiles used + changed values | ✅ review screen |
| SL-05 | Change settings and re-slice | ✅ "Change settings" keeps link + choices |
| DR-03 | Check before start (plate empty, material) | 🟡 checkbox; printer-ready check ⬜ |
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
8. User-preset import from Mac Orca folder (PR-01/02) — e.g. Syncthing to `/config/profiles`.
9. COSMOS: read AFC lane data from Moonraker (MA-02) — open question in spec.
10. ntfy / Home Assistant notifications (BE-06, DR-12).
