# NFC reader at the spool holder (ESP32 + PN5180)

A PN5180 reader next to the spool reports the spool's chip to PocketPrint3D (`POST /api/reader/scan`, see API.md
"Spools by NFC chip"). PocketPrint3D then knows which spool is in the printer: the print screen proposes it and books
the used filament on it. Works with OpenPrintTag (ISO 15693), NTAG / ICODE stickers and Bambu spool tags (UID only).
Firmware: `firmware/nfc-reader/` (PlatformIO, Arduino). Images: `bash firmware/nfc-reader/build.sh` →
`releases/pp3d-nfc-reader-esp32s3.bin` / `-esp32.bin`.

## Wiring

| PN5180 | ESP32-S3 DevKitC-1 | ESP32 DevKit (WROOM-32) |
|---|---|---|
| 5V | 5V | 5V (VIN) |
| 3V3 | 3V3 | 3V3 |
| GND | GND | GND |
| SCK | GPIO 12 | GPIO 18 |
| MISO | GPIO 13 | GPIO 19 |
| MOSI | GPIO 11 | GPIO 23 |
| NSS | GPIO 10 | GPIO 5 |
| BUSY | GPIO 9 | GPIO 16 |
| RST | GPIO 14 | GPIO 17 |
| IRQ, GPIO, AUX, REQ | – | – |

Short wires (< 15 cm). ESP32-S3 N16R8/N8R8: GPIO 35-37 belong to the PSRAM - not used. Reading distance 3-5 cm: mount
the antenna right at the spool (e.g. behind the spool holder, facing the spool's side with the tag).

## Flashing (no tools needed)

1. Chrome or Edge on a computer: open **web.esphome.io**, connect the board by USB (S3 DevKit: the **UART** socket),
   **Connect** → choose the port → **Install** → choose `pp3d-nfc-reader-esp32s3.bin` (or `-esp32.bin`).
2. Done after about a minute. If the board isn't found: hold **BOOT**, press **RESET**, let go of BOOT, try again.

## Setting up

1. In the app: printer → **Control** → "Spool and NFC reader" (printers with AMS / several slots: Filament screen →
   "NFC reader at the printer") → **Create key**. Note the address and the key (shown once).
2. The reader opens the Wi-Fi **PocketPrint3D-NFC**: join it with the phone, the setup page opens (otherwise
   http://192.168.4.1). Choose your Wi-Fi, enter **Reader address**, **Reader key** and the **Slot** (0 for a printer with
   one spool; Bambu AMS trays 0-15, external spool 254) → Save.
3. Put a spool with a chip in front of the reader. The LED turns green (known spool) or yellow (new chip: the app shows
   "Unknown chip seen – assign a spool" once). Status page: http://<reader IP>/. Settings again: hold BOOT for 3 s.

The reader reports a chip when it has seen it twice in a row, and again after the spool was out for 4 s. HTTPS to
api.pocketprint3d.com is checked against the Let's Encrypt roots built into the firmware; own servers over http work too.
