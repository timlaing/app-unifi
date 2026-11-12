FROM ubuntu:26.04@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96

# Investigation only: native ARM64 installer, not a Home Assistant app.
ARG INSTALLER_URL=https://fw-download.ubnt.com/data/unifi-os-server/f730-linux-arm64-5.1.42-d2bca8bd-d6fc-4d20-99e5-b78235843c2f.42-arm64
# Fingerprint measured during investigation; not a vendor-published checksum.
ARG INSTALLER_SHA256=8e29bd50cde8f781ace4b85599256ef62c02723bdc751044d4db90a087fb5207

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl dbus dbus-user-session file iproute2 \
        passt podman procps python3 slirp4netns systemd systemd-sysv uidmap \
        xz-utils \
    && mkdir -p /root/investigation \
    && curl -fL --retry 2 "${INSTALLER_URL}" \
        -o /root/investigation/unifi-os-server-5.1.42-arm64.run \
    && echo "${INSTALLER_SHA256}  /root/investigation/unifi-os-server-5.1.42-arm64.run" \
        | sha256sum --check \
    && chmod +x /root/investigation/unifi-os-server-5.1.42-arm64.run

COPY permissions-entrypoint.sh /usr/local/bin/unifi-lab-permissions-entrypoint

ENV container=docker
STOPSIGNAL SIGRTMIN+3
CMD ["/usr/lib/systemd/systemd"]
