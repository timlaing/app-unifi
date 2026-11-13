"""Ensure the rootfs adapter does not replace vendor units or runtime files."""

from pathlib import Path
import unittest

ROOTFS = Path(__file__).resolve().parents[1] / "rootfs"


class VendorBoundaryTest(unittest.TestCase):
    def test_vendor_base_units_not_supplied(self):
        for name in ("uosserver.service", "uosserver-updater.service"):
            with self.subTest(unit=name):
                self.assertFalse((ROOTFS / "etc/systemd/system" / name).exists())
                self.assertTrue(
                    (
                        ROOTFS
                        / "etc/systemd/system"
                        / (name + ".d/home-assistant.conf")
                    ).is_file()
                )

    def test_vendor_executables_not_replaced(self):
        for name in ("updater-service", "uosserver-service", "discovery", "pasta"):
            with self.subTest(binary=name):
                self.assertFalse((ROOTFS / "var/lib/uosserver/bin" / name).exists())
        self.assertFalse((ROOTFS / "opt/unifi-os/installer").exists())

    def test_worker_executes_vendor_not_a_replacement(self):
        text = (ROOTFS / "usr/local/bin/unifi-os-worker").read_text()
        self.assertIn("exec /opt/unifi-os/installer --non-interactive", text)
        self.assertIn("exec /var/lib/uosserver/bin/uosserver-service", text)

    def test_layout_ordering_in_bootstrap_dropin(self):
        unit = (ROOTFS / "etc/systemd/system/unifi-os-bootstrap.service").read_text()
        override = (
            ROOTFS
            / "etc/systemd/system/unifi-os-bootstrap.service.d/legacy-layout.conf"
        ).read_text()
        self.assertNotIn("unifi.service", unit)
        self.assertIn("After=unifi.service", override)


if __name__ == "__main__":
    unittest.main()
