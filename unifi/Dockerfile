FROM ghcr.io/hassio-addons/unifi:5.3.2@sha256:9b1b59e7fcbe4d3d016782a5f6120753cd8a20252270f99eb231c05e3f338495 AS legacy_runtime
COPY build/collect-legacy-mongo-runtime /collect-legacy-mongo-runtime
RUN bash /collect-legacy-mongo-runtime

FROM ubuntu:18.04@sha256:152dc042452c496007f07ca9127571cb9c29697f42acbfad72324b2bb2e43c98 AS upgrade_runtime
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libcurl4 libssl1.0.0 libssl1.1
COPY build/collect-mongo-upgrade-runtimes /collect-mongo-upgrade-runtimes
RUN bash /collect-mongo-upgrade-runtimes

FROM ubuntu:26.04@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Production candidate: apt dependencies are not pinned, installers are.
# hadolint ignore=DL3008
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl dbus dbus-user-session iproute2 \
        passt podman procps slirp4netns systemd systemd-sysv uidmap \
        xz-utils \
    && groupadd --gid 1001 uosserver \
    && useradd --uid 1001 --gid 1001 --home-dir /home/uosserver \
        --no-create-home --shell /bin/bash uosserver \
    && groupadd --system unifi \
    && useradd --system --gid unifi --no-create-home \
        --home-dir /usr/lib/unifi --shell /usr/sbin/nologin unifi \
    && mkdir -p /var/lib/unifi-os-app /usr/lib/unifi/data \
    && ln -s /var/lib/unifi-os-app/uos/home /home/uosserver \
    && ln -s /var/lib/unifi-os-app/uos/state /var/lib/uosserver \
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
        systemd-tmpfiles-setup-dev.service systemd-tmpfiles-setup-dev-early.service tmp.mount \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Checksums above are measured download fingerprints, not vendor signatures.
COPY --from=legacy_runtime /legacy-runtime /opt/unifi-legacy-mongo
COPY --from=upgrade_runtime /upgrade-runtimes /opt/unifi-mongo
COPY rootfs /
RUN chmod 0755 /usr/local/bin/unifi-os-* /usr/lib/unifi/bin/mongod \
    && systemctl mask console-getty.service getty.target getty@.service \
        serial-getty@.service systemd-remount-fs.service systemd-pstore.service \
    && systemctl enable unifi-os-bootstrap.service unifi-os-log.service unifi.service

ENV container=docker
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/usr/local/bin/unifi-os-entrypoint"]

HEALTHCHECK --start-period=15m --interval=30s --timeout=20s --retries=3 \
    CMD ["/usr/local/bin/unifi-os-health"]

ARG BUILD_ARCH
ARG BUILD_VERSION=6.0.0-dev
LABEL \
    io.hass.name="UniFi OS Server" \
    io.hass.description="UniFi OS Server same-app upgrade candidate" \
    io.hass.type="addon" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.source="https://github.com/timlaing/app-unifi"
