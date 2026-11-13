#!/bin/bash
# Investigation only. Never run on a host or with host PID/cgroup namespaces.
set -euo pipefail

if [[ "${container:-}" != "docker" ]]; then
    echo "This entrypoint is only intended for the isolated Docker lab." >&2
    exit 1
fi

# systemd needs to manage children in this container's private cgroup namespace.
mount -o remount,rw /sys/fs/cgroup

# Rootless crun cannot mount a fresh procfs when Docker's protected submounts
# are inherited and locked in its user namespace. Remove only /proc submounts
# in the OUTER container's mount namespace, retaining Docker's /sys masks.
# This weakens /proc protection; it is not an AppArmor-approved HAOS setup.
for path in \
    /proc/acpi /proc/asound /proc/interrupts /proc/kcore /proc/keys \
    /proc/latency_stats /proc/sched_debug /proc/scsi /proc/timer_list \
    /proc/timer_stats /proc/bus /proc/fs /proc/irq /proc/sys; do
    if mountpoint -q "${path}"; then
        umount "${path}"
    fi
done

# Historical proof-of-concept only. Keep kernel-wide SysRq protected, even
# though this prevents the old rootless runtime setup from completing.
if [[ -w /proc/sysrq-trigger ]]; then
    echo "Refusing writable kernel SysRq; see unifi/TESTING.md instead." >&2
    exit 1
fi

exec /usr/lib/systemd/systemd
