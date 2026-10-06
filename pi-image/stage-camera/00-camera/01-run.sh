#!/bin/bash -e
# PocketPrint3D camera on Raspberry Pi OS Lite: mediamtx (downloaded and checksum-checked by the workflow into files/)
# serves the camera module as RTSP on port 8554. Runs as its own user in the "video" group.
install -m 755 files/mediamtx "${ROOTFS_DIR}/usr/local/bin/mediamtx"
install -d -m 755 "${ROOTFS_DIR}/etc/pocketprint3d-camera"
install -m 644 files/mediamtx.yml "${ROOTFS_DIR}/etc/pocketprint3d-camera/mediamtx.yml"
install -m 644 files/pocketprint3d-camera.service "${ROOTFS_DIR}/etc/systemd/system/pocketprint3d-camera.service"
install -m 644 files/20auto-upgrades "${ROOTFS_DIR}/etc/apt/apt.conf.d/20auto-upgrades"
install -m 644 files/motd "${ROOTFS_DIR}/etc/motd"

on_chroot <<CHEOF
id mediamtx >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin --groups video mediamtx
systemctl enable avahi-daemon.service pocketprint3d-camera.service
CHEOF
