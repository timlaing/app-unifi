# Reduced-permissions investigation

Tested 2026-11-12 on the same Ubuntu 26.04 ARM64 / Docker Desktop environment
as [the installation investigation](README.md).

## Findings

**Security correction:** the original proc-only experiment also removed the
outer `/proc/sysrq-trigger` protection. That can expose kernel-wide reboot
controls to host-mapped root; private mount namespaces do not isolate SysRq.
Do not resume the old permission-test containers. The archived entrypoint now
retains that protection and is not a working deployment recipe. Use the
separate `unifi-os-test` app, which keeps outer protections and prepares
rootless execution in worker namespaces instead. Historical results below
describe capability feasibility, not a release-ready security boundary.

**The only additional outer-container capability needed in the successful
tests was `SYS_ADMIN`. Outer `MKNOD` was explicitly dropped.** This is a
minimum addition to Docker's baseline, not proof that all other default
capabilities can be dropped. Real device adoption and updates were not tested.

The reduced-defaults test dropped `MKNOD`, `NET_RAW`, `AUDIT_WRITE`, and
`SETFCAP`, corresponding to the Supervisor's current optional capability
reduction. Installation, HTTP 200, application health and an active Network
service were verified without them. Outer `NET_ADMIN`, `SYS_MODULE`, BPF,
host namespaces, the Docker socket and full device access were not requested.
The inner rootless container still receives its own capabilities inside its
user/network namespaces; these are not host-level outer capabilities.

The final `unifi-reduced-lab` combined those four drops with the filtered
seccomp profile and the provided proc-only entrypoint. It passed a fresh
installation, Web UI, health, Network-service readiness and outer restart
checks. The
retained outer capability mask was `0x2405fb`: CHOWN, DAC_OVERRIDE, FOWNER,
FSETID, KILL, SETGID, SETUID, SETPCAP, NET_BIND_SERVICE, SYS_CHROOT and
SYS_ADMIN. Removing the remaining baseline capabilities was not investigated.

### Other requirements are separate from capabilities

- **Writable private cgroups:** adding `SYS_ADMIN` alone leaves Docker's
  cgroup filesystem read-only; systemd exits 255. Remounting the private
  `/sys/fs/cgroup` read-write allows systemd to start. Without `SYS_ADMIN`,
  that remount fails with permission denied.
- **TUN access:** mapping `/dev/net/tun` is necessary for the tested pasta
  mode. A capability does not grant device-cgroup access automatically.
  With an existing mapped node, outer `MKNOD` was unnecessary. No FUSE
  device was needed with ext4-backed container storage.
- **Seccomp:** Docker's stock policy blocks `pivot_root`; a pinned upstream
  default profile plus `pivot_root` then blocks crun's keyring creation.
  Allowing `pivot_root` and `keyctl` produced a successful installation with
  filtering enabled. Seccomp-unconfined also works. The downloaded profile
  is from upstream source, not an extracted byte-identical Docker Desktop
  built-in profile; this is not a fully minimized syscall allowlist.
- **Protected procfs submounts:** with seccomp disabled, default Docker paths
  first block `/proc/sys/net/ipv4/ping_group_range` as read-only; remounting
  `/proc/sys` alone still leaves crun unable to mount procfs. Removing the
  outer container's Docker-created `/proc` submounts before systemd starts
  allows rootless procfs creation, without disabling `/sys` masks globally.
- **AppArmor:** Docker Desktop reports no active AppArmor profile for these
  containers. A Home Assistant OS profile allowing the needed operations
  still needs testing. Capabilities do not override AppArmor restrictions.

## Experiment matrix

Every row uses a private cgroup namespace and isolated networking. Where
installation was tested, storage was in a fresh Docker-managed ext4 volume.

| Changes from Docker defaults                                                                                       | Result                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Add SYS_ADMIN                                                                                                      | systemd exits 255 with read-only cgroups.                                                                                |
| Above, remount private cgroups writable                                                                            | Image loads; pasta fails because `/dev/net/tun` is absent.                                                               |
| Above, map TUN                                                                                                     | pasta `pivot_root` fails with EPERM under stock seccomp.                                                                 |
| Above, drop MKNOD                                                                                                  | Same seccomp failure; MKNOD does not fix it.                                                                             |
| Disable seccomp, drop MKNOD, map TUN, writable cgroups                                                             | crun fails: read-only `/proc/sys/net/ipv4/ping_group_range`.                                                             |
| Above, remount `/proc/sys` writable                                                                                | crun fails mounting procfs with EPERM.                                                                                   |
| Above, disable Docker system-path masks/read-only paths                                                            | Installation, Web UI, health and Network service pass; outer restart passes.                                             |
| Above, also drop NET_RAW and AUDIT_WRITE                                                                           | Installation, Web UI, health and Network service pass. Discovery process runs, but actual discovery traffic is untested. |
| Above, also drop SETFCAP                                                                                           | Installation, Web UI, health and Network service pass.                                                                   |
| Use filtered upstream seccomp plus pivot_root only                                                                 | crun fails creating a keyring with EPERM.                                                                                |
| Use filtered upstream seccomp plus pivot_root and keyctl                                                           | Installation and Web UI pass; startup/restart checks described below.                                                    |
| Default system paths, remove only outer `/proc` submounts at startup; drop all four optional baseline capabilities | Installation succeeds without `systempaths=unconfined`.                                                                  |
| Remove SYS_ADMIN but otherwise relax seccomp/system paths                                                          | cgroup remount fails; startup exits 32.                                                                                  |

An attempted reinstall after a failed OCI create encountered stale Podman
`created` state and timed out waiting for a nonexistent running container to
stop. Fresh containers/volumes were used for subsequent matrix tests; this
was not treated as evidence of another missing capability.

After the initial matrix checks, outer-container restarts were also verified
for `unifi-perm-reduced-defaults` and `unifi-perm-pivot-keyctl`: both recovered
HTTP 200, passing inner health checks, active outer services, and active
Network services. The proc-only variant was also tested for readiness/restart.

## Reproduce the reduced setup

The provided entrypoint only prepares this lab container's own private mounts.
Never run it on a host, or with host PID/cgroup namespaces. Removing procfs
protections and granting SYS_ADMIN remain substantial security concessions.

```sh
docker build --platform linux/arm64 -t unifi-os-lab:26.04 investigation/unifi-os-server
docker run -d --name unifi-reduced-lab --platform linux/arm64 \
  --cap-add=SYS_ADMIN \
  --cap-drop=MKNOD --cap-drop=NET_RAW --cap-drop=AUDIT_WRITE --cap-drop=SETFCAP \
  --device=/dev/net/tun --security-opt=seccomp=unconfined \
  --cgroupns=private --memory=4g --cpus=4 --pids-limit=8192 \
  --mount type=volume,source=unifi-reduced-lab-home,target=/home/uosserver \
  --tmpfs /run --tmpfs /run/lock unifi-os-lab:26.04 \
  bash /usr/local/bin/unifi-lab-permissions-entrypoint
docker exec unifi-reduced-lab /root/investigation/unifi-os-server-5.1.42-arm64.run --non-interactive
```

`prepare-seccomp.py OUTPUT --allow keyctl` generates the filtered alternative.
Use its absolute output path in `--security-opt=seccomp=PATH` instead of
`seccomp=unconfined`. The source is pinned to moby/profiles commit
`6049e40058759e8a1673ac1090ec6a7e36b9c9bd`; observed upstream checksum:
`15434cc9c9037d85b35027a60721bf45f381782b4283b01d94663366e71569f8`.

The retained `unifi-reduced-lab` used this filtered alternative, but its old
mount setup is unsafe to resume. No ports were published. Installer logs are
retained at `/root/investigation/install-permissions.log` in each test container.
All permission-test containers were stopped after the investigation.

## Home Assistant implications

Current Supervisor source confirms:

- `privileged` becomes Docker `CapAdd`, not Docker privileged mode.
- Its Docker interface explicitly sets `seccomp=unconfined`, so the stock
  Docker seccomp failures are **not** automatically Home Assistant failures.
- App device declarations produce device-cgroup rules; Supervisor mounts
  host `/dev` separately. A TUN declaration must be tested on actual HAOS.
- The app configuration does not expose arbitrary Docker system-path
  options. The successful proc-only entrypoint avoids needing that option,
  but still requires an AppArmor policy allowing these mount operations.

A **candidate**, not a tested or complete app manifest, is:

```yaml
init: false
privileged:
  - SYS_ADMIN
devices:
  - /dev/net/tun
```

It also needs its own systemd image/entrypoint, persistent storage and suitable
AppArmor policy. Do not infer that `full_access`, protection-mode disabling,
`host_pid`, `host_dbus`, or outer `NET_ADMIN` are required from this experiment.
Test the candidate on disposable HAOS before proposing it upstream.

Sources inspected:

- [Supervisor app Docker wrapper](https://github.com/home-assistant/supervisor/blob/main/supervisor/docker/app.py)
- [Supervisor Docker interface](https://github.com/home-assistant/supervisor/blob/main/supervisor/docker/interface.py)
- [Supervisor Docker manager](https://github.com/home-assistant/supervisor/blob/main/supervisor/docker/manager.py)
