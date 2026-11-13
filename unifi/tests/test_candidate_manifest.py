"""Keep the candidate on the original app identity with explicit release gates."""

from pathlib import Path
import unittest

import yaml

APP = Path(__file__).resolve().parents[1]


class CandidateManifestTest(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((APP / "config.yaml").read_text())

    def test_original_identity_and_manual_breaking_upgrade(self):
        self.assertEqual(self.config["slug"], "unifi")
        self.assertEqual(self.config["stage"], "experimental")
        self.assertIn(self.config["version"], self.config["breaking_versions"])
        self.assertFalse((APP.parent / "unifi-os-test/config.yaml").exists())

    def test_private_storage_and_cold_backup(self):
        data = next(m for m in self.config["map"] if m["type"] == "data")
        self.assertEqual(data["path"], "/lib/unifi/data")
        self.assertFalse(data["read_only"])
        self.assertEqual(self.config["backup"], "cold")

    def test_direct_console_and_default_legacy_host_ports(self):
        self.assertEqual(self.config["webui"], "https://[HOST]:[PORT:11443]")
        for port, host in {
            "11443/tcp": 8443,
            "8444/tcp": 8843,
            "10003/udp": 10001,
            "8080/tcp": 8080,
        }.items():
            self.assertEqual(self.config["ports"][port], host)

    def test_options_retained_without_extra_host_access(self):
        self.assertEqual(
            set(self.config["schema"]), {"log_level", "memory_max", "memory_init"}
        )
        for flag in (
            "host_pid",
            "host_network",
            "host_dbus",
            "docker_api",
            "hassio_api",
        ):
            self.assertFalse(self.config.get(flag, False))

    def test_no_legacy_vendor_patching_entrypoint(self):
        self.assertEqual(list((APP / "rootfs/etc/s6-overlay").glob("**/run")), [])
        dockerfile = (APP / "Dockerfile").read_text()
        self.assertIn('ENTRYPOINT ["/usr/local/bin/unifi-os-entrypoint"]', dockerfile)
        self.assertNotIn("verify_bytes", dockerfile)
        self.assertNotIn("webrtc_jni", dockerfile)
