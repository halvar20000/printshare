# PrintShare

Send a Printables or Thingiverse link from your phone – PrintShare downloads the model, slices it with
OrcaSlicer on your Home Assistant machine and sends it to your printer. Nothing starts without your
confirmation in the app.

Supported printers: Elegoo Centauri Carbon with stock firmware (`elegoo_sdcp`), Klipper printers with
Moonraker (`moonraker`, e.g. OpenCentauri COSMOS, Voron, Sovol, Qidi), Prusa printers with PrusaLink
(`prusalink`: MK4/MK4S, MK3.9, CORE One, MINI, XL) and printers driven by OctoPrint (`octoprint`).

## Setup
1. Add your printer under **Configuration → Printers**, for example:
   ```yaml
   - name: Centauri Carbon
     type: elegoo_sdcp
     address: 192.168.1.50
   ```
   Klipper / COSMOS:
   ```yaml
   - name: Centauri COSMOS
     type: moonraker
     address: 192.168.1.60
     cosmos: true
   ```
   Prusa (PrusaLink) – the password is shown on the printer under Settings → Network → PrusaLink:
   ```yaml
   - name: Prusa MK4S
     type: prusalink
     address: 192.168.1.70
     password: abcd1234
     printer_profile: Prusa MK4S 0.4 nozzle
   ```
   OctoPrint – API key from OctoPrint Settings → Application keys:
   ```yaml
   - name: Ender 3
     type: octoprint
     address: 192.168.1.80
     api_key: 0123456789ABCDEF
     printer_profile: Creality Ender-3 V2 0.4 nozzle
   ```
   Give the printer a fixed IP address in your router. `printer_profile` is the printer name as shown in
   OrcaSlicer; quality and filament default to that printer's own OrcaSlicer defaults.
2. Start the add-on and open the **Log** tab. It shows the access token and a QR code.
3. In the PrintShare app: **Settings → Connect server → Scan QR code**. Without the app, open the
   web app via **Open Web UI** and enter the token.

## Options
| Option | Meaning |
|---|---|
| `printers` | Your printers (see above). Optional per printer: `build_plate` (Textured PEI Plate, High Temp Plate, Cool Plate, Engineering Plate, Supertack Plate), `printer_profile` / `quality_profile` / `filament_profile` (OrcaSlicer preset names, default: Centauri Carbon 0.4, 0.20mm Standard, Elegoo PLA), `api_key` (Moonraker, if required). |
| `server_url` | Address the phone uses. Empty = the IP of Home Assistant on port 8484. Use your Tailscale / VPN address to print on the go. |
| `remote_url` | Optional address away from home, e.g. your Tailscale address `http://100.x.y.z:8484`. The app switches between both automatically; it is part of the QR code. |
| `api_token` | Empty = generated once and kept. |
| `thingiverse_token` | Only for Thingiverse links. |

## Advanced
With **no printers in the options**, the add-on uses `config.yaml` from its configuration folder
(`/addon_configs/<id>_printshare/` in the Samba/SSH share) unchanged – for several printers with
custom overrides or an exported OrcaSlicer machine preset. See `config-example.yaml` in the repository.

## Notes
- Slicing needs CPU and RAM (about 1–2 GB while slicing). A Raspberry Pi 4/5 works but is slower than a PC.
- The printer must be reachable from Home Assistant in your network. Nothing is exposed to the internet;
  use a VPN (e.g. Tailscale) for access from outside.
