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
