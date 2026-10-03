#!/bin/bash -e
# PocketPrint3D bridge on Raspberry Pi OS Lite: the bridge image (saved by the workflow into files/), first-boot and
# update services, the helper commands. Nothing is started here - the chroot has no Docker daemon.
D="${ROOTFS_DIR}/opt/pocketprint3d-bridge"
install -d -m 755 "${D}" "${D}/config" "${D}/data"
install -m 644 files/bridge-image.tar "${D}/bridge-image.tar"
for f in pocketprint3d-firstboot pocketprint3d-start pocketprint3d-update pocketprint3d-code; do
	install -m 755 "files/${f}" "${ROOTFS_DIR}/usr/local/bin/${f}"
done
for u in pocketprint3d-firstboot.service pocketprint3d-update.service pocketprint3d-update.timer; do
	install -m 644 "files/${u}" "${ROOTFS_DIR}/etc/systemd/system/${u}"
done
# small logs: the SD card should last for years
install -d "${ROOTFS_DIR}/etc/docker"
install -m 644 files/daemon.json "${ROOTFS_DIR}/etc/docker/daemon.json"
# security updates of the system by themselves (the bridge itself: pocketprint3d-update.timer)
install -m 644 files/20auto-upgrades "${ROOTFS_DIR}/etc/apt/apt.conf.d/20auto-upgrades"
install -m 644 files/motd "${ROOTFS_DIR}/etc/motd"

on_chroot <<CHEOF
systemctl enable docker.service avahi-daemon.service pocketprint3d-firstboot.service pocketprint3d-update.timer
CHEOF
