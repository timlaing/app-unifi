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
    except (OSError, TimeoutError) as err:
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
    except (OSError, TimeoutError, urllib.error.HTTPError) as err:
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


def extract_data(backup_path, slug, staging):
    with tarfile.open(backup_path, "r:*") as outer:
        outer_members = normalized_members(outer)
        meta_member = outer_members.get("backup.json")
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

        inner_name = f"{slug}.tar.gz"
        inner_member = outer_members.get(inner_name)
        if inner_member is None or not inner_member.isreg():
            raise LegacyError("temporary backup has no app data archive")
        inner_stream = outer.extractfile(inner_member)
        if inner_stream is None:
            raise LegacyError("temporary backup app data cannot be read")
        with tarfile.open(fileobj=inner_stream, mode="r:gz") as inner:
            addon_member = normalized_members(inner).get("addon.json")
            if addon_member is None or not addon_member.isreg():
                raise LegacyError("legacy data has no addon.json settings")
            settings_stream = inner.extractfile(addon_member)
            settings = json.loads(settings_stream.read(MAX_API_BODY))
            if not isinstance(settings, dict):
                raise LegacyError("legacy settings are invalid")

            def safe_members():
                for member in inner.getmembers():
                    name = member.name
                    while name.startswith("./"):
                        name = name[2:]
                    name = name.lstrip("/")
                    parts = name.replace(os.sep, "/").split("/")
                    if (
                        not name
                        or ".." in parts
                        or name == "data"
                        or not name.startswith("data/")
                    ):
                        continue
                    if member.isdev() or member.isfifo():
                        continue
                    if member.issym() or member.islnk():
                        if os.path.isabs(member.linkname):
                            # The legacy app's absolute /backup/unifi link is not
                            # used by UniFi OS and must not escape the staging dir.
                            continue
                        link_parts = member.linkname.replace(os.sep, "/").split("/")
                        if ".." in link_parts:
                            continue
                    yield member.replace(name=name)

            inner.extractall(path=staging, members=safe_members(), filter="tar")
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
        request(
            "POST",
            f"/addons/{urllib.parse.quote(slug, safe='')}/options",
            token,
            {"watchdog": False},
        )
        watchdog_changed = True
        if info.get("state") in ("started", "startup"):
            request("POST", f"/addons/{urllib.parse.quote(slug, safe='')}/stop", token)
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
        try:
            request(
                "DELETE",
                f"/backups/{urllib.parse.quote(backup_slug, safe='')}",
                token,
            )
        except LegacyError as err:
            log(f"warning: could not delete the temporary backup: {err}")
        backup_slug = None
        log("migration complete")
    except BaseException as err:
        if watchdog_changed:
            try:
                request(
                    "POST",
                    f"/addons/{urllib.parse.quote(slug, safe='')}/options",
                    token,
                    {"watchdog": original_watchdog},
                )
            except LegacyError as restore_err:
                log(f"warning: could not restore the old app watchdog: {restore_err}")
            if info.get("state") in ("started", "startup"):
                try:
                    request(
                        "POST",
                        f"/addons/{urllib.parse.quote(slug, safe='')}/start",
                        token,
                    )
                except LegacyError as restore_err:
                    log(f"warning: could not restart the old app: {restore_err}")
        subprocess.run(
            [
                "/usr/local/bin/unifi-os-alert",
                "legacy_migration_failed",
                "Legacy UniFi data could not be migrated",
                f"Migration from {slug} failed: {err}. No UniFi OS data was changed; see the app log.",
            ],
            check=False,
        )
        raise
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup_file is not None:
            backup_file.unlink(missing_ok=True)
        if backup_slug is not None:
            try:
                request(
                    "DELETE",
                    f"/backups/{urllib.parse.quote(backup_slug, safe='')}",
                    token,
                )
            except LegacyError as err:
                log(f"warning: could not delete the temporary backup: {err}")
        os.close(lock_fd)


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
        request(
            "POST",
            f"/addons/{urllib.parse.quote(slug, safe='')}/uninstall",
            token,
            {"remove_config": False},
        )
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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--token-stdin", action="store_true")
    group.add_argument("--token-file")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    if args.token_stdin:
        token = sys.stdin.readline().strip()
    else:
        try:
            token = Path(args.token_file).read_text().strip()
        except OSError as err:
            log(f"could not read the Supervisor token: {err}")
            return 1
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
