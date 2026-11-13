# UniFi OS Server candidate testing and rehearsal evidence

## Scope

This candidate runs Ubiquiti's official Linux installer and services. It provides
container/systemd prerequisites, a legacy filesystem/service adapter, and one
conditional in-place MongoDB compatibility script. It does **not** make a
working-copy database, convert backups, call migration APIs, create owners,
trigger restore or write migration-completion receipts. Export, import and
setup belong entirely to Ubiquiti. The checkpoint below describes the previous
isolated test image; normal candidate networking differs, as documented in
`DOCS.md`. This final packaging change has not been deployed to either host.

**Throwaway deployment checkpoint:** this vendor-only revision is running on
the retained `a0d7b954_unifi` identity at `.103` as `5.3.3-vendor-test.3`.
The console returns HTTP 200, health passes and the vendor detector returns
`hasLegacyNet:true`. The actual Supervisor storage mount is `/lib/unifi/data`,
with a second real bind exposing the existing `unifi/data` directory there.
There is no `/data` storage mount or custom migration runtime. Installer,
updater and server executable hashes match the shipped vendor assets; generated
base units match their saved originals. No export/restore was triggered during
deployment. The vendor setup wizard owns the next step.

Recovery backup `e5f88644` contains the original 5.3.2 app/data immediately
before this internet-enabled deployment; `6a2af4ae` is also retained
with private permissions and an off-instance copy. An incomplete storage tree
left by the rollback contained only a PostgreSQL log; it was preserved under
`storage.preserved-from-rollback-20261113`, not deleted or overwritten. Device
access remains blocked by app-network-namespace egress filters; public IPv4
internet is now enabled for vendor authentication and downloads. A read-only,
capability-free TCP proxy exposes only the console at port 11443. Production
`.133` was not changed. Recreating the Supervisor container requires operator
network-isolation verification before its gated startup proceeds.

Recovery backup `a96dba9f` preserves the vendor-only `.2` deployment and its
original database immediately before the compatibility update. It and the
pre-upgrade `mongo-originals/originals.tar` are retained privately off-instance.
On `.103`, the `.3` update validated MongoDB/FCV 3.6, 4.0, 4.2 and 4.4 in the
same database directory, then restarted the saved vendor installation. A
disposable preflight also passed on that host's actual ARM64 CPU. Console HTTP
200, legacy detection, health, unchanged vendor hashes/base units, public
vendor HTTPS and blocked private egress were verified. The user subsequently
ran the native wizard: export succeeded, Network 10.6.109 was installed and
restored, and vendor setup reached 100%. The user confirmed data loaded fine.
Logs still reported missing `db_stat.gz` (historical statistics), a post-restore
finalization HTTP 401 and a Media Server crash dump. All services were active
afterwards. These limitations are tracked in `PRODUCTION_READINESS.md`.

The operator attaches an internet-facing bridge only after installing the
app-local filters with a temporary NET_ADMIN-only helper; the app itself does
not retain NET_ADMIN. Private/reserved IPv4 destinations and new IPv6
connections are dropped, while loopback and existing reply traffic are allowed.
No host firewall or routing policy is changed. Public DNS is configured before
startup. The extra interface is explicitly named `internet0`, leaving the
vendor's required `eth0` intact. HTTPS vendor metadata was verified from inside
the inner OS container, and a non-production private test destination was
blocked by the filter. Cloud sign-in is intentionally allowed; this no longer
claims complete cloud isolation. The actual migration still requires the
vendor UI's authenticated-account path and has not been triggered by the app.

### Ownership and overrides

All `unifi-os-*` scripts/units in this repository are our container adapter,
including `unifi-os-bootstrap.service` and `unifi-os-worker`. They are not
Ubiquiti files. The harmless outer `unifi.service` and legacy MongoDB launcher
are also ours; the vendor's real Network service remains inside Podman.

The official installer, extracted vendor executables, inner application files
and generated `uosserver.service` / `uosserver-updater.service` units are not
patched. Their container-specific settings live only in separate `.service.d`
drop-ins. The worker executes the original vendor binaries. On outer-container
recreation, saved vendor commands/units are copied verbatim, not rewritten.
Layout ordering also uses a drop-in for our own bootstrap unit.

The candidate is now packaged in `unifi/` with the original `unifi` slug. A
same-identity update retains that app's storage but also requires the same
repository identity; matching only the slug is insufficient. Do not install a
second local app or another repository and assume it can see private data.
No deployment is performed by editing this folder.

## Data mount: no legacy symlink and no `/data` mount

Supervisor supports a custom path for its always-writable private data mount:

```yaml
map:
  - type: data
    path: /lib/unifi/data
    read_only: false
```

This maps the **whole app storage root**, not its legacy controller subfolder.
The old app stores `system.properties`, `db` and `sites` under `unifi/data`
within that root. Simply mapping the root to the vendor path would leave the
properties at `/lib/unifi/data/unifi/data/system.properties`, which fails
Ubiquiti's default-layout detection.

The mount-only adapter therefore does this, without moving/replacing files:

1. Preserve the entire Supervisor storage root with a bind mount at
   `/var/lib/unifi-os-app`.
2. If retained `unifi/data/system.properties` exists, the conditional
   `unifi.service` bind mounts `/var/lib/unifi-os-app/unifi/data` onto
   `/lib/unifi/data` and remains active/exited.
3. The root alias still exposes options, the retained legacy directory and
   separate UniFi OS state. On merged-/usr Ubuntu, `/usr/lib/unifi/data` is the
   same target location; **the data target itself is not a symlink**.

The service starts no controller or database. Stopping/disabling it performs
no cleanup and leaves the mount/data available for the vendor exporter. The
helper refuses a target symlink, non-directory or unrelated non-empty target.

UniFi OS state persists under `/var/lib/unifi-os-app/uos`:

- `home`: rootless Podman storage and user configuration.
- `state`: vendor host configuration, helpers and logs.
- `bootstrap`: saved vendor commands/units and OS installation-version receipt.
- `machine-id`: stable console identity across outer-container recreation.

An OS-installation receipt is not a migration-completion signal.

## Vendor detection and migration

The original MongoDB 3.6.8 server/shell/loader/libraries are included from the
digest-pinned legacy app image. Official checksum-pinned MongoDB 4.0.28,
4.2.25 and 4.4.32 server/shell runtimes are also bundled for ARM64 and AMD64.
`/usr/lib/unifi/bin/mongod` is a regular executable launcher for the retained
database's selected runtime; it performs no conversion itself. The `unifi`
system account supports the vendor's ownership operations. No staging database,
Python driver, backup converter or custom import trigger is included.

Before either installing or restarting the vendor services,
`unifi-os-prepare-mongo` opens the existing `/lib/unifi/data/db` locally and
checks the server version and FCV. Compatible 4.2/4.4 databases are not
format-upgraded. A legacy 3.6/4.0 database is upgraded in place through
3.6 → 4.0 → 4.2 → 4.4 using official FCV commands, full collection validation
and clean shutdowns. Supervisor already stops the old app during an update;
there is no additional controller-stop step.

The first cold open is preceded by a private, verified tar of the entire legacy
data directory at `/var/lib/unifi-os-app/mongo-originals/originals.tar`, outside
that directory. This also protects against journal recovery writes during
inspection. The archive is never replaced; its checksum is verified on repeat
starts. An incomplete backup or failed hop blocks vendor startup. Rollback is
an operator action, never an automatic overwrite of a partially upgraded DB.
`mongo-runtime` records only the executable to use on restart; MongoDB's FCV is
the upgrade checkpoint. The binary selection is saved before the next open so
an interrupted upgrade cannot restart the database with an older binary.
Unsupported server/FCV combinations fail closed. These EOL binaries are legacy
import tooling, not a long-term Network database upgrade policy.

ARM64 tests exercise the real binaries, an injected FCV-write failure and
resume, repeat-startup skipping, backup-integrity rejection and restoring the
original archive with 3.6. A cold-data rehearsal preserved all 102 UniFi
application collections byte-for-byte. AMD64 runtime definitions are included,
but execution remains unverified: this ARM64 build environment has no x86
emulation (`exec format error`). Do not treat it as a validated AMD64 release.

The inspected Linux 5.1.42 updater checks:

- `systemctl is-active unifi` returns 0 or 3.
- `/lib/unifi/data` is a directory.
- `/lib/unifi/data/system.properties` is a regular, readable/parseable file.
- `/usr/lib/unifi/bin/mongod` is a regular file.

The **vendor setup UI**, not our bootstrap, initiates migration. Its import
offer requires all three: the UniFi OS Server model, populated `auth.user`, and
the detected legacy flag. The local/offline account path signs out and clears
`auth.user`, so it skips this screen even when `hasLegacyNet:true`. Local
credentials alone do not exercise the shipped import-offer flow. Testing that
flow requires its authenticated account path and suitable internet access;
device/cloud isolation must be deliberately reviewed, not silently removed.

When those UI guards pass, it presents **Import Your Existing UniFi Network**, and on
**Next** requests the native backup and restore/setup flow. It also permits
**Continue Without Importing**. Detection is queried on page load; reload a
page opened before the services/layout were ready.

The updater sandbox permits Unix/TCP networking, legacy-directory writes,
temporary export files and rootless Podman upload, with limited capabilities
and kernel protections. Its previous Unix-only restriction blocked native
export and has been removed. No replacement updater or custom import worker
is started. Leave OS auto-updates off; OS-version changes remain unsupported.

The unchanged exporter's Rust driver requires MongoDB 4.2 or newer. Prior
controlled export tests succeeded with 4.4; the small in-place preparation step
now addresses that boundary without replacing the vendor migration flow.
Detection, a healthy UI and database preparation are not proof of completed
import: actual backup/restore and retained configuration still need verification.

## Safety and prerequisites

Use only a disposable host with a verified app-only recovery backup. Stop the
old runtime before any same-identity update. The vendor may open the retained
database for writes and stop/disable `unifi.service`; this app no longer makes
an immutable migration clone. Never expose a live database from another app.

Keep copied real data isolated from devices and cloud services. Disabled
device-facing ports prevent incoming adoption/inform but do not block outgoing
traffic. Network isolation is an operator deployment requirement, not custom
migration logic. Do not restore/reset HA, delete backups or forget devices to
recover a migration test.

Security concessions:

- Outer `SYS_ADMIN`, `/dev/net/tun`, AppArmor disabled for this experiment.
- Private PID/cgroup namespaces and cgroup v2 are mandatory.
- Outer Docker `/proc` protections and read-only SysRq are retained.
- Installer/runtime preparation uses separate worker mount namespaces. The
  long-running OS service drops to UID 1001 before execution.
- Outer `MKNOD`, `NET_RAW`, `AUDIT_WRITE` and `SETFCAP` are dropped.
- No Docker socket, host PID/network/DBus, or HA API access is requested.

Ubuntu 26.04, architecture-matched installers and bundled legacy runtime are
used. Native ARM64 testing is available; AMD64 and complete HA lifecycle tests
remain gates. Provide at least 25 GB free for builds/install and sufficient RAM
and swap. `/tmp` is disk-backed (`tmpfs:false` and masked `tmp.mount`) to avoid
the installer's free-space check exceeding half of a small host's RAM.

## Disposable-host candidate testing

1. Use an explicitly prepared same-repository update on a throwaway host; take
   a verified app-only recovery backup first. Do not deploy to a live controller.
2. Keep device ports disabled, automatic boot disabled, and block outgoing
   private-LAN traffic with independently verified namespace-local filters.
   Public internet is needed for the authenticated vendor import path.
3. Use the optional image startup gate for copied real data. Its authorization
   is consumed once: every restart/recreation needs fresh filter verification.
   The candidate's normal image does not contain this lab-only marker or proxy.
4. Start it, allow up to 15 minutes for installation, and inspect its logs.
   Open the configured console host port; a self-signed certificate is expected.
5. For retained legacy data, complete the vendor import/owner wizard and check
   its actual result. A healthy console or a successful detection is not proof
   of import or data preservation.

The installer runs only after systemd is available. It saves the vendor units,
commands and installed OS version. A subsequent boot restores those pieces
instead of installing over existing/partial Podman state. Interrupted initial
installation deliberately fails closed for inspection, not blind reinstall.

## Checks before accepting a result

- Confirm the target Network version can restore the source version.
- Verify source sites, device IDs, networks, WLANs, profiles, users and assets.
- Check the native per-application restore result and owner/login access.
- Verify statistics/legacy administrator permissions separately; do not assume
  the native backup preserves either.
- Verify restart, outer recreation, cold HA backup/restore and scoped rollback.
- Test device reconnection/provisioning only during an approved deliberate
  cutover. The HTTPS portal container port changes to 8444; the default
  externally accessible host port remains 8843.

Detailed historical research remains in the private off-repository research
workspace; its removed custom pipeline is not the current implementation.
