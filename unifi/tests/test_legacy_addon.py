"""The one-shot migration from the deprecated upstream add-on."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1]
HELPER = APP / "rootfs/usr/share/unifi-os/legacy-addon.py"
LEGACY = "a0d7b954_unifi"


def load_helper():
    import importlib.util

    spec = importlib.util.spec_from_file_location("legacy_addon", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_backup(path, slug=LEGACY):
    inner_bytes = io.BytesIO()
    with tarfile.open(fileobj=inner_bytes, mode="w:gz") as inner:
        settings = json.dumps(
            {
                "user": {
                    "options": {"log_level": "info", "memory_max": 2048},
                    "network": {"8443/tcp": 9443, "8843/tcp": 9444, "11443/tcp": 11443},
                }
            }
        ).encode()
        member = tarfile.TarInfo("addon.json")
        member.size = len(settings)
        inner.addfile(member, io.BytesIO(settings))
        data = b"unifi.db.extraargs=--smallfiles\n"
        member = tarfile.TarInfo("data/unifi/data/system.properties")
        member.size = len(data)
        inner.addfile(member, io.BytesIO(data))
        directory = tarfile.TarInfo("data/unifi/data/db")
        directory.type = tarfile.DIRTYPE
        inner.addfile(directory)
    payload = inner_bytes.getvalue()
    with tarfile.open(path, "w") as outer:
        meta = json.dumps({"addons": [{"slug": slug, "version": "5.3.2"}]}).encode()
        member = tarfile.TarInfo("backup.json")
        member.size = len(meta)
        outer.addfile(member, io.BytesIO(meta))
        member = tarfile.TarInfo(f"{slug}.tar.gz")
        member.size = len(payload)
        outer.addfile(member, io.BytesIO(payload))


class LegacyAddonTest(unittest.TestCase):
    def setUp(self):
        self.module = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.migration = root / "legacy-migration"
        self.migration.mkdir(mode=0o700)
        patches = [
            mock.patch.object(self.module, "DATA_ROOT", root),
            mock.patch.object(self.module, "MIGRATION", self.migration),
            mock.patch.object(self.module, "RECEIPT", self.migration / "complete"),
            mock.patch.object(self.module, "CLEANUP", self.migration / "cleanup-done"),
            mock.patch.object(self.module, "FAILED", self.migration / "failed"),
            mock.patch.object(self.module, "TARGET_DATA", root / "unifi" / "data"),
            mock.patch.object(sys, "argv", ["legacy-addon.py", "--token-stdin"]),
            mock.patch.object(sys, "stdin", io.StringIO("secret-token\n")),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = self.module.main()
        return result, stderr.getvalue()

    def _info(self, version="5.3.2", state="stopped"):
        return {
            "slug": "fork_unifi",
            "repository": "forkrepo",
            "name": "UniFi OS Server",
        }

    def _legacy_info(self, version="5.3.2", state="stopped"):
        return {
            "slug": LEGACY,
            "repository": "a0d7b954",
            "name": "UniFi Network Application",
            "version": version,
            "state": state,
            "watchdog": True,
        }

    def _dispatcher(self, legacy_info=None, calls=None):
        legacy_info = legacy_info or self._legacy_info()
        calls = calls if calls is not None else []

        def request(method, path, token, payload=None, timeout=60):
            calls.append((method, path, payload))
            if path == "/addons/self/info":
                return self._info()
            if path == "/addons":
                return {"addons": [{"slug": LEGACY, "state": "stopped"}]}
            if path == f"/addons/{LEGACY}/info":
                return legacy_info
            if path == "/backups/new/partial":
                return {"slug": "bak"}
            return {}

        return request

    def _run_with_backup(self, calls):
        backup = self.migration / "fixture.tar"
        make_backup(backup)

        def download(url, token, destination, timeout=1800):
            Path(destination).write_bytes(backup.read_bytes())

        with (
            mock.patch.object(self.module, "request", self._dispatcher(calls=calls)),
            mock.patch.object(self.module, "download", download),
        ):
            return self._run()

    def test_unsupported_version_refuses_before_any_mutation(self):
        calls = []
        with mock.patch.object(
            self.module,
            "request",
            self._dispatcher(self._legacy_info(version="5.3.1"), calls),
        ):
            result, log = self._run()
        self.assertEqual(result, 1)
        self.assertIn("legacy_addon_version_unsupported", log)
        self.assertIn("5.3.1", log)
        self.assertEqual([method for method, _, _ in calls], ["GET", "GET", "GET"])
        self.assertFalse((self.migration / "complete").exists())

    def test_missing_supervisor_token_is_a_noop(self):
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("skipping legacy add-on migration", log)

    def test_absent_legacy_addon_is_a_noop(self):
        def request(method, path, token, payload=None, timeout=60):
            if path == "/addons/self/info":
                return self._info()
            return {"addons": []}

        with mock.patch.object(self.module, "request", request):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("no legacy", log)

    def test_receipt_is_checked_before_legacy_discovery(self):
        (self.migration / "complete").write_text(json.dumps({"slug": LEGACY}))

        def unexpected(*args, **kwargs):
            raise AssertionError("legacy discovery must not run after migration")

        with mock.patch.object(self.module, "find_legacy", unexpected):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("already migrated", log)

    def test_existing_data_hands_off_without_migration(self):
        self.module.TARGET_DATA.mkdir(parents=True)
        (self.module.TARGET_DATA / "system.properties").write_text("retained")
        calls = []
        with mock.patch.object(self.module, "request", self._dispatcher(calls=calls)):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("existing app data retained", log)
        receipt = json.loads((self.migration / "complete").read_text())
        self.assertEqual(receipt["source"], "existing_data")
        self.assertIn(("POST", f"/addons/{LEGACY}/options", {"watchdog": False}), calls)
        self.assertNotIn(("POST", "/backups/new/partial", mock.ANY), calls)

    def test_failed_marker_skips_legacy_discovery(self):
        self.module.FAILED.write_text(json.dumps({"slug": LEGACY}))

        def unexpected(*args, **kwargs):
            raise AssertionError("legacy discovery must not run after a failure")

        with mock.patch.object(self.module, "find_legacy", unexpected):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("previous migration failed", log)

    def test_failed_download_removes_backup_and_partial_file(self):
        calls = []

        def download(url, token, destination, timeout=1800):
            Path(destination).write_bytes(b"partial")
            raise self.module.LegacyError("download failed")

        with (
            mock.patch.object(self.module, "request", self._dispatcher(calls=calls)),
            mock.patch.object(self.module, "download", download),
        ):
            result, log = self._run()
        self.assertEqual(result, 0)
        self.assertIn("ERROR: legacy add-on migration:", log)
        self.assertIn("download failed", log)
        self.assertIn(("DELETE", "/backups/bak", None), calls)
        self.assertFalse((self.migration / "backup-bak.tar").exists())
        self.assertFalse((self.migration / "complete").exists())
        self.assertTrue(self.module.FAILED.exists())
        self.assertIn(("POST", f"/addons/{LEGACY}/options", {"watchdog": False}), calls)
        self.assertNotIn(
            ("POST", f"/addons/{LEGACY}/options", {"watchdog": True}), calls
        )
        self.assertNotIn(("POST", f"/addons/{LEGACY}/start", None), calls)

    def test_successful_migration_moves_data_and_host_ports(self):
        calls = []
        result, log = self._run_with_backup(calls)
        self.assertEqual(result, 0)
        self.assertIn("migration complete", log)

        receipt = json.loads((self.migration / "complete").read_text())
        self.assertEqual(receipt["slug"], LEGACY)
        self.assertEqual(receipt["version"], "5.3.2")
        self.assertTrue((self.module.TARGET_DATA / "system.properties").is_file())
        self.assertEqual(
            (self.module.TARGET_DATA / "system.properties").read_bytes(),
            b"unifi.db.extraargs=--smallfiles\n",
        )

        posted = [payload for method, _, payload in calls if method == "POST"]
        self.assertIn({"watchdog": False}, posted)
        self.assertIn(
            {
                "name": "UniFi OS migration",
                "addons": [LEGACY],
                "compressed": True,
                "background": False,
            },
            posted,
        )
        self.assertIn(
            {
                "options": {"log_level": "info", "memory_max": 2048},
                "network": {"8443/tcp": 9443, "8843/tcp": 9444},
            },
            posted,
        )
        self.assertIn(("DELETE", f"/backups/bak", None), calls)

    def test_existing_retained_data_is_not_overwritten(self):
        self.module.TARGET_DATA.mkdir(parents=True)
        (self.module.TARGET_DATA / "system.properties").write_text("keep me")
        calls = []
        result, log = self._run_with_backup(calls)
        self.assertEqual(result, 0)
        self.assertIn("existing app data retained", log)
        self.assertEqual(
            (self.module.TARGET_DATA / "system.properties").read_text(), "keep me"
        )
        self.assertEqual(
            json.loads((self.migration / "complete").read_text())["source"],
            "existing_data",
        )

    def test_cleanup_uninstalls_once(self):
        self.module.RECEIPT.write_text(json.dumps({"slug": LEGACY, "version": "5.3.2"}))
        calls = []
        with mock.patch.object(self.module, "request", self._dispatcher(calls=calls)):
            self.module.cleanup("token")
            self.module.cleanup("token")
        self.assertEqual(
            [call for call in calls if call[0] == "POST"],
            [("POST", f"/addons/{LEGACY}/uninstall", {"remove_config": True})],
        )
        self.assertTrue(self.module.CLEANUP.exists())

    def test_migration_runs_before_restore_and_systemd(self):
        entrypoint = (APP / "rootfs/usr/local/bin/unifi-os-entrypoint").read_text()
        helper = entrypoint.index("/usr/share/unifi-os/legacy-addon.py")
        restore = entrypoint.index("/usr/local/bin/unifi-os-runtime-storage restore")
        systemd = entrypoint.index("exec setpriv --bounding-set=-mknod")
        self.assertLess(helper, restore)
        self.assertLess(helper, systemd)
        bootstrap = (APP / "rootfs/usr/local/bin/unifi-os-bootstrap").read_text()
        self.assertNotIn("legacy-addon.py", bootstrap)
        guard = "if [[ ! -f /var/lib/unifi-os-app/legacy-migration/failed ]]; then"
        self.assertIn(guard, bootstrap)
        self.assertLess(
            bootstrap.index(guard),
            bootstrap.index("/usr/local/bin/unifi-os-prepare-mongo"),
        )
        service = (APP / "rootfs/etc/systemd/system/unifi.service").read_text()
        self.assertIn(
            "ConditionPathExists=!/var/lib/unifi-os-app/legacy-migration/failed",
            service,
        )
        unit = (
            APP / "rootfs/etc/systemd/system/unifi-os-setup-notification.service"
        ).read_text()
        self.assertIn("Type=oneshot", unit)
        self.assertIn("+ExecStartPost=", unit)
        self.assertIn("/usr/share/unifi-os/legacy-addon.py --cleanup", unit)
        self.assertLess(
            unit.index("/usr/share/unifi-os/setup-notification.py"),
            unit.index("+ExecStartPost="),
        )


if __name__ == "__main__":
    unittest.main()
