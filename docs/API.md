# PocketPrint3D server API

The contract between the PocketPrint3D server and its apps: the **iOS app (Swift, Dominique)**, the **Android app
(Expo, `mobile/`)** and the **web page** (`printshare/web/`). Server version described here: **0.14.0**.

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
→ 200 {"name": "PrintShare", "version": "0.14.0", "printers": 2}      (the name stays "PrintShare" – technical id)

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

## Two kinds of server: home server and cloud

`GET /api/server` needs **no login** and tells the app which kind it talks to:

```http
GET /api/server
→ 200 {"name": "PrintShare", "version": "0.15.0", "cloud": false, "login": "token"}     home server (Unraid, HA, Docker)
→ 200 {"name": "PrintShare", "version": "0.15.0", "cloud": true,  "login": "email"}     https://api.pocketprint3d.com
```

| | Home server (`login: token`) | Cloud (`login: email`) |
|---|---|---|
| Login | pairing QR code / token (below) | e-mail code → session token per device ([Cloud accounts](#cloud-accounts)) |
| Printers | from the server's configuration | each account adds its own (`POST /api/printers`), **no addresses** |
| Printer status, control, camera, temperatures, power, `/send` | through the server | **`409`** `"the printer is reached through the app on your home network"` – the app talks to the printer itself on the Wi-Fi (docs/CLOUD.md) |
| Slicing, search, uploads, jobs, preview, G-code, profiles | ✅ | ✅, separate per account, with limits |

## Cloud accounts

Only on a cloud server (`/api/server` → `cloud: true`); a home server answers these with `404`.

```http
POST /api/auth/code   {"email": "anna@example.com", "lang": "de"}
→ 200 {"sent": true, "email": "anna@example.com"}        a 6-digit code is e-mailed (valid 10 min, 5 attempts)
→ 400 invalid address · 429 too many codes (3 per address per 15 min, 10 per network per hour) · 502 mail not sent

POST /api/auth/login  {"email": "anna@example.com", "code": "123456", "device": "Pixel 8"}
→ 200 {"token": "pp3d_…", "user": {"id": "4f2c…", "email": "anna@example.com"}}
→ 401 "wrong code" / "the code has expired - please request a new one"
```
The first login creates the account. Store the token in the Keychain / Keystore and send it like the home
server's token: `Authorization: Bearer pp3d_…`. It stays valid until logout or account deletion.

| | |
|---|---|
| `GET /api/auth/me` | `{"id", "email", "printers": 2, "limits": {"slices_per_day": 30, "slices_today": 3, "upload_mb": 100}}` |
| `POST /api/auth/logout` | ends this device's session → `{"ok": true}` |
| `DELETE /api/auth/account?confirm=true` | deletes the account with all printers, profiles, uploads, G-code and jobs (required by Apple/Google in the app; ask the user first) → `{"deleted": true}` |

**Limits of the free service** (answer `429` with a message to show): 30 slices per day and account, one slicing
job at a time per account, uploads up to 100 MB (`413`). Values may change – read them from `/api/auth/me`.

### Printers of an account (cloud)
```http
POST /api/printers   {"name": "Werkstatt CC", "type": "elegoo_sdcp"}
POST /api/printers   {"name": "COSMOS", "type": "moonraker", "cosmos": true}
POST /api/printers   {"name": "MK4", "type": "prusalink", "machine": "Prusa MK4S 0.4 nozzle"}
→ 200 {"id": "werkstatt-cc", "name": "Werkstatt CC", "type": "elegoo_sdcp", "machine": "Elegoo Centauri Carbon 0.4 nozzle",
       "leveling": true, "power": false, "cosmos": false}

PATCH  /api/printers/{id}   any of {"name", "type", "machine", "cosmos", "auto_leveling"}  → the printer as above
DELETE /api/printers/{id}   → {"deleted": "werkstatt-cc"}
```
`machine` (OrcaSlicer printer profile) is required for `prusalink` / `octoprint`; the Centauri profile is the default
otherwise. The choices for it (0.15.3):
```http
GET /api/machines   → [{"name": "Prusa MK4S 0.4 nozzle", "vendor": "Prusa"}, …]   (all of Orca 2.4.2, ~1000)
```
The app reaches `prusalink` printers with the user `maker` + the password from the printer screen (or an API key),
`octoprint` with an API key; both are kept on the phone only. At most 10 printers per account. The address of the printer stays in the app (it finds the printer on
the Wi-Fi) – the server never stores or needs it.

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
- `spoolman` (0.16.0, Klipper only): Moonraker's own Spoolman link – `{"connected": true, "spool_id": 3}` or `null`
  (not configured). When it is not null, Moonraker books the used filament itself: the app must not book it again
  (see "Spoolman" below). Lanes then carry the `spool_id` AFC assigned to them (`null` = none).
- Other fields may exist (e.g. `raw` for the Centauri); ignore them.

### `GET /api/printers/{id}/options[?process=<quality>]`
Everything for the preparation screen. `?process=` returns the defaults of that quality (supports, brim, infill,
infill pattern, walls).

```json
{"printer": "cosmos",
 "materials": ["Meine PLA", "Elegoo ABS @ECC", "Elegoo PLA @ECC", "…"],
 "processes": ["Mein Standard", "0.12mm Fine @Elegoo CC 0.4 nozzle", "0.20mm Standard @Elegoo CC 0.4 nozzle", "…"],
 "own": {"materials": ["Meine PLA"], "processes": ["Mein Standard"]},
 "plates": ["Textured PEI Plate", "High Temp Plate", "Cool Plate", "Engineering Plate", "Supertack Plate"],
 "supports": ["off", "normal", "tree"], "brims": ["auto", "off", "outer"],
 "infill_patterns": ["rectilinear", "alignedrectilinear", "zigzag", "…", "grid", "triangles", "cubic", "gyroid", "…"],
 "defaults": {"filament": "Elegoo PLA @ECC", "process": "0.20mm Standard @Elegoo CC 0.4 nozzle",
              "bed_type": "Textured PEI Plate", "supports": "off", "brim": "auto", "infill": 15, "walls": 2,
              "infill_pattern": "rectilinear", "infill_line_width": 0.45, "layer_height": "0.2"}}
```
- Names are OrcaSlicer preset names; show them shortened (text before ` @`).
- `own`: uploaded presets of the user (shown first, group "Own profiles").
- Since 0.15.3 `materials` also lists OrcaSlicer's printer-independent library (`Generic PETG @System`, …) after the
  printer's own materials, and presets that pick their printers by condition (Prusa, CORE One) are included.
- `infill_patterns` (0.15.2): OrcaSlicer's `sparse_infill_pattern` values (all of Orca 2.4.2, in Orca's order); an app
  may offer a subset. `defaults.infill_pattern`: the quality's pattern (Orca's legacy `zig-zag` is reported as
  `rectilinear`, like Orca reads it), `defaults.infill_line_width`: infill line width in mm (`null` if the preset
  gives it as a percentage) – for a true-to-scale infill preview. Missing on older servers: hide the choice.

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

**MakerWorld (0.17.1, model pages only):** `GET /api/models/makerworld/{id}` (id from `makerworld.com/…/models/<id>`) gives
the same fields plus `download: "external"` (Printables/Thingiverse: `"server"`), `files: []` and `variants`
(`[{"id", "title", "default", "weight_g", "print_hours", "materials", "colors", "needs_ams"}]`, MakerWorld's "profiles").
MakerWorld has no public API: search is behind a bot check and downloads need the user's own MakerWorld login, so it is
not in `/api/sources` and `/api/files` / `/api/jobs` answer `400 "MakerWorld only allows downloads with your own MakerWorld
account …"`. Apps show the model page with a button to MakerWorld; the user downloads the 3MF there and shares the file with
the app (normal upload flow; Orca reads Bambu Studio projects incl. colours).

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
             "supports": "off", "brim": null, "infill": 20, "infill_pattern": "gyroid", "walls": null,
             "filaments": null,
             "copies": 4, "rotate_x": 90, "rotate_y": null, "scale": 100, "orient": null}}
→ 200 {"job": "843289d5b2"}
```
`null` / missing = the printer's default. `infill_pattern` (0.15.2): one of `/options` `infill_patterns`, else
`400` (older servers ignore it). `filaments`: multicolour, one preset per model filament (by index,
`null` = default). `400` if a material/quality doesn't fit the printer.

Plate options (since 0.14.0; older servers ignore them silently, so check `/api/info` `version` first):
- `copies` 1–50: copies of the model on the plate, arranged by OrcaSlicer. If they don't all fit, it puts as
  many as fit – `result.copies` says how many.
- `rotate_x`, `rotate_y` −360…360: tilt in degrees before slicing (e.g. 90 = lay on another side). Each object
  turns about its own centre and stays on the bed. No rotation about Z: the arrangement turns objects anyway.
  STL, 3MF and OBJ only (STEP → job `error`).
- `scale` 10–1000: size in percent.
- `orient` `true`/`false`: lay flat automatically (null = printer setting). Not together with `rotate_x/y` (`400`).

### `GET /api/jobs/{job}`
```json
{"id": "843289d5b2", "kind": "prepare", "state": "sliced",
 "log": ["Looking up model files", "Slicing for COSMOS + CANVAS", "Sliced: 8m 49s / 3.94 g"],
 "result": {"printer": "cosmos", "source_file": "cube.stl", "gcode": "/data/gcode/cosmos/843289d5b2/cube.gcode",
            "print_time": "8m 49s", "filament_g": 3.94, "filament_m": 1.31, "layers": 100,
            "profiles": {"machine": "Elegoo Centauri Carbon 0.4 nozzle", "process": "0.20mm Standard @Elegoo CC 0.4 nozzle",
                         "filament": "Elegoo PLA @ECC", "bed_type": "Textured PEI Plate"},
            "overrides": {"enable_support": "0", "sparse_infill_density": "20%"},
            "sent": {}, "filaments": [], "copies_requested": null, "copies": null},
 "error": null, "created": 1790778079.45, "request": {"link": "…", "printer": "cosmos", "file": null, "options": {…}}}
```
- **`state`**: `slicing` → `sliced` | `error`; after `/send`: `sending` → `uploaded` | `started`
  (a failed send goes back to `sliced` with `error` set, so the user can try again).
- `log`: progress lines (English; the apps translate the known ones).
- `result.filaments` (multicolour): `[{"index", "color", "preset", "grams"}]`.
- `result.copies_requested` / `result.copies` (0.14.0): copies asked for and copies on the plate; both `null`
  for one copy. `copies < copies_requested` → show "only N of M fit". Times and grams are for the whole plate.
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
- `spool_id` (0.16.0, Klipper with `status.spoolman` not null): Moonraker's active spool is set to it before the
  upload, so Moonraker books this print on that spool. `400` for other printer types. Leave it out with AFC (the lanes
  carry their own spools).
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

`GET /api/jobs/{job}/gcode[?lanes={"1":3,"2":1}]` – the G-code file (for "share/export"). With `lanes` (AFC slot
mapping, as in `/send`) the tool numbers are rewritten on a copy: **in the cloud the app downloads this and sends it to
the printer itself** on the home Wi-Fi (see `mobile/src/lib/lan/` for the Centauri SDCP and Moonraker side).

### One-shot (CLI, iOS Shortcuts)
`POST /api/print {"link": "…", "printer": "centauri", "file": null, "start": true}` → `{"job": "…"}` – downloads,
slices, uploads and starts without review. Not for the apps (no confirmation step).

### Own Manyfold library (0.21.0, own servers only – never in the cloud)
[Manyfold](https://manyfold.app) is a self-hosted 3D model library. When it is set up, `GET /api/sources` lists
`{"id": "manyfold", "name": "Manyfold", "available": true}` and search/model details work like Printables. Hits carry
`"link": "manyfold:<id>"` – **use `link` (if present) instead of `url` for `/api/files`, `/api/jobs`**; `url` is the model
page in Manyfold (needs a Manyfold login in the browser). Images (`thumbnail`, `images`) are **server-relative**
(`/api/manyfold/image/<model>/<file>`): prefix the server address and add `?token=` (image views can't send headers).

| | |
|---|---|
| `GET /api/manyfold/config` | `{"configured", "url", "token_set", "client_set"}` (never the key) |
| `PUT /api/manyfold/config` `{"url", "token"}` | checks the connection, stores it (`<config dir>/manyfold.yaml`, 0600) → `{"configured": true, "url", "models": 61}`; `400` with Manyfold's reason; `token` omitted = keep |
| `DELETE /api/manyfold/config` | removes the app setting (`config.yaml` / env `MANYFOLD_URL`, `MANYFOLD_TOKEN`, `MANYFOLD_CLIENT_ID`, `MANYFOLD_CLIENT_SECRET` may still set it) |
| `GET /api/manyfold/image/{model}/{file}` | a model image through the server (only `image/*`, not SVG) |

All `409` in the cloud. The server reads Manyfold's API v0 (`/models`, `/models/{id}`, `/models/{id}/model_files/{id}`,
`Accept: application/vnd.manyfold.v0+json`, bearer API key or OAuth client credentials); the JSON API has no search, so
the model list (ids + names) is cached 5 minutes and searched on the server.

### AI failure detection (0.23.0, own servers only)
The user runs Obico's ML API (`ml_api` service of obico-server, AGPL, separate container). While a printer prints, the
server checks a camera frame every `interval` s (frames offered under one-time addresses `/api/detect/frame/<token>.jpg`,
60 s, no key) and smooths the failure confidences; after a warm-up of 12 frames per print an alert is raised at the
sensitivity's threshold (low 0.75, medium 0.55, high 0.38), optionally pausing the printer.

| | |
|---|---|
| `GET /api/printers/{id}/status` | adds `"watch": {"state": "idle|warming|watching|alert|muted", "score", "threshold", "frames", "last_check", "alerted_at", "paused", "action", "error", "frame"}` when set up |
| `GET /api/printers/{id}/watch/frame` | the last checked frame (JPEG) – `?token=` for image views |
| `POST /api/printers/{id}/watch/mute` | "false alarm": no more alerts for this print |
| `GET /api/failure-detection/config` | `{"configured", "ml_url", "token_set", "server_url", "interval", "sensitivity", "action"}` |
| `PUT /api/failure-detection/config` `{"ml_url", "ml_token"?, "server_url"?, "interval", "sensitivity", "action"}` | saved only after the ML API fetched and checked a test frame → `{…, "test": {"detections": 0}}`; `400` with the reason (e.g. "can it reach http://…?") |
| `DELETE /api/failure-detection/config` | turns it off (env `ML_API_URL` / `ML_API_TOKEN` may still set it) |

All `409` in the cloud. `server_url` = this server as the ML API container reaches it (default `PRINTSHARE_URL`).

## Web app login (0.28.0, cloud – docs/WEB.md)
- `POST /api/auth/login {…, "cookie": true}` → the session goes into the HttpOnly cookie `pp3d_session` (Secure,
  SameSite=Strict, 180 days) and the answer has `"token": null`. Requests then carry no Authorization header; changes
  (anything but GET/HEAD) need `X-Requested-With: pocketprint3d`, else 403. `POST /api/auth/logout` and account deletion
  clear the cookie. Apps keep using the token as before.
- The cloud server serves the web app at `/` (app routes → `index.html`, `/api/*` never).

## Spool bookings in the account (0.29.0, cloud – docs/WEB.md step 2)
For spools kept in the cloud (`/spoolman/…`): the app registers what a print uses, the server books it when the print is
finished. An own Spoolman at home keeps the app's own bookings (phone).
- `POST /api/bookings {"printer", "file", "uses": [{"spool", "grams", "label"?}], "printer_name"?, "job"?}` → `{"booking"}`
  (`null` without uses). `file` = the name on the printer (for bridge sends: the job's `printer_file`). A new booking
  replaces one on the same printer that never started; spools must be the account's (404); 50 open at most (409).
- `GET /api/bookings` → `{"waiting", "open", "booked"}` – waiting for the print, the user decides (`ask_part` = suggested
  share), booked in the last 15 min (`booked_uses`). Booking: `{id, printer, printer_name, file, job, uses, booked_uses,
  created, seen, progress, state: wait|ready|ask|booked|dropped, ask_part}`.
- `POST /api/bookings/observe {"statuses": {"<printer>": <status as from /status> | null}}` → the list + `booked_now`:
  the app reports printers it reaches on the Wi-Fi (not printers it can't see - `null` means "not reachable", which asks
  after 3 days). Printers behind a bridge are checked by the cloud itself every minute.
- `POST /api/bookings/{id}/resolve {"part": 0..1}` (0 = nothing), `DELETE /api/bookings/{id}`.
- Rules (same as the app's before): finished → book all; cancelled/error → ask with the printed share; never seen
  printing for 20 min or another file → ask; unreachable 3 days → ask. Each spool is removed once booked (no double booking).
- `GET /api/jobs/{id}` has `printer_file` after a send through a bridge (the file's name on the printer).

## Bridges (0.24.0, cloud only – docs/BRIDGE.md)
A bridge is a PocketPrint3D server at home that keeps one outgoing WebSocket to the cloud. Step 2 (cloud side) is
built; forwarding the printer endpoints to a bridge comes with step 4.

**Pairing (bridge side, no login):**
- `POST /api/bridge/pair/start {"bridge_id", "public_key"?, "version"?, "name"?}` → `{"code": "K7Q4-M2ZX", "poll",
  "expires_in": 600}`. `bridge_id` 8–64 of `[A-Za-z0-9-]` (a UUID), `public_key` = X25519, 32 bytes base64. 20 per IP/hour (429).
- `POST /api/bridge/pair/poll {"bridge_id", "poll"}` → `{"status": "waiting", "expires_in"}` until the user entered the
  code, then once `{"status": "paired", "token": "pp3db_…", "account": "<e-mail>"}`; 404 unknown, 410 expired.

**App (session token):**
- `POST /api/bridges/pair {"code", "name"?}` → bridge (below). The code is accepted with or without dash, any case;
  404 unknown/expired, 429 after 5 wrong codes in 15 min, 409 at 10 bridges. Pairing a bridge again (e.g. after a
  reset) replaces its token; another account taking it over removes it from the old one.
- `GET /api/bridges` → `[{"id", "name", "version", "public_key", "created", "last_seen", "online", "connected",
  "printers": [{"id", "name", "type", "machine", "capabilities"}]}]` (printers as the bridge reports them; never
  addresses or secrets). Home servers answer `[]`.
- `PATCH /api/bridges/{id} {"name"}`, `DELETE /api/bridges/{id}` (token revoked, connection closed with 4001).

**Bridge connection:** `WS /api/bridge/ws`, header `Authorization: Bearer pp3db_…`. First frame `{"type": "hello",
"version", "printers"}` → `{"type": "welcome", "bridge_id", "min_version", "methods"}`. Close codes: 4401 unknown token
(pair again), 4426 version below `min_version` (0.24.0), 4400 no hello within 10 s, 4000 replaced by a newer connection of
the same bridge, 4001 removed from the account. Requests/responses/events as in docs/BRIDGE.md section 6 (methods:
`printers.list`, `printer.status`, `printer.control`, `printer.controls`, `printer.adjust`, `printer.temperatures`,
`printer.camera.snapshot`, `printer.power`, `job.send`, `watch.state`, `watch.mute`, `discover`, `printer.add|update|remove`;
events `printer.state`, `watch.alert`, `job.progress`, `printers.changed`).
- `GET /api/bridge/jobs/{job}/gcode?lanes=` (bridge token) – the G-code of a job of the bridge's account (same as
  `/api/jobs/{job}/gcode`); 401 for other tokens, 404 for other accounts' jobs.
- `GET /api/admin/stats` adds `bridges`, `bridges_online`.

**Printers behind a bridge (0.26.0):** a connected bridge's printers become printers of the account automatically (on
every connect and every `printers.changed`; they stay while the bridge is offline, so jobs and slicing profiles keep
working). `GET /api/printers` marks them with `"bridge": "<bridge id>"` (`null` = reached by the phone on the Wi-Fi).
For these printers the cloud **forwards** the usual endpoints to the bridge instead of answering 409:
`GET /api/printers/{id}/status|controls|temperatures|camera|camera/snapshot|power`, `POST /api/printers/{id}/control|adjust|power|watch/mute`,
`POST /api/jobs/{job}/send` (same body; `confirm` is checked by the cloud and the bridge; busy printer, lanes and spool
by the bridge; upload steps appear in the job's `log`). `camera` says `"stream": false` (still pictures only through a
bridge). Bridge offline → 503 with a clear text, no answer → 504. Name and slicing model come from the bridge; a name
changed with `PATCH /api/printers/{id}` stays. `DELETE /api/printers/{id}` removes a printer on the bridge too (only
printers added through the app; others → 400).
- `POST /api/bridges/{id}/discover` → printers the bridge finds at home (`[{"type", "address", "name", "cosmos"?,
  "detail"?, "added"}]`; the address is only for display/sealing, it never needs to be sent back in plain text).
- `POST /api/bridges/{id}/printers {"printer": {"name", "type", "machine"?, "cosmos"?}, "sealed": "<pp3d-seal-v1 of
  {address, password?, api_key?} for this bridge's public_key>"}` → the new printer of the account (as in `GET /api/printers`).
- `PUT /api/printers/{id}/bridge-access {"sealed"}` – new address/password/key for a printer added this way.

### Bridge mode of a home server (0.25.0)
On the user's own server (not in the cloud), with the server's token:
- `GET /api/bridge` → `{"enabled", "state": "off|pairing|connecting|connected|error", "code": "K7Q4-M2ZX" | null,
  "code_expires_in", "paired", "account", "cloud", "bridge_id", "connected_since", "error"}` – the code is what the user
  enters in the app (`POST /api/bridges/pair` on the cloud).
- `POST /api/bridge {"enabled": bool}` – switch bridge mode on/off (kept in `bridge.yaml`; else config `bridge: true` /
  env `PRINTSHARE_BRIDGE=1`). `POST /api/bridge/reset` – forget the pairing, show a new code.
- Methods the bridge answers: docs/BRIDGE.md section 6. `printer.add {"printer": {"name", "type", "machine"?, "cosmos"?},
  "sealed": "<pp3d-seal-v1 blob of {address, password?, api_key?}>"}` → the printer as in `printers.list`;
  `printer.update {"printer": id, …}` (address/secrets kept unless sealed again), `printer.remove {"printer"}` (only
  printers added this way); `job.send {"printer", "job", "start", "confirm", "leveling"?, "lanes"?, "spool_id"?}` →
  `{"state": "started|uploaded", "file"}`, errors `confirm_required`, `busy`, `download_failed`, `send_failed`;
  `printer.camera.snapshot {"printer", "w"?}` → `{"jpeg": base64, "type"}`; `discover` → `[{"type", "address", "name",
  "cosmos"?, "detail"?, "added"}]`. Error codes: `invalid`, `unknown_printer`, `busy`, `confirm_required`, `offline`.

## Spoolman (0.16.0, spec MA-07)
[Spoolman](https://github.com/Donkie/Spoolman) keeps track of filament spools. **The apps talk to the user's Spoolman
directly** on the home network (like to the printers in cloud mode); its address stays on the phone and the server
needs no setting. API: https://donkie.github.io/Spoolman/ – the apps use

| | |
|---|---|
| `GET /api/v1/info` | connection test (`version`); Spoolman listens on port 7912 unless a proxy is used |
| `GET /api/v1/spool?allow_archived=false&sort=last_used:desc,id:asc` | spools: `id`, `remaining_weight` (g, `null` if unknown), `location`, `filament.{name, material, color_hex, vendor.name}` |
| `PUT /api/v1/spool/{id}/use` `{"use_weight": 11.4}` | book used filament in grams |

What the Android app does (`mobile/src/lib/spoolman.ts`):
1. Review screen: one spool per colour (default: the AFC lane's `spool_id`, else Moonraker's active spool, else the
   last choice for that printer). Warning when `remaining_weight` < the colour's grams, or the spool's material
   differs from the preset's.
2. **Who books:** printer `status.spoolman` not null → Moonraker books itself; the app only sends `spool_id` with
   `/send` (single colour, no AFC) or, in the cloud, sets it itself (`POST /server/spoolman/spool_id`). Otherwise
   (Centauri, PrusaLink, OctoPrint, Klipper without Moonraker's Spoolman link) **the app books**: after "Print" it
   stores a booking (printer, file name on the printer, spool + grams per colour).
3. With every printer status it reads, the app settles the booking: same file and `kind` `done` → book it all;
   `stopped`/`error` → ask the user (all / the printed share from `progress` / nothing); the file vanished after it was
   seen printing → book if it had reached 99 %, else ask; never seen within 20 min → ask. A booked spool is removed
   from the booking right away, so a retry never books twice. "Upload only" books nothing.

### Spools in the cloud (0.17.0)
For cloud accounts without a Spoolman at home the server keeps the spools itself, under **`/spoolman/api/v1/…`** with
the session token (`Authorization: Bearer pp3d_…`). Reading and booking answer exactly like Spoolman, so an app points
its Spoolman code at `https://api.pocketprint3d.com/spoolman` and changes nothing else:

| | |
|---|---|
| `GET /spoolman/api/v1/info` | `{"version": "0.17.0", "name": "PocketPrint3D", …}` |
| `GET /spoolman/api/v1/spool[?allow_archived=true]` | Spoolman's spool objects, recently used first (other filters are ignored) |
| `GET /spoolman/api/v1/spool/{id}` | one spool; ids are numbered per account (#1, #2 …) |
| `PUT /spoolman/api/v1/spool/{id}/use` | `{"use_weight": g}` or `{"use_length": mm}` (from density + diameter) |
| `POST /spoolman/api/v1/spool` | **PocketPrint3D's own shape** (no filament ids): see below |
| `PATCH /spoolman/api/v1/spool/{id}` | same fields, all optional; `remaining_weight` = weighed again; `archived` |
| `DELETE /spoolman/api/v1/spool/{id}` | `{"deleted": 3}` |

```json
POST /spoolman/api/v1/spool
{"filament": {"vendor": "Elegoo", "name": "Rapid PLA+ Black", "material": "PLA", "color_hex": "#000000",
              "weight": 1000, "density": 1.24, "diameter": 1.75},
 "remaining_weight": 640, "location": "Shelf", "comment": "opened"}
→ {"id": 1, "filament": {"name": "Rapid PLA+ Black", "vendor": {"name": "Elegoo", …}, "material": "PLA",
   "color_hex": "000000", "weight": 1000, …}, "initial_weight": null, "used_weight": 360, "remaining_weight": 640, …}
```
- `filament.weight` = filament on a full spool; `remaining_weight` given → `used_weight = weight − remaining` (without a
  weight the remaining becomes the initial weight). Everything optional, `color_hex` with or without `#`.
- 500 spools per account (`400`), `404` on a home server ("use your own Spoolman"), deleted with the account.
- Android: Settings → Spoolman → "In der Cloud" stores `cloud` instead of an address (`CLOUD_SPOOLS` in
  `mobile/src/lib/spoolman.ts`); spool list `app/spools.tsx`, form `app/spool/[id].tsx` (copy for a stack of equal spools).

### Filament presets from SpoolmanDB (0.19.0)
For adding spools: [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) (MIT, Donkie and contributors) – the server loads
`https://donkie.github.io/SpoolmanDB/filaments.json` at most once a day (kept on disk, an older copy is used when GitHub
Pages is down) and condenses it to one entry per brand + name + material + colour.

| | |
|---|---|
| `GET /api/filament-db/brands` | `[{"name": "ELEGOO", "count": 97}, …]` (67 brands, sorted case-insensitively) |
| `GET /api/filament-db/filaments?brand=ELEGOO&diameter=1.75` | `[{"id", "name": "Red", "material": "PLA", "color_hex": "EA140E", "color_hexes": null, "density": 1.26, "extruder_temp": 210, "bed_temp": 60, "finish": null, "translucent": false, "glow": false, "weights": [{"weight": 1000, "spool_weight": 154}], "diameter": 1.75}, …]` sorted by material, name; `404` unknown brand, `503` database not available |

Android: spool form → "Aus Datenbank wählen" → brand → filament fills vendor, name, material, colour, weight and sends
`spool_weight` + `filament.density` along.

### OpenPrintTag (NFC spools, app side)
No server API: the Android app reads OpenPrintTag spools (Prusa's open NFC standard, https://specs.openprinttag.org)
itself and fills the spool form / picks the matching spool – see `mobile/src/lib/openprinttag.ts` (parser) and
`mobile/src/lib/nfc.ts` (matching) for an implementation the iOS app can follow (Core NFC `NFCISO15693Tag`).

## Profiles (own OrcaSlicer presets)
| | |
|---|---|
| `GET /api/profiles` | `[{"file": "filament-Meine PLA.json", "kind": "filament", "name": "Meine PLA", "inherits": "Elegoo PLA @ECC"}, …]` (+ `print_start`, `nozzle` for printer presets, `error` if unusable) |
| `POST /api/profiles?filename=x.json` | body: JSON preset or OrcaSlicer bundle (zip); → list of stored presets; `400` with a reason if Orca 2.4.2 doesn't know the base |
| `DELETE /api/profiles/{file}` | `400` while a printer uses it |
| `POST /api/profiles/orca-cloud` `{"link": "https://cloud.orcaslicer.com/b/<code>"}` (0.18.0) | imports a **public** Orca Cloud bundle (**no Orca account**; private bundles only open for whitelisted, logged-in Orca users → `400 "bundle not found or private …"`): `{"bundle": {"name", "author", "version", "updated"}, "imported": [<same as the list above>], "skipped": [{"name", "error"}]}`; presets Orca 2.4.2 can't use are skipped, `400` if none is usable / not a share link / not found |

Orca Cloud: the server reads `GET https://api.orcaslicer.com/api/v1/bundles/share/<code>` (open, found in the
cloud.orcaslicer.com web app); presets inheriting another preset of the same bundle are merged first, `"type": "printer"`
is stored as `machine`. Apps: after the import, set the printer profile automatically only if exactly one imported printer
preset `inherits` the printer's system model (`GET /api/printers/{id}/profile` → `machine`), else let the user choose.

`kind`: `machine` (printer), `process` (quality), `filament` (material). Printer presets are assigned per printer
(`PUT /api/printers/{id}/profile`); quality/material presets appear in `/options` under `own`.

## Web-page-only endpoints
Settings that are made on the web page, not in the apps: `/api/printers/{id}/power/config` (GET/PUT/DELETE),
`/power/test`, `/power/entities`. Details in `printshare/api.py`.
