#!/usr/bin/python3
"""One-shot migration from the deprecated hassio-addons UniFi Network app.

Only the Python standard library is used. The Supervisor token is read from
stdin (startup) or from a root-only file (post-start cleanup); it is never
placed on a command line or in an exported environment variable.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

SUPERVISOR = "http://supervisor"
LEGACY_VERSION = "5.3.2"
LEGACY_NAME = "UniFi Network Application"
DATA_ROOT = Path("/var/lib/unifi-os-app")
MIGRATION = DATA_ROOT / "legacy-migration"
RECEIPT = MIGRATION / "complete"
CLEANUP = MIGRATION / "cleanup-done"
TARGET_DATA = DATA_ROOT / "unifi" / "data"

# Only settings and container-port keys that this app also declares are copied.
MANAGED_OPTIONS = (
    "log_level",
    "memory_max",
    "memory_init",
    "ingress_allow_insecure_http",
)
MANAGED_PORTS = (
    "161/udp",
    "1900/udp",
    "3478/udp",
    "5514/udp",
    "6789/tcp",
    "8080/tcp",
    "8443/tcp",
    "8843/tcp",
    "8880/tcp",
    "10001/udp",
)

MAX_API_BODY = 4 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024


class LegacyError(Exception):
    """A reason to refuse startup without changing any data."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def log(message):
    print(f"legacy add-on migration: {message}", file=sys.stderr, flush=True)


def request(method, path, token, payload=None, timeout=60):
    body = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        SUPERVISOR + path, data=body, headers=headers, method=method
    )
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_API_BODY + 1)
    except urllib.error.HTTPError as err:
        raise LegacyError(f"Supervisor {method} {path} failed: HTTP {err.code}")
    except OSError as err:
        raise LegacyError(f"Supervisor {method} {path} failed: {err}")
    if len(raw) > MAX_API_BODY:
        raise LegacyError(f"Supervisor {method} {path} returned too much data")
    try:
        result = json.loads(raw)
    except ValueError as err:
        raise LegacyError(f"Supervisor {method} {path} returned invalid JSON: {err}")
    if not isinstance(result, dict) or result.get("result") != "ok":
        message = (
            result.get("message", "unknown error")
            if isinstance(result, dict)
            else "invalid response"
        )
        raise LegacyError(f"Supervisor {method} {path}: {message}")
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def addon_action(token, slug, action, payload=None):
    path = f"/addons/{urllib.parse.quote(slug, safe='')}/{action}"
    return request("POST", path, token, payload)


def download(url, token, destination, timeout=1800):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with (
            opener.open(req, timeout=timeout) as response,
            open(destination, "wb") as output,
        ):
            while True:
                chunk = response.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                output.write(chunk)
    except OSError as err:
        raise LegacyError(f"could not download the temporary backup: {err}")


def atomic_write(path, payload):
    MIGRATION.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def read_receipt():
    try:
        data = json.loads(RECEIPT.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_legacy(token):
    own = request("GET", "/addons/self/info", token)
    own_slug = own.get("slug")
    if not isinstance(own_slug, str):
        raise LegacyError("could not determine this app's add-on slug")
    listed = request("GET", "/addons", token)
    addons = listed.get("addons", [])
    if not isinstance(addons, list):
        raise LegacyError("Supervisor returned an invalid add-on list")

    candidates = []
    for addon in addons:
        if not isinstance(addon, dict):
            continue
        slug = addon.get("slug")
        if not isinstance(slug, str) or slug == own_slug or not slug.endswith("_unifi"):
            continue
        info = request(
            "GET", f"/addons/{urllib.parse.quote(slug, safe='')}/info", token
        )
        if info.get("name") == LEGACY_NAME and info.get("repository") != own.get(
            "repository"
        ):
            candidates.append((slug, info))
    if len(candidates) > 1:
        raise LegacyError(
            "more than one legacy UniFi Network add-on is installed; remove the extras"
        )
    return candidates[0] if candidates else None


def normalized_members(archive):
    result = {}
    for member in archive.getmembers():
        name = member.name
        while name.startswith("./"):
            name = name[2:]
        name = name.lstrip("/")
        result[name] = member
    return result


def inner_archive(outer, members, slug):
    meta_member = members.get("backup.json")
    if meta_member is None or not meta_member.isreg():
        raise LegacyError("temporary backup has no backup.json")
    stream = outer.extractfile(meta_member)
    if stream is None:
        raise LegacyError("temporary backup metadata cannot be read")
    try:
        metadata = json.loads(stream.read(MAX_API_BODY))
    except ValueError as err:
        raise LegacyError(f"temporary backup metadata is invalid: {err}")
    included = {
        item.get("slug")
        for item in metadata.get("addons", [])
        if isinstance(item, dict)
    }
    if slug not in included:
        raise LegacyError("temporary backup does not contain the legacy add-on")
    inner_member = members.get(f"{slug}.tar.gz")
    if inner_member is None or not inner_member.isreg():
        raise LegacyError("temporary backup has no app data archive")
    stream = outer.extractfile(inner_member)
    if stream is None:
        raise LegacyError("temporary backup app data cannot be read")
    return stream


def legacy_members(inner):
    for member in inner.getmembers():
        name = member.name
        while name.startswith("./"):
            name = name[2:]
        name = name.lstrip("/")
        parts = name.replace(os.sep, "/").split("/")
        if not name or ".." in parts or not name.startswith("data/"):
            continue
        if member.isdev() or member.isfifo():
            continue
        if member.issym() or member.islnk():
            if os.path.isabs(member.linkname):
                # The legacy app's absolute /backup/unifi link is not used by
                # UniFi OS and must not escape the staging directory.
                continue
            if ".." in member.linkname.replace(os.sep, "/").split("/"):
                continue
        yield member.replace(name=name)


def addon_settings(inner, members):
    member = members.get("addon.json")
    if member is None or not member.isreg():
        raise LegacyError("legacy data has no addon.json settings")
    stream = inner.extractfile(member)
    settings = json.loads(stream.read(MAX_API_BODY))
    if not isinstance(settings, dict):
        raise LegacyError("legacy settings are invalid")
    return settings


def extract_data(backup_path, slug, staging):
    with tarfile.open(backup_path, "r:*") as outer:
        stream = inner_archive(outer, normalized_members(outer), slug)
        with tarfile.open(fileobj=stream, mode="r:gz") as inner:
            settings = addon_settings(inner, normalized_members(inner))
            inner.extractall(path=staging, members=legacy_members(inner), filter="tar")
    return settings


def install_data(staging):
    source = staging / "data"
    if not (source / "system.properties").is_file():
        raise LegacyError("legacy data has no system.properties")
    TARGET_DATA.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if TARGET_DATA.exists():
        if (TARGET_DATA / "system.properties").is_file():
            log("retained Network data already present; not overwriting it")
            shutil.rmtree(source)
            return
        if not TARGET_DATA.is_dir() or any(TARGET_DATA.iterdir()):
            raise LegacyError("unexpected data at the legacy migration target")
        TARGET_DATA.rmdir()
    shutil.move(str(source), str(TARGET_DATA))


def apply_settings(token, settings):
    user = settings.get("user")
    if not isinstance(user, dict):
        return
    payload = {}
    options = user.get("options")
    if isinstance(options, dict):
        copied = {key: options[key] for key in MANAGED_OPTIONS if key in options}
        if copied:
            payload["options"] = copied
    network = user.get("network")
    if isinstance(network, dict):
        copied = {key: network[key] for key in MANAGED_PORTS if key in network}
        if copied:
            payload["network"] = copied
    if payload:
        request("POST", "/addons/self/options", token, payload)
        log("migrated legacy options and host port mappings")


def take_backup(token, slug):
    created = request(
        "POST",
        "/backups/new/partial",
        token,
        {
            "name": "UniFi OS migration",
            "addons": [slug],
            "compressed": True,
            "background": False,
        },
        timeout=1800,
    )
    backup_slug = created.get("slug")
    if not isinstance(backup_slug, str) or not backup_slug:
        raise LegacyError("Supervisor did not return a temporary backup slug")
    backup_file = MIGRATION / f"backup-{backup_slug}.tar"
    download(
        f"{SUPERVISOR}/backups/{urllib.parse.quote(backup_slug, safe='')}/download",
        token,
        backup_file,
    )
    return backup_slug, backup_file


def delete_backup(token, backup_slug):
    if backup_slug is None:
        return
    try:
        request(
            "DELETE",
            f"/backups/{urllib.parse.quote(backup_slug, safe='')}",
            token,
        )
    except LegacyError as err:
        log(f"warning: could not delete the temporary backup: {err}")


def restore_old_app(token, slug, info, watchdog_changed, original_watchdog):
    if not watchdog_changed:
        return
    try:
        addon_action(token, slug, "options", {"watchdog": original_watchdog})
    except LegacyError as err:
        log(f"warning: could not restore the old app watchdog: {err}")
    if info.get("state") in ("started", "startup"):
        try:
            addon_action(token, slug, "start")
        except LegacyError as err:
            log(f"warning: could not restart the old app: {err}")


def alert_migration_failed(slug, err):
    subprocess.run(
        [
            "/usr/local/bin/unifi-os-alert",
            "legacy_migration_failed",
            "Legacy UniFi data could not be migrated",
            f"Migration from {slug} failed: {err}. No UniFi OS data was changed; see the app log.",
        ],
        check=False,
    )


def cleanup_temp(staging, backup_file, backup_slug, token, lock_fd):
    if staging is not None and staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if backup_file is not None:
        backup_file.unlink(missing_ok=True)
    delete_backup(token, backup_slug)
    os.close(lock_fd)


def migrate(token, slug, info):
    MIGRATION.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(MIGRATION / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    import fcntl

    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    original_watchdog = bool(info.get("watchdog", True))
    watchdog_changed = False
    staging = None
    backup_file = None
    backup_slug = None
    try:
        log(f"migrating from {slug} version {info.get('version')}")
        addon_action(token, slug, "options", {"watchdog": False})
        watchdog_changed = True
        if info.get("state") in ("started", "startup"):
            addon_action(token, slug, "stop")
        backup_slug, backup_file = take_backup(token, slug)
        staging = Path(tempfile.mkdtemp(prefix="staging-", dir=MIGRATION))
        os.chmod(staging, 0o700)
        settings = extract_data(backup_file, slug, staging)
        install_data(staging)
        apply_settings(token, settings)
        atomic_write(
            RECEIPT,
            {
                "slug": slug,
                "version": LEGACY_VERSION,
                "migrated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        )
        delete_backup(token, backup_slug)
        backup_slug = None
        log("migration complete")
    except BaseException as err:
        restore_old_app(token, slug, info, watchdog_changed, original_watchdog)
        alert_migration_failed(slug, err)
        raise
    finally:
        cleanup_temp(staging, backup_file, backup_slug, token, lock_fd)


def cleanup(token):
    receipt = read_receipt()
    if receipt is None or CLEANUP.exists():
        return
    slug = receipt.get("slug")
    if not isinstance(slug, str) or not slug:
        raise LegacyError("migration receipt has no add-on slug")
    listed = request("GET", "/addons", token)
    addons = listed.get("addons", [])
    installed = any(
        isinstance(item, dict) and item.get("slug") == slug for item in addons
    )
    removed = False
    if installed:
        log(f"uninstalling migrated legacy add-on {slug}")
        addon_action(token, slug, "uninstall", {"remove_config": True})
        removed = True
    atomic_write(
        CLEANUP,
        {
            "slug": slug,
            "uninstalled": removed,
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    token = sys.stdin.readline().strip()
    if not token:
        log("Supervisor token is unavailable")
        return 1

    try:
        if args.cleanup:
            cleanup(token)
            return 0
        legacy = find_legacy(token)
        if legacy is None:
            log("no legacy UniFi Network add-on is installed")
            return 0
        slug, info = legacy
        version = str(info.get("version", "")).lstrip("v")
        if version != LEGACY_VERSION:
            log(
                f"legacy_addon_version_unsupported: {slug} has version "
                f"{info.get('version')!r}; exactly {LEGACY_VERSION} is supported. "
                "Nothing was changed; install the final upstream version and start again."
            )
            return 1
        if RECEIPT.exists():
            log("legacy data was already migrated")
            return 0
        migrate(token, slug, info)
        return 0
    except LegacyError as err:
        log(str(err))
        return 1


if __name__ == "__main__":
    sys.exit(main())
