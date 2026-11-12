# UniFi OS Server experimental test

## Scope and safety

This is a **separate app**, slug `unifi_os_test`, for a disposable Home
Assistant OS installation. Do not install it on the host that manages your
production network. It does not provide an in-place upgrade of the existing
UniFi Network app and never mounts its data or `/backup` directory.

Security concessions:

- Requests outer `SYS_ADMIN` and access to `/dev/net/tun`.
- Explicitly disables AppArmor for this first integration test; a suitably
  constrained profile is still required before any release. Nested Podman
  also uses an unconfined AppArmor profile, rather than trying to load a
  container profile into the host's policy namespace.
- Makes its **private** cgroup mount writable. Startup refuses a shared
  cgroup namespace or non-PID-1 invocation instead of modifying host cgroups.
- Retains Docker's `/proc` protections in the outer root/systemd namespace,
  including read-only `/proc/sysrq-trigger`. Rootless runtime preparation
  occurs in a separate mount namespace, with UID dropped to `uosserver`
  before the long-running service executes. It checks that this user cannot
  write SysRq. A namespace alone does not isolate kernel-wide controls.
- Drops outer `MKNOD`, `NET_RAW`, `AUDIT_WRITE` and `SETFCAP` before systemd.
- Does not request full device access, host networking/PID/DBus, the Docker
  socket, or Supervisor/Core API access. Leave protection mode enabled.

Only HTTPS **11443** is published by default. All device-facing ports are
disabled. Leave them disabled for installation and lifecycle tests. Automatic
boot is disabled. Do not enable UI auto-updates, remote management, restore
production backups, or adopt production devices during initial testing.

Ubiquiti's requirements include Ubuntu 24.04 or later, systemd, Podman 4.9.3+
and ARM64 or x86-64. This image uses Ubuntu 26.04 and architecture-specific
5.1.42 installers. Docker packaging is still vendor-unsupported.

Use a wired test host with at least 25 GB free disk space for image builds
and installation; 8 GB total host RAM is recommended to leave headroom for
Home Assistant. The installer itself checks for 15 GB free in its home path.
Allow up to 15 minutes for first-start initialization and warm-up.

## Install as a local app

1. Check out branch `experiment/unifi-os-ha-test` on your development machine.
1. Copy the **entire `unifi-os-test` folder**, including `Dockerfile` and
   `rootfs`, into your disposable HAOS host's local-app directory via Samba or
   Terminal & SSH. On newer systems this is the `local_apps` share/mount; older
   systems call it `addons` and expose it at `/addons`.
1. In **Settings > Apps > App store** (or **Add-ons > Add-on store** on older
   versions), choose **Check for updates** from the menu.
1. Under **Local apps**, open **UniFi OS Server (experimental test)** and
   choose **Install**. There is no `image` key, so Supervisor builds locally
   for the host's architecture.
1. Keep all optional ports disabled and protection mode enabled. Choose
   **Start** and inspect the **Log** tab.
1. Wait for installation completion and open `https://<HAOS-IP>:11443` using
   **Open Web UI**. A self-signed certificate warning is expected. The UI
   appearing does not by itself prove Network has finished starting.

After editing files, refresh the app store and use **Rebuild**. On newer CLI
versions these equivalents are available:

```sh
ha apps rebuild --force local_unifi_os_test
ha apps start local_unifi_os_test
ha apps logs local_unifi_os_test
```

Older CLIs use `ha addons` instead of `ha apps`. Check `ha --help` for the
commands present on the test host. No branch has been pushed automatically;
copy local files unless you explicitly publish this branch yourself.

## Persistence and lifecycle

All authoritative state is inside this app's private `/data/uos`:

- `home`: rootless Podman images, containers, named volumes and user config.
- `state`: UniFi host settings, port maps, helpers and installer logs.
- `bootstrap`: saved vendor commands, systemd units and installation receipt.
- `machine-id`: stable per-installation identity.

The first start runs the official installer **after systemd has booted**, not
during the Docker build. Later starts restore its outer commands/units from
the receipt rather than reloading or overwriting the inner container image.
Stable UID/GID and subordinate IDs allow outer-container recreation to reuse
the same rootless storage. `/run` and the journal are transient.

The trusted, pinned root installer uses a temporary mount namespace to allow
rootless OCI initialization. Its relaxed `/proc` view is not inherited by
outer root daemons. This transient root execution and `SYS_ADMIN` remain
security concessions, not a sandbox against malicious vendor code. The
long-running worker drops its effective privileges; the updater remains in
the protected outer namespace. No test ever writes to a SysRq interface.

Interrupted installations deliberately fail on the next start rather than
reinstalling over partial Podman state. Collect logs before recovery. For a
fresh disposable test, uninstall **only this experimental app**, confirm its
test data may be removed, and install it again. Never remove the original
UniFi app or hand-edit its data to recover this experiment.

Cold Supervisor backups are configured so the nested services stop before
archiving `/data`. Actual HAOS backup/restore is still a required test; do not
treat the configuration alone as evidence that restoring is safe. Do not
clone an initialized controller for concurrent use: it would duplicate its
identity and possibly remote-access tokens.

The test refuses an OS-version mismatch rather than downgrading persisted
state. UniFi OS upgrades from its UI are disabled for this experiment: the
root updater has only Unix-socket networking and a read-only filesystem
except `/run` and its logs directory, with `SYS_ADMIN` removed. Its startup
checks that `server.conf` is not writable. It remains active because the main
service needs its local restart IPC; disabling boot activation alone would
not stop updates.

## Migration: what Ubiquiti actually documents

The [Self-Hosting UniFi guide][self-hosting] explicitly says:

> On macOS and Windows, the installer will automatically detect and offer to
> migrate your existing Network Server setup (if installed in the default
> location).

For Linux it instead says:

> On Linux, or if auto-migration doesn't occur, you can manually migrate by
> installing UniFi OS Server and using the Site Export tool.

The linked [backup/migration guide][migration] also describes downloading a
Network `.unf` backup and restoring it into the new application. Devices may
reconnect automatically once their configuration and inform endpoint are
correct; that is different from automatic installer import of Linux data.

This test app does **not** claim or implement automatic Linux migration.
Shared-IP device ports can collide with the old app, so this experiment keeps
them disabled and uses a separate UI port and private data directory.

Inspection of the Linux updater binary also found `has-legacy-net` and
`legacy-net-backup` commands referencing the standalone application's default
paths. That is evidence of backend legacy-detection/export functionality, not
proof of a documented or supported automatic Home Assistant migration. This
separate app exposes none of the old app's files to that mechanism.

**Version gate:** OS Server 5.1.42 bundles Network **10.5.67**, while this
repository's existing app installs **10.6.109**. Do not restore a newer-version
backup into this older target. Establish a compatible destination Network
version and verify migration using disposable source data first. Do not
downgrade the production source to make a backup fit.

Only after host/lifecycle tests pass, a later controlled migration test should
cover compatible `.unf` restore or site export/import, device SSH credentials,
inform-address changes, Home Assistant integration reconnection and rollback.
Ubiquiti changes the HTTPS captive portal from **8843 to 8444**. Do not forget
devices or delete the original controller until rollback has been validated.

## Home Assistant test checklist

Record the host architecture, HAOS/Supervisor versions, logs and result for
each item. No actual HAOS deployment was performed by the coding agent.

- [ ] App manifest appears in the local store on both target architectures.
- [ ] Native `aarch64` build and installation succeed.
- [ ] Native `amd64` build and installation succeed.
- [ ] App runs with protection mode enabled and without `full_access`.
- [ ] Outer `/proc/sysrq-trigger` stays read-only and the service actually
      runs as `uosserver`; verify metadata/access only, never write to SysRq.
- [ ] Bootstrap completes; UI responds; Network finishes starting.
- [ ] Existing UniFi app and its data/port settings remain unchanged.
- [ ] Stop/restart and HAOS reboot followed by a manual start recover without
      reinstalling the OS (automatic boot is deliberately disabled).
- [ ] Rebuild/recreation retains machine ID, UUID and test configuration.
- [ ] Cold app backup/restore works on the same architecture, without a
      concurrently running clone of the same controller.
- [ ] Interrupted installation and incompatible receipt/version fail safely.
- [ ] RAM, disk, PID and CPU usage leave Home Assistant responsive.
- [ ] AppArmor can be re-enabled with an appropriately restricted policy.

After these pass, separately test deliberate adoption of disposable devices,
port publishing, captive portals, compatible backup import, remote access,
application upgrades and Home Assistant integration authentication.

## Diagnostics

Installer logs persist under `/data/uos/state/logs/installer.log`. Bootstrap
and vendor-service journal messages are forwarded to the app's Log tab.
Hardware/getty services and console/kernel-log forwarding are disabled to
avoid interacting with Supervisor's host `/dev` mount.

If the container is running but unhealthy, an administrator with Docker
access on a **disposable host** can inspect its own services:

```sh
docker exec <test-container-name> systemctl status unifi-os-bootstrap.service uosserver.service
docker exec <test-container-name> /usr/local/bin/unifi-os-health
docker exec <test-container-name> journalctl -u unifi-os-bootstrap.service --no-pager
```

Names differ by Supervisor version (`app_local_unifi_os_test` or legacy
`addon_local_unifi_os_test`). Get the actual name from `docker ps`; do not
guess a production container. Inspect Supervisor logs if the app fails before
its own logs appear. Do not bypass a private-cgroup guard by enabling host
namespaces or granting broader access.

## Local validation status

The ARM64 image builds and its manifest validates against the current
Supervisor schema. Native ARM64 container installation/readiness was tested
with a persistent `/data` volume and only `SYS_ADMIN` added plus TUN access.
Both official architecture downloads were fingerprinted and verified.

Native ARM64 restart and outer-container recreation retained the machine ID
and UniFi UUID. The outer SysRq mount stayed read-only, and the actual network
service process ran as UID 1001 with no effective host capabilities. Guards
rejected missing persistent storage, shared cgroups, partial installations,
version mismatches and worker execution in the outer mount namespace.
ShellCheck and Hadolint passed. These are Docker Desktop results, not HAOS
results; cold Supervisor restore is still unvalidated.

Review checks against the pinned unit found no inherited pre/stop/reload
commands, no vendor service delegation, and an explicit updater dependency.
Podman used systemd cgroups under the separately delegated `user@1001.service`
subtree, rather than the root-owned vendor service cgroup.

The final updater sandbox stayed active and passed its read-only config check;
local restart IPC worked with AF_UNIX-only sockets and no `SYS_ADMIN` in its
capability set. Its logs directory remains writable for the vendor logger.

The local AMD64 cross-build failed executing the base image's `/bin/bash`
with `exec format error`, before any app installation commands ran. No Docker
Desktop emulation settings were changed. Native AMD64 build/runtime testing
is therefore outstanding; the AMD64 path is provided for that HAOS test.

[self-hosting]: https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi
[migration]: https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi
