# Changelog

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
