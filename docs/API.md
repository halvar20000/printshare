# PocketPrint3D server API

The contract between the PocketPrint3D server and its apps: the **iOS app (Swift, Dominique)**, the **Android app
(Expo, `mobile/`)** and the **web page** (`printshare/web/`). Server version described here: **0.13.1**.

The examples were recorded from the server with the real OrcaSlicer 2.4.2 and simulated printers
(`tests/fakes.py`), shortened with `…`; the search examples are illustrative (they need the internet). Ids, times
and values differ on your server.

## Basics

| | |
|---|---|
| Base URL | `http://<server>:8484` at home, optionally a second address away from home (Tailscale etc.) |
| Format | JSON (UTF-8), except uploads (raw body), camera images and G-code |
| Auth | every `/api/...` call: `Authorization: Bearer <token>`; `?token=<token>` also works (for image/stream views that can't send headers) |
| Errors | HTTP status + `{"detail": "<message in English>"}` |
| Compression | responses ≥ 2 kB are gzipped when the client sends `Accept-Encoding: gzip` |

```http
GET /api/info
→ 200 {"name": "PrintShare", "version": "0.13.1", "printers": 2}      (the name stays "PrintShare" – technical id)

GET /api/info            (no or wrong token)
→ 401 {"detail": "invalid token"}
```

**Status codes the apps should handle:** `400` wrong input (message says what), `401` token, `404` unknown
printer/job/file, `409` not allowed right now (printer busy, print running, empty slot, job still running),
`413` file too large, `502` printer / Home Assistant / Printables not reachable. Messages are English; the apps
map the common ones to their own texts (see `friendlyError` in `mobile/src/lib/api.ts`).

### Rules for changes (both apps depend on them)
- **Additive only:** new fields and endpoints may appear at any time – apps must ignore unknown fields.
- A field is never removed or changes meaning in a minor version. Where a format has to change, the app asks
  for the new one explicitly (example: `/preview?format=2`), old apps keep getting the old one.
- `/api/info` → `version` (the pyproject version) tells an app what the server can do.
- Every new endpoint is added to this file in the same pull request.

## Connecting the app (pairing)

The server shows a QR code (web page → Settings → "App verbinden", `printshare pair` on the command line, or the
container log). It contains a link:

```
printshare://connect?url=http%3A%2F%2F192.168.1.10%3A8484&token=<token>[&remote=https%3A%2F%2Ftower.x.ts.net%3A8443]
```

- `url` home address, `token` API token, `remote` optional away address.
- The app stores them securely (Keychain) and tries both addresses with `GET /api/info` (4 s timeout, first
  answer wins). Only **GET** requests are retried on the other address, never a print start or job creation.

```http
GET /api/pairing?url=http://192.168.1.10:8484[&remote=…]
→ 200 {"link": "printshare://connect?url=…&token=…", "svg": "<svg viewBox=…>…</svg>",
       "url": "http://192.168.1.10:8484", "remote_url": "", "token": "…",
       "configured": false, "warnings": []}
```
`warnings`: `"localhost"` (address points to the server itself), `"ingress"` (opened through Home Assistant).

## Typical flow

```
GET  /api/printers                          choose printer
GET  /api/printers/{id}/status              online? busy? lanes (AFC slots)
(GET /api/search, /api/models/{source}/{id}  or a shared link, or POST /api/uploads for a file)
GET  /api/files?link=…                      files of the model → pick one if several
GET  /api/inspect?link=…&file=…             colours of a 3MF → material/slot per colour
GET  /api/printers/{id}/options             materials, qualities, plates, defaults
POST /api/jobs                              download + slice (no printer contact)
GET  /api/jobs/{job}                        poll every ~1 s until state != "slicing"
GET  /api/jobs/{job}/preview?format=2       layer viewer (optional)
POST /api/jobs/{job}/send                   after the user confirmed: upload (+ start)
GET  /api/jobs/{job}                        poll until state != "sending"
GET  /api/printers/{id}/status              progress
```

**Safety rules the server enforces** (the apps must show a confirmation before they send `confirm: true`):
starting a print (`/send` with `start: true`), cancelling (`/control` cancel), changing a temperature or switching
a fan off while printing (`/adjust`), switching the power off (refused while printing, no override).

## Printers

### `GET /api/printers`
```json
[{"id": "centauri", "name": "Centauri Carbon", "type": "elegoo_sdcp",
  "machine": "Elegoo Centauri Carbon 0.4 nozzle", "leveling": true, "power": false},
 {"id": "cosmos", "name": "COSMOS + CANVAS", "type": "moonraker",
  "machine": "Elegoo Centauri Carbon 0.4 nozzle", "leveling": null, "power": false}]
```
- `type`: `elegoo_sdcp` (Centauri Carbon stock firmware), `moonraker` (Klipper, e.g. COSMOS), `prusalink`, `octoprint`.
- `leveling`: `null` = no per-print bed-leveling switch; `true/false` = the printer's default (show a switch).
- `power`: a smart plug is set up → offer "switch on" while the printer is offline.

### `GET /api/printers/{id}/status`
Live state; call every 3–10 s while visible. `502` = printer not reachable (off / not on the network).

```json
{"state": "printing", "kind": "active", "file": "cube.gcode", "progress": 3.1, "layer": 3, "layers": 100,
 "print_duration_s": 60, "time_remaining_s": null,
 "nozzle": 210.1, "nozzle_target": 210, "bed": 60.0, "bed_target": 60,
 "camera": "http://127.0.0.1:7125/webcam/?action=stream",
 "lanes": [{"id": "CANVAS_1", "tool": 3, "unit": "CANVAS_1", "material": "PLA", "color": "#FFFFFF",
            "filament": "Elegoo PLA White", "weight_g": 988, "loaded": true, "in_toolhead": false, "status": "Ready"}],
 "heaters": {"nozzle": {"actual": 210.1, "target": 210}, "bed": {"actual": 60.0, "target": 60},
             "chamber": {"actual": 31.5, "target": null}},
 "fans": {"part": 50, "aux_fan": 0}, "lights": {"case": true}, "speed": 100}
```
- **`kind`** (use this, not `state`): `idle`, `active`, `paused`, `done`, `stopped`, `error`, `unknown`.
  `state` is the printer's own word (`printing`, `standby`, `heating`, …) for extra detail.
- `progress` 0–100; `time_remaining_s` only where the printer reports it (PrusaLink, OctoPrint), else estimate
  from `print_duration_s` and `progress`.
- `lanes` (AFC units such as CANVAS on COSMOS, else `[]`): `tool` is the T-number the G-code uses; **the order is
  not the physical order** – show slots sorted by the number at the end of `id` ("Slot 1–4"), see
  `mobile/src/lib/lanes.ts`. Empty lane: `loaded: false`, `material: null`, `color: null`.
- `heaters` with `target: null` = sensor only (e.g. a chamber thermometer). `fans` in %, `lights` on/off,
  `speed` in % (Centauri: one of its modes 50/100/130/160).
- `camera`: the printer's own URL – **apps use `/camera/...` below instead** (works away from home).
- Other fields may exist (e.g. `raw` for the Centauri); ignore them.

### `GET /api/printers/{id}/options[?process=<quality>]`
Everything for the preparation screen. `?process=` returns the defaults of that quality (supports, brim, infill, walls).

```json
{"printer": "cosmos",
 "materials": ["Meine PLA", "Elegoo ABS @ECC", "Elegoo PLA @ECC", "…"],
 "processes": ["Mein Standard", "0.12mm Fine @Elegoo CC 0.4 nozzle", "0.20mm Standard @Elegoo CC 0.4 nozzle", "…"],
 "own": {"materials": ["Meine PLA"], "processes": ["Mein Standard"]},
 "plates": ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"],
 "supports": ["off", "normal", "tree"], "brims": ["auto", "off", "outer"],
 "defaults": {"filament": "Elegoo PLA @ECC", "process": "0.20mm Standard @Elegoo CC 0.4 nozzle",
              "bed_type": "Textured PEI Plate", "supports": "off", "brim": "auto", "infill": 15, "walls": 2,
              "layer_height": "0.2"}}
```
- Names are OrcaSlicer preset names; show them shortened (text before ` @`).
- `own`: uploaded presets of the user (shown first, group "Own profiles").

### Printer control – `POST /api/printers/{id}/control`
```json
{"action": "pause" | "resume" | "cancel", "confirm": true}
→ 200 {"ok": true, "action": "pause"}
→ 400 {"detail": "cancelling a print needs confirm=true"}
```

### Temperatures, fans, light, speed
`GET /api/printers/{id}/controls` – what the printer can do:
```json
{"heaters": [{"id": "nozzle", "max": 300}, {"id": "bed", "max": 110}, {"id": "chamber", "max": 60}],
 "fans": [{"id": "part"}, {"id": "aux"}, {"id": "chamber"}], "lights": [{"id": "light"}],
 "speed": {"modes": [50, 100, 130, 160]}, "history": false}
```
(Klipper: `"speed": {"min": 10, "max": 300}`, fans like `aux_fan`/`case_fan`, lights like `case`/`hotend`.
PrusaLink: all empty, `speed: null`.)

`POST /api/printers/{id}/adjust`
```json
{"kind": "heater" | "fan" | "light" | "speed", "id": "nozzle", "value": 210, "confirm": false}
→ 200 {"ok": true}
→ 400 {"detail": "nozzle target must be 0-320 °C"}
→ 409 {"detail": "a print is running - confirm this change (confirm=true)"}
```
`value`: °C (0 = off) for heaters, 0–100 % for fans, `true/false` for lights, % (or a mode) for speed.
While printing, heater changes and switching a fan to 0 need `confirm: true` → ask the user first, then resend.

`GET /api/printers/{id}/temperatures` – history for a chart:
```json
{"series": {"nozzle": [[-1190, 21.4, 200.0], [-1180, 22.9, 200.0], "…"],
            "chamber": [[-1190, 25.0, null], "…"]},
 "source": "printer"}
```
Entries `[seconds before now, actual, target|null]`. `source: "printshare"` = the printer keeps no history
(Centauri); the server records what it sees while the app polls `/status` (30 min).

### Camera
| | |
|---|---|
| `GET /api/printers/{id}/camera` | `{"available": true, "stream": true, "snapshot": true, "name": "cam"}` (`available: false` = none) |
| `GET /api/printers/{id}/camera/snapshot?w=640` | JPEG, optionally scaled to width `w` (160–1920) |
| `GET /api/printers/{id}/camera/stream?token=…` | live MJPEG (`multipart/x-mixed-replace`), passed through the server |

Live ≈ 300 KB/s: use still images away from home. Centauri: 640×360 MJPEG; Klipper: the first webcam in Moonraker.

### Power (smart plug through Home Assistant)
| | |
|---|---|
| `GET /api/printers/{id}/power` | `{"available": false, "state": null}` or `{"available": true, "state": "on"\|"off"\|"unavailable"\|"unknown", "error": null}` |
| `POST /api/printers/{id}/power` `{"on": true}` | `{"ok": true, "state": "on"}`; off while printing → `409`; plug/HA problem → `502` |

After switching on, the printer needs ~30–60 s until `/status` answers. The settings (`/power/config`, `/power/test`,
`/power/entities`) are made on the web page; the token is never returned (`token_set: true/false`).

### Printer profile
`GET /api/printers/{id}/profile` → `{"machine": "Elegoo Centauri Carbon 0.4 nozzle", "machine_file": null,
"config_file": null, "machine_preset": "cosmos"}`; `PUT` the same path with `{"machine_file": "<file>" | null}`
assigns an uploaded printer preset (null = standard).

## Models

### Search – `GET /api/sources`, `GET /api/search`, `GET /api/models/{source}/{id}`
```http
GET /api/sources
→ [{"id": "printables", "name": "Printables", "available": true},
   {"id": "thingiverse", "name": "Thingiverse", "available": true}]      (Thingiverse only with a token)

GET /api/search?q=benchy&source=printables&page=1&sort=relevant|popular|makes
→ {"results": [{"source": "printables", "id": "3161", "name": "3DBenchy", "url": "https://www.printables.com/model/3161-3dbenchy",
                "author": "CreativeTools", "thumbnail": "https://…/thumbs/cover/320x240/…jpg",
                "likes": 12000, "downloads": 300000, "makes": 5000, "license": "…"}, …],
   "total": 1234, "page": 1, "has_more": true}
```
24 hits per page; `null` for values a source doesn't know. Paid/premium Printables models are left out.

`GET /api/models/printables/3161` – everything of the search hit plus
`images` (URLs), `summary`, `description` (plain text), `category`, `recommended` (author's settings, Printables
only, missing keys left out: `{"nozzle": "0.4 mm", "layer_height": "0.2 mm", "material": "PLA", "weight_g": 12.5,
"print_hours": 1.5}`) and `files` (`[{"name": "3DBenchy.stl", "size": 11285384, "sliceable": true}, …]`).
The **link** for the next steps is the hit's `url`.

### Link or uploaded file
A model is always identified by a **link**: an `http(s)` URL (Printables, Thingiverse, direct file) or an uploaded file.

```http
POST /api/uploads?name=cube.stl            body: raw file (max 300 MB; .stl .3mf .obj .step .stp)
→ 200 {"id": "ec1563762709", "link": "upload:ec1563762709", "name": "cube.stl", "size": 684}

GET /api/files?link=upload:ec1563762709
→ 200 [{"index": 1, "name": "cube.stl", "size": null}]
```
Several files → let the user choose, pass `file=<index>` (as a string) in the next calls.

`GET /api/inspect?link=…&file=…` – colours of a 3MF project (downloads the model, cached for a day):
```json
{"file": "flag.3mf", "painted": false, "source": "orca", "used": [1, 2],
 "filaments": [{"index": 1, "color": "#E53935", "type": "PLA", "name": null},
               {"index": 2, "color": "#FFFFFF", "type": "PLA", "name": null}]}
```
(STL: `"filaments": []`.) More than one entry in `used` → multicolour: one material (and on AFC printers one slot)
per colour.

`GET /api/model-file?link=…&file=…` – the model file itself (for a 3D view before slicing), from the same cache.

## Jobs: slice → review → send

### `POST /api/jobs` – download + slice (no printer contact)
```json
{"link": "upload:ec1563762709", "printer": "cosmos", "file": null,
 "options": {"filament": "Elegoo PLA @ECC", "process": null, "bed_type": null,
             "supports": "off", "brim": null, "infill": 20, "walls": null,
             "filaments": null}}
→ 200 {"job": "843289d5b2"}
```
`null` / missing = the printer's default. `filaments`: multicolour, one preset per model filament (by index,
`null` = default). `400` if a material/quality doesn't fit the printer.

### `GET /api/jobs/{job}`
```json
{"id": "843289d5b2", "kind": "prepare", "state": "sliced",
 "log": ["Looking up model files", "Slicing for COSMOS + CANVAS", "Sliced: 8m 49s / 3.94 g"],
 "result": {"printer": "cosmos", "source_file": "cube.stl", "gcode": "/data/gcode/cosmos/843289d5b2/cube.gcode",
            "print_time": "8m 49s", "filament_g": 3.94, "filament_m": 1.31, "layers": 100,
            "profiles": {"machine": "Elegoo Centauri Carbon 0.4 nozzle", "process": "0.20mm Standard @Elegoo CC 0.4 nozzle",
                         "filament": "Elegoo PLA @ECC", "bed_type": "Textured PEI Plate"},
            "overrides": {"enable_support": "0", "sparse_infill_density": "20%"},
            "sent": {}, "filaments": []},
 "error": null, "created": 1790778079.45, "request": {"link": "…", "printer": "cosmos", "file": null, "options": {…}}}
```
- **`state`**: `slicing` → `sliced` | `error`; after `/send`: `sending` → `uploaded` | `started`
  (a failed send goes back to `sliced` with `error` set, so the user can try again).
- `log`: progress lines (English; the apps translate the known ones).
- `result.filaments` (multicolour): `[{"index", "color", "preset", "grams"}]`.
- `result.overrides`: values that differ from the profile, to show as "changed values".
- `result.sent` after sending: `{"uploaded": "cube.gcode", "started": false, "tools": {"0": 0}}`.

`GET /api/jobs` – recent jobs (newest first, in memory, max. 50):
`[{"id", "kind", "state", "error", "created", "printer", "link", "file", "print_time", "filament_g"}]`.
`DELETE /api/jobs/{job}` removes a job and its G-code (`409` while it runs).

### `POST /api/jobs/{job}/send` – after the review and the user's confirmation
```json
{"start": true, "confirm": true, "leveling": true, "lanes": {"1": 3, "2": 1}}
→ 200 {"job": "843289d5b2"}
```
- `start: false` = only upload (no confirmation needed). `start: true` needs `confirm: true`
  (`400 "starting a print needs confirm=true"`), the app must have asked the user ("plate empty?", "start?").
- `leveling`: only for printers with `leveling != null`; omitted = printer default.
- `lanes` (AFC): `{"<model colour index>": <tool of the chosen slot>}`. The server rewrites the tool numbers in a
  copy of the G-code – changing slots needs no re-slicing. `409` if a chosen slot is empty and the print should start.
- `409 "printer is busy - wait until the current print has finished"`.

### Preview and G-code
`GET /api/jobs/{job}/preview?format=2` – layers for a 2D viewer (gzip, 0.1–2 MB):
```json
{"version": 2, "unit": 20,
 "types": ["Inner wall", "Outer wall", "Bottom surface", "Internal solid infill", "Sparse infill", "Internal Bridge", "Top surface"],
 "filament_colors": ["#F2754E"], "bounds": [118.21, 118.21, 137.79, 137.79], "bed": [256.0, 256.0],
 "layers": [{"z": 0.2, "paths": [[0, 0, 2744, 2744, 2376, 2744, 2376, 2376, 2744, 2376, 2744, 2743], "…"]}]}
```
Each path: `[type index, tool, x0, y0, x1, y1, …]`, coordinates in 1/`unit` mm (here 1/20 mm). Without
`format=2` the server sends version 1 (no tool entry) for old apps.

`GET /api/jobs/{job}/gcode` – the G-code file (for "share/export").

### One-shot (CLI, iOS Shortcuts)
`POST /api/print {"link": "…", "printer": "centauri", "file": null, "start": true}` → `{"job": "…"}` – downloads,
slices, uploads and starts without review. Not for the apps (no confirmation step).

## Profiles (own OrcaSlicer presets)
| | |
|---|---|
| `GET /api/profiles` | `[{"file": "filament-Meine PLA.json", "kind": "filament", "name": "Meine PLA", "inherits": "Elegoo PLA @ECC"}, …]` (+ `print_start`, `nozzle` for printer presets, `error` if unusable) |
| `POST /api/profiles?filename=x.json` | body: JSON preset or OrcaSlicer bundle (zip); → list of stored presets; `400` with a reason if Orca 2.4.2 doesn't know the base |
| `DELETE /api/profiles/{file}` | `400` while a printer uses it |

`kind`: `machine` (printer), `process` (quality), `filament` (material). Printer presets are assigned per printer
(`PUT /api/printers/{id}/profile`); quality/material presets appear in `/options` under `own`.

## Web-page-only endpoints
Settings that are made on the web page, not in the apps: `/api/printers/{id}/power/config` (GET/PUT/DELETE),
`/power/test`, `/power/entities`. Details in `printshare/api.py`.
