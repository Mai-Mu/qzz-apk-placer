import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_placer.core import Device, DeliveryPolicy, Snapshot, load_path, save_path, validate_apk


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = DeliveryPolicy()
        self.policy.select("sample.apk")
        self.device = Device("usb-1", "PDA")
        self.devices = [self.device]

    def test_once_per_connection_and_again_after_reconnect(self):
        self.policy.observe(self.devices)
        self.assertTrue(self.policy.ready(self.devices, 0))
        self.policy.success(self.device)
        self.assertFalse(self.policy.ready(self.devices, 0))
        self.policy.observe([])
        self.policy.observe(self.devices)
        self.assertTrue(self.policy.ready(self.devices, 0))

    def test_new_path_immediately_rearms_connected_device(self):
        self.policy.success(self.device)
        self.policy.select("replacement.apk")
        self.assertTrue(self.policy.ready(self.devices, 0))

    def test_manual_resend(self):
        self.policy.success(self.device)
        self.policy.manual = True
        self.assertTrue(self.policy.ready(self.devices, 0))

    def test_transient_failure_retries_after_backoff(self):
        self.policy.failure(100)
        self.assertFalse(self.policy.ready(self.devices, 109))
        self.assertTrue(self.policy.ready(self.devices, 110))

    def test_pause_blocks_all_work(self):
        self.policy.paused = True
        self.assertFalse(self.policy.ready(self.devices, 0))
        self.policy.paused = False
        self.assertTrue(self.policy.ready(self.devices, 0))

    def test_lost_path_stays_blocked_until_reselected(self):
        self.policy.path_lost = True
        self.assertFalse(self.policy.ready(self.devices, 0))
        self.policy.select("sample.apk")
        self.assertTrue(self.policy.ready(self.devices, 0))

    def test_no_device_or_multiple_devices_never_start(self):
        self.assertFalse(self.policy.ready([], 0))
        self.assertFalse(self.policy.ready(self.devices + [Device("usb-2", "Other")], 0))


class FileTests(unittest.TestCase):
    def test_missing_empty_and_wrong_extension_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.apk"
            self.assertIsNotNone(validate_apk(str(missing)))
            missing.touch()
            self.assertIsNotNone(validate_apk(str(missing)))
            text = Path(directory) / "sample.txt"
            text.write_bytes(b"data")
            self.assertIsNotNone(validate_apk(str(text)))

    def test_snapshot_is_independent_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "安装包.APK"
            source.write_bytes(b"original data")
            self.assertIsNone(validate_apk(str(source)))
            with Snapshot(str(source)) as copied:
                source.write_bytes(b"changed")
                self.assertEqual(copied.read_bytes(), b"original data")
                self.assertEqual(copied.name, source.name)
            self.assertFalse(copied.exists())

    def test_modification_during_snapshot_rejected(self):
        import apk_placer.core as core
        original_copy = core.shutil.copyfile
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.apk"
            source.write_bytes(b"first")

            def changing_copy(src, dst):
                original_copy(src, dst)
                src.write_bytes(b"new version")

            with patch.object(core.shutil, "copyfile", changing_copy):
                with self.assertRaisesRegex(ValueError, "APK"):
                    with Snapshot(str(source)):
                        self.fail("unstable source accepted")

    def test_settings_unicode_round_trip_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("apk_placer.core.data_directory", return_value=root):
                self.assertEqual(load_path(), "")
                save_path("C:/安装包/客户.apk")
                self.assertEqual(load_path(), "C:/安装包/客户.apk")
                (root / "settings.json").write_text("broken", "utf-8")
                self.assertEqual(load_path(), "")


if __name__ == "__main__":
    unittest.main()
