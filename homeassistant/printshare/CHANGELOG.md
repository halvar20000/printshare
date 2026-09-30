# Changelog

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
