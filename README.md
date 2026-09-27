# PrintShare (P0 prototype)

Send a **Printables** or **Thingiverse** link from your phone. PrintShare downloads the model, slices it with **OrcaSlicer** on your own server, uploads the G-code to your printer and starts the print. It's a self-hosted "Bambu Handy" for everyone else.

Supported in P0:

| Printer | Firmware | Type in config |
|---|---|---|
| Elegoo Centauri Carbon | stock Elegoo (SDCP) | `elegoo_sdcp` |
| Elegoo Centauri Carbon | OpenCentauri **COSMOS** (Klipper) | `moonraker` + `machine_preset: cosmos` |
| Any Klipper printer | Moonraker | `moonraker` |

```
Phone ──link──▶ PrintShare (Docker on Unraid) ──▶ Printables / Thingiverse
                     │  OrcaSlicer (command line, same profiles as the desktop app)
                     └──▶ Centauri Carbon (SDCP)  /  Klipper (Moonraker)
```

---

## 1. Install on Unraid

On the Unraid console as root (`ssh unraid`). When pasting several lines into the web terminal, press **Enter** afterwards.

```bash
# 1. Get the code (skip if you already have the project share /mnt/user/AI/Projects/3dprintinghandy)
mkdir -p /mnt/user/appdata/printshare/src /mnt/user/appdata/printshare/data
cd /mnt/user/appdata/printshare/src
curl -fL -o printshare.tar.gz https://github.com/halvar20000/printshare/archive/refs/heads/main.tar.gz
tar xzf printshare.tar.gz --strip-components=1 && rm printshare.tar.gz

# 2. Build the image (~5 min the first time; downloads OrcaSlicer 2.4.2)
docker build -t printshare:0.1 .

# 3. Configuration
cp config.example.yaml /mnt/user/appdata/printshare/config.yaml
openssl rand -hex 24          # -> use as api_token
nano /mnt/user/appdata/printshare/config.yaml

# 4. Run
docker run -d --name printshare --restart unless-stopped \
  -p 8484:8484 \
  -v /mnt/user/appdata/printshare:/config \
  -v /mnt/user/appdata/printshare/data:/data \
  printshare:0.1
```

Then open `http://<unraid-ip>:8484`, enter the token under **Settings**, paste a link and press **Print**.

Update later: fetch the code again (step 1, `curl` + `tar`), rebuild, `docker rm -f printshare`, run step 4 again. The configuration in `/mnt/user/appdata/printshare` stays.

## 2. Configure your printer

Edit `config.yaml`. Keep only your own printer block:

* **Thomas (stock firmware):** `type: elegoo_sdcp` with `host:` set to the printer's IP. Give the printer a fixed DHCP lease.
* **Dominique (COSMOS):** `type: moonraker` with `url:` set to the same address you use for Mainsail, plus `machine_preset: cosmos`.
  - The preset replaces Elegoo's start/end G-code with `PRINT_START … / PRINT_END`, because COSMOS ≥ 26.07 deliberately e-stops on the old `M729`/`M8213` commands.
  - Best practice: import the official [COSMOS OrcaSlicer profile](https://cloud.orcaslicer.com/b/3fad3c38f25f) in OrcaSlicer on the desktop and export the printer preset as JSON. Copy it to `/mnt/user/appdata/printshare/profiles/` and set `machine_file: /config/profiles/<file>.json`.

To list the preset names you can use:

```bash
docker exec printshare printshare presets process -s "Elegoo CC"
docker exec printshare printshare presets filament -s "@ECC"
```

## 3. Test from the command line first

```bash
docker exec printshare printshare printers
docker exec printshare printshare status -p cc-thomas
docker exec printshare printshare files "https://www.printables.com/model/3161-3d-benchy"
docker exec printshare printshare print "https://www.printables.com/model/3161-3d-benchy" -p cc-thomas --no-start
```

`--no-start` only uploads the file, so you can check it on the printer screen before the first real print. `--slice-only` doesn't contact the printer at all; the G-code ends up in `/mnt/user/appdata/printshare/data/gcode/`.

## 4. The app on your phone

**Native app (iOS + Android):** see [`mobile/README.md`](mobile/README.md). Connect it by scanning the pairing code:

```bash
docker exec printshare printshare pair --url http://<server-ip>:8484
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
POST   /api/jobs   {"link", "printer", "file", "options": {"filament", "process", "bed_type",
                    "supports": "off|normal|tree", "brim": "auto|off|outer", "infill": 20, "walls": 3}}
GET    /api/jobs   |   GET /api/jobs/<id>   |   DELETE /api/jobs/<id>
POST   /api/jobs/<id>/send   {"start": true, "confirm": true}      # confirm is required to start
GET    /api/printers/<id>/status
POST   /api/printers/<id>/control   {"action": "pause|resume|cancel", "confirm": true}
POST   /api/print  {"link", "printer", "file", "start"}   # one-shot slice + send (CLI, shortcuts)
```

## Notes and limits (P0)

* **Printables** has no official API. PrintShare uses the website's own endpoint, one model at a time and only on the user's behalf; files are never stored for others. **Thingiverse** needs an app token from thingiverse.com/developers.
* Models with several files: the app asks which file to use; on the command line use `--file N`. A single 3MF is preferred automatically.
* 3MF project files from Bambu Studio are sliced with *your* printer profile. Their plate layout is kept, but print settings saved inside the 3MF are not used.
* Plate thumbnails are empty, because the server has no graphics output.
* Jobs are kept in memory only (last 50) and are lost when the container restarts. Slicing runs one job at a time (`max_parallel_slices`).

## Development

```bash
pip install -e ".[dev]"
ORCA_ROOT=/path/to/extracted/OrcaSlicer pytest -q     # fake SDCP + Moonraker printers, real OrcaSlicer
python3 scripts/make_icons.py                          # regenerate the app icons (Pillow)
```

Credits: the Centauri Carbon connection uses [pycentauri](https://github.com/bjan/pycentauri) (Apache-2.0).
