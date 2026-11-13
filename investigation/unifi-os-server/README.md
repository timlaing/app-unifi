# UniFi OS Server installation investigation

Investigated on 2026-11-12 for upstream issue
[hassio-addons/app-unifi#676](https://github.com/hassio-addons/app-unifi/issues/676).
This is an isolated experiment, not a supported Home Assistant app.

**Historical results only.** For the current test implementation use
[the candidate testing instructions](../../unifi/TESTING.md). Earlier privileged/reduced
lab containers relaxed outer SysRq protections; do not resume them or use
the old commands as deployment instructions. See the security correction in
[PERMISSIONS.md](PERMISSIONS.md).

## Outcome

The official UniFi OS Server 5.1.42 ARM64 installer completed on Ubuntu
26.04.1 LTS inside Docker Desktop. The Web UI returned HTTP 200, the inner
container passed its health check, and the Network service became active.
An outer-container restart recovered the Web UI and both outer services.

Ubiquiti's [self-hosting requirements][requirements] specify Ubuntu 24.04 or
later, so 26.04 falls within the published OS range. This does **not** imply
vendor support for installation inside Docker; the same article explicitly
rejects a standalone Docker/Podman distribution.

## Environment

- Docker Desktop 29.9.3, ARM64 Linux VM, kernel 7.0.14-linuxkit.
- Ubuntu 26.04 image digest:
  `sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96`.
- Podman 5.7.0, systemd 259.9, glibc 2.43, slirp4netns 1.3.3.
- UniFi OS Server 5.1.42; bundled image `uosserver:c9603dec9010`.
- Bundled UniFi Network package: `10.5.67-35187-1`.
- 4 GiB container memory, four CPUs, private cgroup namespace.
- No published Docker ports, host networking, Docker socket, or host-directory
  mounts. Podman's forwarded ports remain inside the outer Docker container.

## Experiments

See [reduced-permissions results](PERMISSIONS.md) for the follow-up: installation
also succeeds without full Docker privileged mode, adding only `SYS_ADMIN`
to a reduced baseline with explicit TUN access and private-mount preparation.

| Configuration                                                                            | Observed result                                                                                                                                           |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Default Docker permissions, sleep as PID 1                                               | Installer fails at `loginctl enable-linger uosserver`: systemd is not PID 1. `podman info` separately fails with `cannot clone: Operation not permitted`. |
| Default Docker permissions, systemd as PID 1, `/run` tmpfs                               | Outer container exits with code 255; no useful console logs captured.                                                                                     |
| Privileged, systemd PID 1, storage in writable Docker layer                              | Installer fails loading image: overlay is unsupported over overlayfs without a mount program.                                                             |
| Above plus `fuse-overlayfs` and `dbus-user-session`                                      | Image loads, but inner executables fail with `Invalid argument`; switching crun to runc also fails. The precise cause was not established.                |
| Privileged, systemd PID 1, Docker named volume at `/home/uosserver`, `dbus-user-session` | Installation succeeds without fuse-overlayfs; Web UI HTTP 200, inner health check passes, Network service active.                                         |

The successful volume uses ext4. `dbus-user-session` brings in
`libpam-systemd`, needed for the lingering user's runtime directory and bus.
Installing systemd alone with `--no-install-recommends` was insufficient.

A 2,048 PID limit was hit during application startup (`pids.events` reported
39 hits). The limit was raised to 8,192 before testing outer-container restart.
Transient connection resets and an `activating` Network service were observed
during restart warm-up; readiness must not be inferred from open TCP ports alone.

## Reproduce on ARM64

The Dockerfile captures the successful prerequisites and installer. The image
was built and a second, clean installation completed successfully using it.
The commands below were tested; `unifi-os-lab` and its volume are retained
locally, so reuse them with `docker start unifi-os-lab`, or choose fresh names
for another installation. All investigation containers were stopped afterwards.

**Security:** `--privileged` substantially weakens isolation. Use only a
disposable Docker environment, with explicit approval. This is not evidence
that these privileges are the minimum required. Do not use real backups or
adopt real devices during this experiment.

```sh
docker build --platform linux/arm64 -t unifi-os-lab:26.04 investigation/unifi-os-server
docker run -d --name unifi-os-lab --platform linux/arm64 \
  --privileged --cgroupns=private --memory=4g --cpus=4 --pids-limit=8192 \
  --mount type=volume,source=unifi-os-lab-home,target=/home/uosserver \
  --tmpfs /run --tmpfs /run/lock unifi-os-lab:26.04
docker exec unifi-os-lab /root/investigation/unifi-os-server-5.1.42-arm64.run --non-interactive
docker exec unifi-os-lab systemctl is-active uosserver.service uosserver-updater.service
docker exec unifi-os-lab curl -kfsS -o /dev/null -w '%{http_code}\n' https://127.0.0.1:11443/
docker exec unifi-os-lab runuser -u uosserver -- env XDG_RUNTIME_DIR=/run/user/1001 podman healthcheck run uosserver
docker stop -t 150 unifi-os-lab
```

The UID in the final health command is 1001 in the tested image; resolve it
with `id -u uosserver` if the base image changes. The image must not install
UniFi during `docker build`, since the official installer requires live systemd.
The checksum in the Dockerfile is an observed fingerprint, not a vendor signature.

## Architecture and persistence

The installer creates an outer rootless Podman user, `uosserver`, with lingering
enabled; outer `uosserver.service` and root-owned `uosserver-updater.service`;
and a single bundled inner container running systemd and multiple services.
It also installs host-side discovery and networking helpers.

- Host-side settings, binaries, and logs: `/var/lib/uosserver`.
- Host commands: `/usr/local/bin/uosserver` and `uosserver-purge`.
- Rootless container storage and named volumes:
  `/home/uosserver/.local/share/containers` (approximately 2.4 GiB after install).
- Inner persistent volumes: `/persistent`, `/var/log`, `/data`, `/srv`,
  `/etc/rabbitmq/ssl`, `/var/lib/mongodb`, and `/var/lib/unifi`.
- Outer Web UI: HTTPS 11443 forwarded to inner HTTPS 443.
- Installer port map includes TCP 5671, 6789, 8080, 8444, 8880-8882, 9543,
  28082; UDP 3478, 5514, 10003; and loopback-only TCP 11084.

The experiment's named volume alone is **not** a complete backup. Container
recreation and full backup/restore have not been tested; `/var/lib/uosserver`
and regenerated runtime/user state must also be accounted for.

## Implications for issue 676

1. Docker nesting is technically possible in this environment, despite not
   being a vendor-supported packaging model. Default Docker isolation fails.
2. Minimum capabilities, devices, AppArmor/seccomp rules, and cgroup delegation
   still need testing on actual Home Assistant OS. This Docker Desktop result
   does not establish Supervisor compatibility.
3. UniFi OS Server 5.1.42 bundles Network 10.5.67, older than this repository's
   Network 10.6.109. Do not migrate a newer backup into this older application;
   establish a compatible destination Network version first.
4. Device discovery/adoption, portal traffic, remote access, authentication,
   updates, HA integration, backup restoration, and real migration remain untested.
5. A successor would need different supervision, lifecycle, storage, ports,
   resource sizing, and upgrade semantics. Do not replace the existing app yet.

[requirements]: https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi
