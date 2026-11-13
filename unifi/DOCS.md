# Home Assistant App: UniFi OS Server

**Production candidate — not yet approved for a live controller.** This is a
breaking update of the existing `unifi` app, not a second app or a release-ready
replacement. Review [production readiness](PRODUCTION_READINESS.md) first.

## Same-app update

Keep the existing repository/app identity. Installing from a different
repository or as a local app produces different private storage even if its
slug is also `unifi`. Do not uninstall the old app or move its database.

Supervisor stops the old runtime as part of an update. Its complete storage
root is mounted privately at `/lib/unifi/data`, retained through a bind alias
at `/var/lib/unifi-os-app`, and its existing `unifi/data` subdirectory is exposed
at the vendor path with another real bind mount. There is no `/data` mount or
legacy-data symlink. Existing data and settings are not rewritten by the layout
adapter. UniFi OS state lives separately under the same storage root's `uos/`.

Take and verify a **cold app-only HA backup** before an approved update. Keep an
off-host copy. The app also saves a private original-data tar outside the legacy
directory before the first MongoDB open, including possible journal recovery.
That archive is checksum-verified and never replaced.

For an existing MongoDB 3.6/4.0 database, one pre-installer script upgrades the
same directory through 3.6 → 4.0 → 4.2 → 4.4, using official MongoDB commands,
FCV checkpoints, full collection validation and clean shutdowns. Compatible
4.2/4.4 databases are not format-upgraded. Unknown formats, incomplete backups
and failed transitions stop startup; there is no automatic data rollback.

The matching official runtime is selected by an app-owned launcher. No vendor
installer, executable, inner application file or generated base unit is patched.
Container adaptations use separate systemd drop-ins. There is no backup
converter, working-copy database, automatic owner creation or import API worker.

## Vendor setup and import

Once the console is ready, use **Open Web UI** and Ubiquiti's normal setup
wizard. Its legacy import offer requires the vendor-authenticated account
path; local/offline setup does not show the same offer. Internet is required
for sign-in and downloads. The wizard owns backup export, installing a
compatible Network version, restore and owner setup.

After import, verify device IDs, sites, networks, WLANs, administrator access
and assets before permitting device reconnection. A healthy console is not
proof of a complete restore. In the observed ARM64 run, the vendor reported
successful restore and the user confirmed data loaded, but historical
statistics were not restored (`db_stat.gz` missing). A finalization HTTP 401 and
Media Server crash dump still require investigation.

## Networking

The normal candidate uses Supervisor's app network and direct port publishing;
it needs no external TCP proxy, Docker socket or deployment helper. It does
**not** isolate copied data from LAN devices: disposable-host testing requires
separate, verified incoming and outgoing isolation. See [testing](TESTING.md).

| Service           | Container port | Default host port |
| ----------------- | -------------- | ----------------- |
| UniFi OS console  | 11443/tcp      | 8443              |
| STUN              | 3478/udp       | 3478              |
| Device inform     | 8080/tcp       | 8080              |
| Remote syslog     | 5514/udp       | 5514              |
| Mobile speed test | 6789/tcp       | 6789              |
| HTTPS portal      | 8444/tcp       | 8843              |
| HTTP portal       | 8880/tcp       | 8880              |
| OS discovery      | 10003/udp      | 10001             |

The defaults retain legacy host numbers where possible, but some container
port keys changed. **Custom existing bindings are not yet proven to survive
an update.** Check them explicitly; removed SNMP/SSDP mappings are not silently
emulated. Port forwarding/device provisioning is an outstanding acceptance test.

## Settings, backups and lifecycle

The legacy `log_level`, `memory_max` and `memory_init` keys remain accepted and
stored so Supervisor does not invalidate existing options. Their effects are
**not yet applied** to the vendor runtime. Do not assume old heap limits still
work; this is a release blocker. Other Network settings belong to the native
backup/import, not to a custom adapter.

The retained `/backup` mount makes legacy external backups available; new
vendor automatic backups are not claimed to be redirected to `/backup/unifi`.
Cold HA backups must include the complete app storage root, including original
data, runtime selection and `uos/`. Backup/restore and rollback of the final
candidate still require complete acceptance testing.

Restart restores saved vendor commands/units verbatim. An interrupted initial
installation fails closed rather than reinstalling over existing Podman state.
Vendor OS upgrades are not implemented: keep OS auto-updates off. Restoring
older data is an explicit operator action using a verified matching app backup,
never an automatic overwrite or a MongoDB binary downgrade.

## Security and resources

The candidate requires cgroup v2, private PID/cgroup namespaces, `/dev/net/tun`
and outer `SYS_ADMIN`; AppArmor is currently disabled. Rootless Podman runs the
inner vendor OS. Host PID/network/DBus, host cgroup control, HA API and Docker
socket access are not requested. Outer read-only kernel SysRq protection is
checked. These protections are not a completed security review.

Allow at least 25 GB free for building/installing on the test host and sufficient
RAM/swap for the vendor preflight. Temporary installer storage is disk-backed.
Bundled MongoDB 3.6–4.4 runtimes are EOL import-compatibility tooling, not a
long-term database support promise. ARM64 is exercised; AMD64 is not yet
execution-validated. Consult the release checklist before changing this status.
