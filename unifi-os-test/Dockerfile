FROM ubuntu:26.04@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Experimental image: apt dependencies are not pinned, installers are.
# hadolint ignore=DL3008
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl dbus dbus-user-session iproute2 \
        passt podman procps slirp4netns systemd systemd-sysv uidmap \
        xz-utils \
    && groupadd --gid 1001 uosserver \
    && useradd --uid 1001 --gid 1001 --home-dir /home/uosserver \
        --no-create-home --shell /bin/bash uosserver \
    && ln -s /data/uos/home /home/uosserver \
    && ln -s /data/uos/state /var/lib/uosserver \
    && mkdir -p /opt/unifi-os \
    && case "$(dpkg --print-architecture)" in \
        arm64) \
            url="https://fw-download.ubnt.com/data/unifi-os-server/f730-linux-arm64-5.1.42-d2bca8bd-d6fc-4d20-99e5-b78235843c2f.42-arm64"; \
            checksum="8e29bd50cde8f781ace4b85599256ef62c02723bdc751044d4db90a087fb5207" ;; \
        amd64) \
            url="https://fw-download.ubnt.com/data/unifi-os-server/5172-linux-x64-5.1.42-12e9e3cf-8f8b-4e54-928c-76b80a10c8a4.42-x64"; \
            checksum="f6111e9396a42c74016f5dde9b01fbef486a6fe69efe137935e6e38b7c22f94d" ;; \
        *) echo "Unsupported architecture" >&2; exit 1 ;; \
    esac \
    && curl -fLsS --retry 2 "${url}" -o /opt/unifi-os/installer \
    && echo "${checksum}  /opt/unifi-os/installer" | sha256sum --check \
    && chmod 0755 /opt/unifi-os/installer \
    && echo "5.1.42" > /opt/unifi-os/version \
    && systemctl mask systemd-modules-load.service systemd-udevd.service \
        systemd-udevd-control.socket systemd-udevd-kernel.socket \
        systemd-tmpfiles-setup-dev.service systemd-tmpfiles-setup-dev-early.service \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Checksums above are measured download fingerprints, not vendor signatures.
COPY rootfs /
RUN chmod 0755 /usr/local/bin/unifi-os-* \
    && systemctl mask console-getty.service getty.target getty@.service \
        serial-getty@.service systemd-remount-fs.service systemd-pstore.service \
    && systemctl enable unifi-os-bootstrap.service unifi-os-log.service

ENV container=docker
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/usr/local/bin/unifi-os-entrypoint"]

HEALTHCHECK --start-period=15m --interval=30s --timeout=20s --retries=3 \
    CMD ["/usr/local/bin/unifi-os-health"]

ARG BUILD_ARCH
ARG BUILD_VERSION=0.1.0
LABEL \
    io.hass.name="UniFi OS Server (experimental test)" \
    io.hass.description="Disposable-host UniFi OS Server experiment" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.source="https://github.com/timlaing/app-unifi"
