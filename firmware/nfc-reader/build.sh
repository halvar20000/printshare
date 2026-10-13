#!/usr/bin/env bash
# Build the NFC reader firmware and one image per board for web flashing (web.esphome.io → "Install" → the .bin).
#   bash firmware/nfc-reader/build.sh     (needs PlatformIO: pip install platformio)
set -euo pipefail
cd "$(dirname "$0")"
PIO=${PIO:-pio}
OUT=${OUT:-../../releases}
mkdir -p "$OUT"
BA=$(find ~/.platformio/packages/framework-arduinoespressif32 -name boot_app0.bin | head -1)
for env in esp32s3 esp32; do
  $PIO run -e $env
  B=.pio/build/$env
  chip=$([ $env = esp32s3 ] && echo esp32s3 || echo esp32)
  boot=$([ $env = esp32s3 ] && echo 0x0 || echo 0x1000)
  size=$([ $env = esp32s3 ] && echo 8MB || echo 4MB)   # the S3 DevKit build uses the 8 MB partition table
  esptool.py --chip $chip merge_bin -o "$OUT/pp3d-nfc-reader-$env.bin" --flash_mode dio --flash_size $size \
    $boot $B/bootloader.bin 0x8000 $B/partitions.bin 0xe000 "$BA" 0x10000 $B/firmware.bin
done
ls -l "$OUT"/pp3d-nfc-reader-*.bin
