#!/bin/bash -e
# Optional printer camera on the same Pi: mediamtx (downloaded and checksum-checked by the workflow into files/) serves a
# connected Pi camera module (V2 / V3 / OV5647) as rtsp://<IP>:8554/cam - for PocketPrint3D's "Own camera". It opens the
# camera only while someone fetches a picture, so a Pi without a camera costs nothing. Own user in the "video" group.
install -m 755 files/mediamtx "${ROOTFS_DIR}/usr/local/bin/mediamtx"
install -d -m 755 "${ROOTFS_DIR}/etc/pocketprint3d-camera"
install -m 644 files/mediamtx.yml "${ROOTFS_DIR}/etc/pocketprint3d-camera/mediamtx.yml"
install -m 644 files/pocketprint3d-camera.service "${ROOTFS_DIR}/etc/systemd/system/pocketprint3d-camera.service"

on_chroot <<CHEOF
id mediamtx >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin --groups video mediamtx
systemctl enable pocketprint3d-camera.service
CHEOF
