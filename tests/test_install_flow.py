import tempfile
import unittest
from pathlib import Path

from apk_placer.adb import AdbDevice, InstallError
from apk_placer.core import Device
from apk_placer.worker import TransferWorker
from test_worker import ClockStop, FakeBackend


class InstallBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.devices = [Device("mtp-1", "Test PDA", ("USB123",))]

    def serial_number(self):
        return "USB123"


class FakeInstaller:
    def __init__(self):
        self.targets = [AdbDevice("USB123", "device")]
        self.installs = []
        self.failure = False

    def devices(self, cancelled):
        return self.targets

    def install(self, serial, source, cancelled):
        if self.failure:
            raise InstallError("INSTALL_FAILED_UPDATE_INCOMPATIBLE")
        self.installs.append((serial, source.read_bytes()))


class InstallFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.source = Path(self.directory.name) / "client.apk"
        self.source.write_bytes(b"original version")
        self.backend = InstallBackend()
        self.installer = FakeInstaller()
        self.worker = TransferWorker(str(self.source), installer_factory=lambda _: self.installer, adb_locator=lambda _: "adb.exe")

    def tearDown(self):
        self.worker._discard_pending()
        self.directory.cleanup()

    def run_ticks(self, callbacks):
        self.worker.stopping = ClockStop(callbacks)
        self.worker._monitor(self.backend)

    def test_disabled_by_default_only_transfers(self):
        self.run_ticks([lambda: None])
        self.assertFalse(self.worker.auto_install)
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertFalse(self.installer.installs)

    def test_enabled_copies_then_installs_exactly_once(self):
        self.worker.command("auto_install", True)
        self.run_ticks([lambda: None, lambda: None])
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertEqual(self.installer.installs, [("USB123", b"original version")])
        self.assertIsNone(self.worker.pending)

    def test_enable_after_success_does_not_install_old_task(self):
        self.run_ticks([lambda: self.worker.command("auto_install", True), lambda: None])
        self.assertFalse(self.installer.installs)
        self.assertEqual(len(self.backend.transfers), 1)

    def test_manual_transfer_after_enabling_installs(self):
        self.run_ticks([lambda: self.worker.command("auto_install", True),
                        lambda: self.worker.command("manual"), lambda: None])
        self.assertEqual(len(self.backend.transfers), 2)
        self.assertEqual(len(self.installer.installs), 1)

    def test_unauthorized_wait_does_not_recopy_and_keeps_same_snapshot(self):
        self.worker.command("auto_install", True)
        self.installer.targets = [AdbDevice("USB123", "unauthorized")]
        self.run_ticks([lambda: self.source.write_bytes(b"changed after copy"),
                        lambda: None, lambda: setattr(self.installer, "targets", [AdbDevice("USB123", "device")]), lambda: None])
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertEqual(self.installer.installs, [("USB123", b"original version")])

    def test_wrong_adb_device_never_installed(self):
        self.worker.command("auto_install", True)
        self.installer.targets = [AdbDevice("OTHER", "device")]
        self.run_ticks([lambda: None, lambda: None])
        self.assertFalse(self.installer.installs)
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertIsNotNone(self.worker.pending)

    def test_disable_while_waiting_cleans_snapshot_and_never_installs(self):
        self.worker.command("auto_install", True)
        copied = []

        def disable():
            copied.append(self.worker.pending.source)
            self.worker.command("auto_install", False)

        self.run_ticks([disable, lambda: None])
        self.assertFalse(self.installer.installs)
        self.assertFalse(copied[0].exists())

    def test_install_failure_not_retried_forever_or_recopied(self):
        from unittest.mock import patch
        self.worker.command("auto_install", True)
        self.installer.failure = True
        with patch("apk_placer.worker.log.exception"):
            self.run_ticks([lambda: None, lambda: None, lambda: None])
        self.assertIsNone(self.worker.pending)
        self.assertEqual(len(self.backend.transfers), 1)

    def test_missing_source_cancels_pending_install(self):
        self.worker.command("auto_install", True)
        self.run_ticks([self.source.unlink, lambda: None])
        self.assertFalse(self.installer.installs)
        self.assertTrue(self.worker.policy.path_lost)
        self.assertIsNone(self.worker.pending)

    def test_configuring_adb_continues_waiting_install_without_recopy(self):
        self.worker.command("auto_install", True)
        self.worker.adb_locator = lambda configured: configured
        self.worker.adb_path = ""
        self.run_ticks([lambda: None, lambda: self.worker.command("adb_path", "adb.exe"), lambda: None])
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertEqual(len(self.installer.installs), 1)

    def test_debug_mode_reenumeration_with_same_usb_serial_does_not_recopy(self):
        self.worker.command("auto_install", True)
        self.run_ticks([lambda: setattr(self.backend, "devices", [Device("mtp-2", "Test PDA", ("USB123",))]), lambda: None])
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertEqual(len(self.installer.installs), 1)

    def test_install_while_mtp_reenumerates_then_reappears_does_not_recopy(self):
        self.worker.command("auto_install", True)
        self.run_ticks([lambda: setattr(self.backend, "devices", []),
                        lambda: setattr(self.backend, "devices", [Device("mtp-2", "Test PDA", ("USB123",))]), lambda: None])
        self.assertEqual(len(self.backend.transfers), 1)
        self.assertEqual(len(self.installer.installs), 1)

    def test_pause_defers_install_and_resume_continues(self):
        self.worker.command("auto_install", True)
        counts = []

        def resume():
            counts.append(len(self.installer.installs))
            self.worker.command("pause", False)

        self.run_ticks([lambda: self.worker.command("pause", True), resume, lambda: None])
        self.assertEqual(counts, [0])
        self.assertEqual(len(self.installer.installs), 1)
        self.assertEqual(len(self.backend.transfers), 1)

    def test_new_target_discards_old_pending_install(self):
        self.worker.command("auto_install", True)
        self.installer.targets = [AdbDevice("USB123", "unauthorized")]
        self.run_ticks([lambda: setattr(self.backend, "devices", [Device("mtp-other", "Other PDA", ("OTHER",))])])
        self.assertIsNone(self.worker.pending)
        self.assertFalse(self.installer.installs)

    def test_temporary_adb_error_does_not_discard_copy(self):
        from unittest.mock import patch
        self.worker.command("auto_install", True)
        with patch.object(self.installer, "devices", side_effect=InstallError("offline")):
            self.run_ticks([lambda: None])
        self.assertIsNotNone(self.worker.pending)
        self.assertEqual(len(self.backend.transfers), 1)


if __name__ == "__main__":
    unittest.main()
