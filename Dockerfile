# Web app (docs/WEB.md): the Expo web build of mobile/, served by the cloud at app.pocketprint3d.com. Built once on
# the build machine's own architecture - the output is plain HTML/JS for every platform.
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS webapp
WORKDIR /mobile
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile/ ./
RUN EXPO_PUBLIC_WEB_SAME_ORIGIN=1 npx expo export --platform web --output-dir /webapp && test -f /webapp/index.html

FROM ubuntu:24.04

ARG ORCA_VERSION=2.4.2
# set by buildx (amd64 | arm64); OrcaSlicer publishes AppImages for both
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PRINTSHARE_CONFIG=/config/config.yaml \
    PATH=/opt/venv/bin:$PATH

# Runtime libraries OrcaSlicer needs even in command-line mode
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 python3-venv \
        libopengl0 libglu1-mesa libgl1 libegl1 libgtk-3-0t64 libwebkit2gtk-4.1-0 \
        libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# OrcaSlicer (AppImage extracted, no FUSE needed)
RUN case "${TARGETARCH:-amd64}" in \
      amd64) f="OrcaSlicer_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage" ;; \
      arm64) f="OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V${ORCA_VERSION}.AppImage" ;; \
      *) echo "Unsupported architecture ${TARGETARCH}"; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/orca.AppImage "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${ORCA_VERSION}/$f" \
    && chmod +x /tmp/orca.AppImage && cd /opt && /tmp/orca.AppImage --appimage-extract >/dev/null \
    && mv /opt/squashfs-root /opt/orca && rm /tmp/orca.AppImage

# klipper_estimator (MIT, Annex-Engineering): exact print times for Klipper printers (printshare/klipper_time.py).
# Pinned + checksummed. Its arm build is 32-bit armv7: kept only if this machine can run it, else the feature is off.
ARG KLIPPER_ESTIMATOR_VERSION=3.7.3
RUN case "${TARGETARCH:-amd64}" in \
      amd64) f=klipper_estimator_linux; sum=6e7e3a4ff10c4f63648d4e61fa0cb868c900f7ae63a1c9c3a04920411d15dafb ;; \
      arm64) f=klipper_estimator_rpi;   sum=da6c2bed61a47960e706323b78b950a4df7500caecfea1bd450b42a6408bf79d ;; \
    esac \
    && mkdir -p /opt/klipper_estimator \
    && curl -fsSL -o /opt/klipper_estimator/klipper_estimator \
       "https://github.com/Annex-Engineering/klipper_estimator/releases/download/v${KLIPPER_ESTIMATOR_VERSION}/$f" \
    && echo "$sum  /opt/klipper_estimator/klipper_estimator" | sha256sum -c - \
    && chmod +x /opt/klipper_estimator/klipper_estimator \
    && (/opt/klipper_estimator/klipper_estimator --version \
        || { echo "klipper_estimator can't run on ${TARGETARCH} - Klipper times stay OrcaSlicer's"; rm -rf /opt/klipper_estimator; })

# Further libraries orca-slicer links against (separate layer to keep the one above cached).
# The ldd check fails the build with the complete list if anything is still missing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsm6 libice6 libsecret-1-0 libwayland-server0 libwayland-egl1 libwayland-client0 \
        libxext6 libx11-6 libxkbcommon0 libdbus-1-3 libglx0 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/* \
    && missing=$(LD_LIBRARY_PATH=/opt/orca/lib/orca-runtime:/opt/orca/bin ldd /opt/orca/bin/orca-slicer | grep "not found" || true) \
    && if [ -n "$missing" ]; then echo "Missing libraries:"; echo "$missing"; exit 1; fi \
    && /opt/orca/AppRun --help | head -1

WORKDIR /app
COPY pyproject.toml ./
COPY printshare ./printshare
RUN python3 -m venv /opt/venv && pip install --no-cache-dir .
COPY --from=webapp /webapp /opt/webapp

# Labels: OCI metadata + what Home Assistant expects from a pre-built add-on image
ARG VERSION=dev
ARG HASS_ARCH=amd64
LABEL org.opencontainers.image.title="PocketPrint3D" \
      org.opencontainers.image.description="Print Printables/Thingiverse models from your phone - self-hosted slicing with OrcaSlicer" \
      org.opencontainers.image.source="https://github.com/halvar20000/printshare" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      io.hass.name="PocketPrint3D" \
      io.hass.type="addon" \
      io.hass.version="${VERSION}" \
      io.hass.arch="${HASS_ARCH}"

VOLUME ["/config", "/data"]
EXPOSE 8484
ENTRYPOINT ["printshare"]
CMD ["serve"]
