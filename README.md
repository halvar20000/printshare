# PrintShare

Send a **Printables** or **Thingiverse** link from your phone. PrintShare downloads the model, slices it with **OrcaSlicer** on your own server, uploads the G-code to your printer and starts the print. It's a self-hosted "Bambu Handy" for everyone else.

Supported printers:

| Printer | Interface | Type in config | Tested |
|---|---|---|---|
| Elegoo Centauri Carbon | stock Elegoo (SDCP) | `elegoo_sdcp` | real printer |
| Elegoo Centauri Carbon | OpenCentauri **COSMOS** (Klipper) | `moonraker` + `machine_preset: cosmos` | simulated |
| Any Klipper printer (Voron, Sovol, Qidi, Neptune 4 …) | Moonraker | `moonraker` | simulated |
| Prusa MK4/MK4S, MK3.9, CORE One, MINI, XL | **PrusaLink** (password from the printer screen) | `prusalink` | simulated |
| Printers driven by **OctoPrint** (Ender, MK3S …) | OctoPrint API key | `octoprint` | simulated |

For Prusa and OctoPrint printers set `printer_profile` to the printer's name in OrcaSlicer (e.g.
`Prusa MK4S 0.4 nozzle`); quality and filament then default to that printer's own OrcaSlicer defaults.
*Simulated* = tested against a fake printer built from the official API – reports from real printers welcome.

```
Phone ──link──▶ PrintShare (Docker on Unraid) ──▶ Printables / Thingiverse
                     │  OrcaSlicer (command line, same profiles as the desktop app)
                     └──▶ Centauri Carbon (SDCP)  /  Klipper (Moonraker)
```

---

## 1. Install

Pre-built image for amd64 and arm64: `ghcr.io/halvar20000/printshare`. You only enter the printer's IP
address; on first start the container log shows the **access token** and a **QR code** for the app.

### Unraid

On the Unraid console (as root), load the template once:

```bash
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-PrintShare.xml \
  https://raw.githubusercontent.com/halvar20000/printshare/main/unraid/printshare.xml
```

Then **Docker → Add Container → Template: PrintShare**, fill in *Printer type*, *Printer IP address* and
*Server address for the app* (e.g. `http://192.168.1.10:8484`), **Apply**. Open the container log
(Docker tab → PrintShare icon → Logs) and scan the QR code in the app.

Updates: Docker tab → *Check for Updates* → *Apply update*. The configuration in `/mnt/user/appdata/printshare` stays.

### Home Assistant

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add `https://github.com/halvar20000/printshare`.
2. Install **PrintShare**, then under **Configuration** add your printer:
   ```yaml
   - name: Centauri Carbon
     type: elegoo_sdcp        # or moonraker (Klipper / COSMOS)
     address: 192.168.1.50
   ```
3. Start the add-on, open the **Log** tab and scan the QR code in the app.

Details: [homeassistant/printshare/DOCS.md](homeassistant/printshare/DOCS.md).

### Docker (any Linux server)

```bash
docker run -d --name printshare --restart unless-stopped -p 8484:8484 \
  -e PRINTER_TYPE=elegoo_sdcp -e PRINTER_ADDRESS=192.168.1.50 \
  -e PRINTSHARE_URL=http://192.168.1.10:8484 \
  -v /opt/printshare:/config -v /opt/printshare/data:/data \
  ghcr.io/halvar20000/printshare:latest
docker logs printshare        # token + QR code
```

Or with `docker compose up -d` using [docker-compose.yml](docker-compose.yml).

### Printer settings (all install methods)

| Setting (Unraid variable / HA option) | Meaning |
|---|---|
| `PRINTER_TYPE` / `type` | `elegoo_sdcp` = Centauri Carbon stock firmware, `moonraker` = Klipper (e.g. COSMOS) |
| `PRINTER_ADDRESS` / `address` | printer IP (give it a fixed DHCP lease) |
| `PRINTER_COSMOS` / `cosmos` | Klipper only: `PRINT_START`/`PRINT_END` start code for COSMOS (default on) |
| `BUILD_PLATE` / `build_plate` | default plate, changeable per print |
| `PRINTSHARE_URL` / `server_url` | address the phone uses at home; needed for the QR code (HA detects it) |
| `PRINTSHARE_REMOTE_URL` / `remote_url` | optional address away from home, e.g. Tailscale `http://100.x.y.z:8484`; the app switches automatically |
| `PRINTSHARE_API_TOKEN` / `api_token` | empty = generated once |

When a printer is set in the form, `config.yaml` is regenerated on every start. Leave the printer address
empty to edit `config.yaml` by hand instead (several printers, overrides, exported OrcaSlicer presets) –
start from [`config-example.yaml`](config-example.yaml).

### Build it yourself (developers)

```bash
docker build -t printshare:dev .          # ~5 min; downloads OrcaSlicer 2.4.2 for your CPU
bash scripts/unraid-install.sh             # Unraid: build + run from a source checkout
```

## 2. Your own OrcaSlicer printer profile (optional)

In the app: **Settings → your printer → Upload printer profile**, or on the web page: **Settings → Printer profile**. Export the profile in OrcaSlicer
(File → Export → preset bundle `.zip`, or the profile's JSON file), pick it on the phone – the server
checks it (valid preset, parent profile known to OrcaSlicer 2.4.2) and uses it for this printer right away.
It is kept in `/config/profiles/` and assigned in `/config/printers.d/<printer>.yaml`, so it survives the
Unraid template / Home Assistant add-on regenerating `config.yaml`. A profile with its own `PRINT_START`
(e.g. COSMOS with AFC) is not overridden by the built-in COSMOS start code.

**Own quality and material profiles** work the same way: upload them (a bundle may contain printer, quality
and material profiles together) and they appear first under *Own profiles* when you prepare a print, on every
printer they fit. Syncing them automatically from Orca Cloud is planned (#7).

API: `POST /api/profiles?filename=…` (raw body), `GET /api/profiles`, `DELETE /api/profiles/<file>`,
`GET|PUT /api/printers/<id>/profile` `{"machine_file": "<file>" | null}`.

## 2b. Configure your printer by hand (optional)

Only needed without the form fields above. Edit `config.yaml`, keep only your own printer block:

* **Thomas (stock firmware):** `type: elegoo_sdcp` with `host:` set to the printer's IP. Give the printer a fixed DHCP lease.
* **Dominique (COSMOS):** `type: moonraker` with `url:` set to the same address you use for Mainsail, plus `machine_preset: cosmos`.
  - The preset replaces Elegoo's start/end G-code with `PRINT_START … TOOL=… / PRINT_END`, because COSMOS ≥ 26.07 deliberately e-stops on the old `M729`/`M8213` commands, and uses AFC tool changes (`T<n> PURGE_LENGTH=…`) for multicolour prints with CANVAS on COSMOS.
  - Best practice: import the official [COSMOS OrcaSlicer profile](https://cloud.orcaslicer.com/b/3fad3c38f25f) in OrcaSlicer on the desktop and export the printer preset as JSON. Copy it to `/mnt/user/appdata/printshare/profiles/` and set `machine_file: /config/profiles/<file>.json`.

To list the preset names you can use:

```bash
docker exec printshare printshare presets process -s "Elegoo CC"
docker exec printshare printshare presets filament -s "@ECC"
```

## 3. Test from the command line first

The commands below use the container name `printshare` from `docker run`/Docker Compose. The Unraid template
names the container `PrintShare` – use `docker exec PrintShare …` there (`docker ps` shows the name).

```bash
docker exec printshare printshare printers
docker exec printshare printshare status -p cc-thomas
docker exec printshare printshare files "https://www.printables.com/model/3161-3d-benchy"
docker exec printshare printshare print "https://www.printables.com/model/3161-3d-benchy" -p cc-thomas --no-start
```

`--no-start` only uploads the file, so you can check it on the printer screen before the first real print. `--slice-only` doesn't contact the printer at all; the G-code ends up in `/mnt/user/appdata/printshare/data/gcode/`.

## 4. The app on your phone

**Native app (iOS + Android):** see [`mobile/README.md`](mobile/README.md).

**Connect the app** – easiest way: open `http://<server-ip>:8484` in a browser, enter the access token
(shown in the container / add-on log) under *Settings*, then *Settings → Connect the app → Show QR code* and
scan it in the app (*Settings → Connect server → Scan QR code*). Check the home address first – when the page
was opened as `localhost` or through Home Assistant, enter the server's IP address with port 8484 instead;
add the away address (e.g. Tailscale) there too. The code contains the token, so don't share screenshots of it.

The same code is printed in the container log on start (when `PRINTSHARE_URL` / add-on `server_url` is set)
and by the command line:

```bash
docker exec PrintShare printshare pair --url http://<server-ip>:8484   # Unraid template
docker exec printshare printshare pair --url http://<server-ip>:8484   # docker run / Compose
```

**Web app (PWA)** — works in any browser without installing from a store:

PrintShare is also a web app (PWA) served by the container: iPhone and Android, no app store.
Flow: share or paste a link → choose material, quality, plate, supports, brim, infill, walls →
**Slice** → check time, filament, layers and the changed values → tick "the build plate is empty" →
**Print** (or *Upload only*). Nothing starts without that confirmation. The *Printer* tab shows
live status with Pause / Resume / Cancel.

**Open it once with the token** (the phone stores it, and the token is removed from the address bar):
`https://<server>/?token=<api_token>` — or enter the token under *Settings*.

**HTTPS via Tailscale (recommended).** Installing the app and the Android share menu need HTTPS.
On the Unraid host (Tailscale plugin, *MagicDNS* and *HTTPS certificates* enabled in the Tailscale admin console):

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:8484
tailscale serve status            # shows the address, e.g. https://tower.<tailnet>.ts.net:8443
```

Works from home and on the go (phone with Tailscale on); nothing is exposed to the internet.
Plain `http://<server>:8484` also works in the browser, but without install and share menu.

* **Install:** iPhone (Safari): Share → *Add to Home Screen*. Android (Chrome): menu ⋮ → *Install app*.
* **Android share menu:** once installed, *PrintShare* appears when you share a link from the Printables app or Chrome.
* **iPhone share menu:** Shortcuts app → new Shortcut → *Show in Share Sheet* (URLs) → action *Open URLs*
  with `https://<server>/?link=` + *Shortcut Input*. In Printables or Safari: Share → *PrintShare*.

API (header `Authorization: Bearer <token>`):

```
GET    /api/info
GET    /api/printers
GET    /api/printers/<id>/options[?process=...]   materials, qualities, plates, defaults
POST   /api/uploads?name=part.stl   raw file body -> {"link": "upload:<id>"} (use as link below)
GET    /api/files?link=...
GET    /api/sources | /api/search?q=&source=printables|thingiverse&sort=relevant|popular|makes | /api/models/<source>/<id>
POST   /api/jobs   {"link", "printer", "file", "options": {"filament", "process", "bed_type",
                    "supports": "off|normal|tree", "brim": "auto|off|outer", "infill": 20, "walls": 3}}
GET    /api/jobs   |   GET /api/jobs/<id>   |   DELETE /api/jobs/<id>
POST   /api/jobs/<id>/send   {"start": true, "confirm": true}      # confirm is required to start
GET    /api/printers/<id>/status
POST   /api/printers/<id>/control   {"action": "pause|resume|cancel", "confirm": true}
POST   /api/print  {"link", "printer", "file", "start"}   # one-shot slice + send (CLI, shortcuts)
```

## 5. Switch the printer on and off (optional, Home Assistant)

If the printer hangs on a smart plug that Home Assistant knows (`switch.…`, `light.…` or `input_boolean.…`),
PrintShare can switch it: open the web page → *Settings → Power*, enter the Home Assistant address (e.g.
`http://192.168.1.5:8123`) and a long-lived access token (Home Assistant → your profile → *Security*), tap
*Load list*, pick the plug, *Test*, *Save*. As Home Assistant add-on, address and token can stay empty.

The app then shows *Switch on* while the printer is off, and *Switch off* in the printer's *Control* screen;
switching off asks first and is refused while a print is running. The token stays on the server
(`printers.d/<printer>.yaml`, readable only by the owner) and is never sent back to the app or browser.

## Notes and limits (P0)

* **Printables** has no official API. PrintShare uses the website's own endpoint (search, model details, download), only on the user's behalf; files are never stored for others. Paid and premium models are not shown.
* **Thingiverse** (links and search in the app) needs an app token: thingiverse.com/developers → *Create an App* → copy the *App Token* into the Unraid field *Thingiverse app token*, the Home Assistant option `thingiverse_token` or `thingiverse_token:` in `config.yaml`, then restart.
* Models with several files: the app asks which file to use; on the command line use `--file N`. A single 3MF is preferred automatically.
* 3MF project files from Bambu Studio are sliced with *your* printer profile. Their plate layout is kept, but print settings saved inside the 3MF are not used.
* Plate thumbnails are empty, because the server has no graphics output.
* Jobs are kept in memory only (last 50) and are lost when the container restarts. Slicing runs one job at a time (`max_parallel_slices`).

## Development

The server API used by the apps is documented in [`docs/API.md`](docs/API.md); plans for a hosted service in
[`docs/CLOUD.md`](docs/CLOUD.md).

```bash
pip install -e ".[dev]"
ORCA_ROOT=/path/to/extracted/OrcaSlicer pytest -q     # fake SDCP + Moonraker printers, real OrcaSlicer
python3 scripts/make_icons.py                          # regenerate the app icons (Pillow)
```

Credits: the Centauri Carbon connection uses [pycentauri](https://github.com/bjan/pycentauri) (Apache-2.0).
