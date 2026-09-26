# Roadmap — status vs. requirements spec

Spec: `../Mobile Print-App – Softwareanforderungen.md` (Dominique, 2026-09-26, IDs below refer to it).
Legend: ✅ done in P0 · 🟡 partial · ⬜ open

## Open decisions (need Thomas/Dominique)
| Topic | Options | Notes |
|---|---|---|
| App technology | SwiftUI native (spec) vs. React Native/Expo (earlier Cowork recommendation) | Spec targets iOS only; Thomas also uses Android (S24 Ultra). Share Extension without paid Apple account is limited (NF-10). |
| Slice service | keep own `slicer.py` vs. base on AFKFelix/orca-slicer-api or escalopa/orcaslicer-api (spec) | Own implementation already works incl. preset flattening + COSMOS preset; switching only pays off if those projects handle arrange/thumbnails/multi-plate better. |
| Profile source | Orca desktop user presets (PR-01) vs. bundled system presets (current) | Current P0 uses bundled system presets + overrides; PR-01/02/03 needs user-preset import with `inherits` resolution (`profiles.load_user_preset` exists). |
| App name | "PrintShare" is the working name | — |

## Phase 1 – Server MVP (spec: "URL in → print starts")
| ID | Item | Status |
|---|---|---|
| MQ-01 | Printables link → server downloads files | ✅ (GraphQL; share sheet via iOS Shortcut + web page) |
| MQ-02 | Choose among several files | 🟡 by index/name (CLI, web "Check files"); no previews, no "all files" |
| MQ-03 | Local files STL/3MF/OBJ/STEP | 🟡 CLI local path + direct URL; no upload endpoint yet |
| MQ-04 | Print prepared 3MF / ready G-code | 🟡 3MF slices (own profile); pre-sliced G-code passthrough ⬜ |
| MQ-09 | Thingiverse | ✅ (needs app token) |
| DV-01 | Several printers | ✅ config list; online status ⬜ |
| DV-02 | Nozzle per printer/job | 🟡 via preset names in config; per-job ⬜ |
| DV-03 | Build plate | ✅ `bed_type` per printer; per-job ⬜ |
| MA-01 | Filament profile | 🟡 per printer in config; per-job ⬜ |
| QU-01 | Quality as process profile | 🟡 per printer in config |
| QU-03/04, SU-01/02/05 | walls, infill, supports, brim | ⬜ (add `process_overrides` per job — mechanism exists) |
| PL-02 | Auto-orient | 🟡 `auto_orient` config flag; Orca `--orient` |
| PL-04 | Arrange / copies | 🟡 `--arrange 1` always on; copies ⬜ |
| SL-01 | Async slicing + progress | 🟡 async job + text log; cancel ⬜ |
| SL-02 | Summary time/filament | 🟡 time + g + m; per-lane, layers, thumbnail ⬜ |
| SL-04 | Understandable slice errors | 🟡 last 25 Orca log lines |
| DR-01 | Printer setup | ✅ config.yaml |
| DR-02 | Moonraker upload + start | ✅ (tested against fake) ; WebSocket status ⬜ (polling) |
| DR-04 | Live status | 🟡 snapshot status endpoint |
| DR-05 | Pause/resume/cancel | ⬜ (pycentauri + Moonraker both support it) |
| DR-11 | SDCP adapter | ✅ (tested against fake) |
| PR-03 | Resolve `inherits` | ✅ for system presets |
| BE-01 | Queue, 1 slice at a time | ⬜ (currently unlimited parallel jobs) |
| BE-07 | Docker image + Unraid template | 🟡 Dockerfile + compose; CA template ⬜ |
| NF-03/04 | VPN only, token | 🟡 single global token; per-device tokens ⬜ |
| NF-05 | No start without confirmation | 🟡 explicit button; confirmation screen ⬜ |

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
