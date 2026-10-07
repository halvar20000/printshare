# Changelog

## 0.40.0
- Prints started elsewhere (e.g. sent from OrcaSlicer straight to the printer) now show up in the app's job list and
  are followed until they finish.
- Time-lapse "always": record every print where the printer has a camera, including prints started elsewhere (setting
  in the app; own servers and bridges).

## 0.39.0
- Choose where your spools live: in the PocketPrint3D cloud or in your own Spoolman. The server and your bridges follow
  the choice, so NFC readers and slot assignments work with both.
- Copy all spools from your Spoolman into the cloud with one tap (chip links and slot assignments move along).
- Home servers and bridges can read spools from Spoolman (`PRINTSHARE_SPOOLMAN_URL` or set from the app) and tell the
  printer what is in a slot.

## 0.38.0
- Spools by NFC chip: link any chip (sticker, Bambu spool tag, OpenPrintTag) to a spool once - from then on the app
  recognises the spool when you hold the phone to it.
- Spool per slot is kept on the server (shared by the app, the web app and NFC readers).
- NFC reader at the printer: a reader in the spool holder can report which spool sits in which slot (key per printer).

## 0.37.0
- Filament menu for Bambu Lab printers: load and unload filament, and set what is in each AMS tray and on the external
  spool (material and colour) - from the app, also through a bridge.

## 0.36.1
- Own camera: add `#rotate=90` (or 180, 270) to the camera address to turn the picture - for a camera mounted on its side.

## 0.36.0
- Own camera per printer: use an IP camera (RTSP, e.g. Tapo or Reolink) or a webcam address instead of the printer's
  built-in camera - for the picture in the app, time-lapse and failure detection. In the app for printers behind a
  bridge (sent encrypted to it), on your own server as `camera_url` in config.yaml.

## 0.35.2
- Bambu Lab: camera pictures (P1S/P1P/A1) on the printers tab, full screen and for time-lapse.
- Bambu Lab: a print the printer doesn't take (e.g. without LAN-only mode) now shows a clear message instead of
  "started".

## 0.35.1
- Printer search through a bridge: finds printers also when the server runs in Docker's bridge network without the
  "LAN for the printer search" setting (the app tells it the home Wi-Fi), and is faster.

## 0.35.0
- Bambu Lab printers (P1S, P1P, X1, A1) in LAN-only mode with developer mode: status, AMS trays as slots (choose the
  tray per colour), pause/resume/cancel, temperatures, fans, light, speed, and printing (upload + start). Your server or
  bridge finds them on the network; enter the access code shown on the printer. Camera follows later.

## 0.34.0
- Ready-made Raspberry Pi image for the bridge: write it to an SD card, plug in the network cable and power - the app
  finds the bridge on your Wi-Fi and connects it with one tap (Settings → Advanced → Print from anywhere → "Found on
  your Wi-Fi"). No default password, no SSH. Guide: https://pocketprint3d.com/bridge/
- Bridge containers show a status page with the pairing code at their own address (only on the home network).

## 0.33.0
- Jobs follow their print: "Printing" → "Printed" or "Cancelled" when the printer is done, instead of staying on
  "Started". Printed jobs can be printed again. Also for prints the phone sends on the Wi-Fi.
- Spool bookings: a "finished" shown by the printer right after the start (the previous run of the same file) is no longer
  taken as the end of the new print.

## 0.32.0
- Time-lapse: switch on "Record a time-lapse" before printing (off by default) and your server takes one camera picture
  per layer (every 30 s for printers without layer information) and makes a short MP4 when the print is over - watch and
  download it in the app or browser. Works on your own server and through a bridge (the video goes to your cloud job).
  Needs the printer's camera.

## 0.31.0
- PocketPrint3D Cloud: send from OrcaSlicer on your computer. Add PocketPrint3D as a physical printer (host type
  Octo/Klipper) with the address and key from the app (printer → "Send from OrcaSlicer"). The G-code shows up as a job
  with print time, filament and preview; "Upload and print" starts it right away on printers behind a bridge and books
  the spool used last.

## 0.30.0
- Jobs survive a restart or an update: sliced models stay in the job list and can still be sent. A job that was being
  sliced or sent at that moment says so. Old jobs clean up after themselves: at most 50 (per account in the cloud), none
  older than 14 days, with their G-code.

## 0.29.0
- PocketPrint3D Cloud: spool bookings live in the account. With spools kept in the cloud, the used filament is booked when
  the print finishes - also for prints started in the browser, and for printers behind a bridge even when no app is
  open. Web app texts for the desktop.

## 0.28.0
- PocketPrint3D Cloud in the browser: app.pocketprint3d.com is the same app as on the phone, with the same account -
  search, prepare, slice, preview, spools, and printing through a bridge. Drop a model file onto the page to start.
  (Self-hosted servers: no change.)

## 0.27.0
- Print from anywhere: new add-on option "Connect to PocketPrint3D Cloud" (bridge mode). The add-on's web page shows the
  pairing code and the connection under Settings → Print from anywhere.
- New slim image `ghcr.io/halvar20000/printshare-bridge` for people who only want the bridge (no slicing at home).

## 0.26.0
- PocketPrint3D Cloud: printers of a connected bridge show up in the account by themselves, and status, pause/resume/
  cancel, temperatures, fans/light, camera pictures, power and sending a print go through the bridge - from anywhere.
  Printers can also be found and added at home through the bridge.

## 0.25.0
- Bridge mode: your PocketPrint3D server can connect to a free PocketPrint3D Cloud account, so the app reaches your
  printers from anywhere - only an outgoing connection, no port forwarding. Switch it on (Unraid: "Connect to
  PocketPrint3D Cloud"), enter the pairing code from the log in the app. Printer passwords and keys added through the
  app are encrypted for your server only; the cloud can't read them. (The app side follows in the next app version.)

## 0.24.0
- PocketPrint3D Cloud: groundwork for bridges at home (docs/BRIDGE.md) - pairing with a code, bridge tokens and the
  connection the bridge keeps open to the cloud. Nothing changes for self-hosted servers yet; the bridge mode itself
  comes in the next versions.

## 0.23.0
- AI failure detection with Obico's ML API (runs as its own container): while printing, camera pictures are checked;
  a likely failure shows in the app with the picture and can pause the print automatically. Works for every printer
  with a camera, also the Centauri Carbon with stock firmware. Set up in the app (Settings → AI failure detection).

## 0.22.0
- Exact print times for Klipper printers (e.g. COSMOS): after slicing, klipper_estimator recalculates the time with the
  printer's own speed and acceleration limits (often 10–20 % closer than OrcaSlicer) and corrects the progress lines,
  so Mainsail/Fluidd show the right remaining time too. Works while the printer is off once it was reached once.

## 0.21.0
- Your own Manyfold model library as a search source in the app ("Entdecken" → Manyfold): search, model pages with
  pictures, print like a Printables model. Set it up in the app (Settings → Manyfold) or with MANYFOLD_URL / MANYFOLD_TOKEN.

## 0.20.0
- Preview images in the G-code: the printer's screen (file list, print screen) shows a picture of the sliced model in
  the sizes and formats the printer profile asks for (PNG, QOI for Prusa, JPG). OrcaSlicer's command line made none.

## 0.19.0
- Filament presets from SpoolmanDB (open filament database, 67 brands) for adding spools in the app: brand → filament
  fills in name, material, colour, weight and spool weight.

## 0.18.1
- Orca Cloud import: only public bundles can be read without an Orca account (private ones only open for whitelisted,
  logged-in Orca users) - texts and the error message say so and point to exporting the presets in OrcaSlicer.

## 0.18.0
- Import OrcaSlicer profiles from an Orca Cloud share link (cloud.orcaslicer.com/b/…) – web page "Druckerprofil" card and
  app; no Orca account needed. Printer presets with `"type": "printer"` (as Orca Cloud stores them) now slice.

## 0.17.1
- MakerWorld links: the app shows the model page (pictures, creator, licence, variants) with a button to MakerWorld.
  MakerWorld only allows downloads with your own account - download the 3MF there and share it with PocketPrint3D.

## 0.17.0
- Cloud mode only: spools per account in Spoolman's API shapes (`/spoolman/api/v1/…`), for app users without a Spoolman
  at home. The self-hosted add-on is unchanged (use your own Spoolman there).

## 0.16.0
- Spoolman (for the apps): the printer status tells whether Klipper's Moonraker books the used filament in Spoolman
  itself, and AFC lanes report their spool; "send" can set Moonraker's active spool. The Android app chooses the
  spool per colour, warns when too little is left and books the filament after the print.

## 0.15.3
- Prusa printers: the quality list was empty and slicing failed ("process not compatible with printer"); both fixed
  (Prusa's presets choose their printers by condition).
- Materials also offer OrcaSlicer's printer-independent library (Generic PETG, Polymaker, eSUN, …).
- `GET /api/machines`: all OrcaSlicer printer models, for the app's model choice (Prusa, OctoPrint printers in the cloud).

## 0.15.2
- Infill pattern per print (grid, gyroid, honeycomb, …): new choice "Füllmuster" on the web page.

## 0.15.1
- The G-code download can rewrite the tool numbers for chosen AFC slots (used by the app with PocketPrint3D Cloud,
  where the phone sends the print to the printer itself).

## 0.15.0
- Groundwork for the hosted PocketPrint3D service (cloud mode, off by default): login with an e-mail code,
  separate printers, profiles, uploads and jobs per account, limits for the free service. Nothing changes for
  your own server (Unraid, Home Assistant, Docker).

## 0.14.0
- Plate options when preparing a print: **several copies** (as many as fit are arranged on the plate; the review
  says if fewer fit), **tilt** the model by 90° steps onto another side, **size** in percent and **lay flat
  automatically** per print. Works for STL, 3MF (also multicolour projects) and OBJ.

## 0.13.1
- New name: **PocketPrint3D** (formerly PrintShare) – the app, web page and add-on show the new name. Nothing
  changes for existing installations: same add-on, image, settings and pairing.

## 0.13.0
- Your own OrcaSlicer quality and material profiles: upload them like a printer profile (app: Settings →
  printer, or the web page); they appear first under "Own profiles" when preparing a print and are used for
  slicing (based on the bundled OrcaSlicer 2.4.2 profiles). Groundwork for syncing profiles from Orca Cloud.

## 0.12.0
- Switch the printer on and off through a smart plug in Home Assistant: set it up on the web page
  (Settings → "Power"), then "Switch on" appears in the app and the printer tab while the printer is off.
  Switching off asks first and is refused while a print is running. As add-on PrintShare now asks for
  access to the Home Assistant API (`homeassistant_api`), so no address or token has to be entered.

## 0.11.0
- AFC units (e.g. CANVAS on COSMOS): choose the **slot** for each colour already when preparing; the material
  profile for slicing follows the filament in that slot (can still be changed). Slots are shown in their physical
  order as "Slot 1–4" instead of "CANVAS_4 (T0)". The web page can choose the slots before sending, too.

## 0.10.3
- Upload your own OrcaSlicer printer profile on the web page too (Settings → "Printer profile"): upload a
  JSON or preset bundle for a printer, switch each printer between its standard and an uploaded profile, delete
  profiles that are no longer used.

## 0.10.2
- Connect the app without the command line: the web page (Settings → "Connect the app") shows the pairing
  QR code, the address and the token. Addresses can be edited there; the code stays hidden until you tap
  "Show QR code" because it contains the token.

## 0.10.1
- The app can show a model file in 3D before slicing (`/api/model-file`, served from the download cache).

## 0.10.0
- Printer control in the app: set nozzle/bed/chamber temperatures (with PLA/PETG presets and cool down),
  temperature history chart, fans, light and print speed. Changes that could spoil a running print ask
  for confirmation first. Centauri Carbon, Klipper/Moonraker and OctoPrint; PrusaLink shows temperatures.

## 0.9.1
- AFC lanes: each lane is shown once (AFC 1.2 has several objects per lane and a unit with the same
  name as the first lane) – checked with data from a real COSMOS + CANVAS printer.

## 0.9.0
- Printer camera in the app: thumbnail on the printers tab, fullscreen live view or still images; the
  image comes through PrintShare, so it also works away from home. Centauri Carbon, Klipper webcams,
  OctoPrint and PrusaLink cameras.

## 0.8.0
- Lane selection for AFC (e.g. CANVAS on COSMOS): the app shows the printer's lanes and lets you choose a lane
  per colour before printing, without re-slicing; an empty lane blocks the start.

## 0.7.0
- Upload your own OrcaSlicer printer profile in the app (Settings → printer). It is checked, used right away
  and kept when the add-on regenerates its configuration.

## 0.6.0
- Multicolour groundwork: colours of 3MF projects are detected, the app lets you choose a material per colour,
  slicing uses one filament per colour, filament use per colour and a colour preview.
- Model downloads are cached for a day (colour check and slicing download once).

## 0.5.0
- G-code preview in the app: every layer from above, coloured by line type, with a layer slider.
- Bed leveling on/off per print (Elegoo Centauri Carbon stock firmware).
- Download the sliced G-code (`/api/jobs/<id>/gcode`).

## 0.4.0
- New printers: Prusa via PrusaLink (MK4/MK4S, MK3.9, CORE One, MINI, XL) and any printer driven by OctoPrint.
  Set `printer_profile` to the OrcaSlicer printer name; quality and filament use that printer's defaults.

## 0.3.1
- Elegoo Centauri Carbon (stock firmware): prints now really start. The printer acknowledged a start sent
  right after the upload but ignored it; PrintShare now waits for the file, checks that the print runs and retries.
- Optional address away from home (`remote_url`, e.g. Tailscale), included in the pairing QR code; the app
  switches between home and away automatically.

## 0.3.0
- Model search for the app: Printables (and Thingiverse with an app token), model details with images,
  license and the author's recommended settings.

## 0.2.0
- First Home Assistant add-on release: printers configured in the add-on options, pairing QR code in the log.
- Native iOS/Android app support: file uploads, pairing, printer-busy check before starting a print.
