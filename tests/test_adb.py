from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from apk_placer.adb import AdbClient, AdbDevice, InstallError, find_adb, match_device, parse_devices
from apk_placer.core import load_adb_path, load_path, save_path, save_setting


class AdbTests(unittest.TestCase):
    def test_parse_excludes_wifi_and_emulators_but_keeps_authorization_states(self):
        output = """List of devices attached
USB123 device product:pda model:Test transport_id:1
USB456 unauthorized transport_id:2
USB789 offline transport_id:3
emulator-5554 device
192.168.1.2:5555 device
adb-ABC._adb-tls-connect._tcp device
* daemon started successfully
"""
        self.assertEqual(parse_devices(output), [AdbDevice("USB123", "device"), AdbDevice("USB456", "unauthorized"), AdbDevice("USB789", "offline")])

    def test_match_requires_explicit_identity_even_with_only_one_device(self):
        candidates = [AdbDevice("OTHER", "device")]
        self.assertIsNone(match_device(candidates, ("TARGET",)))
        self.assertIsNone(match_device(candidates, ()))
        self.assertEqual(match_device(candidates, ("other",)), candidates[0])

    def test_ambiguous_identity_never_selects_a_device(self):
        self.assertIsNone(match_device([AdbDevice("A", "device"), AdbDevice("B", "device")], ("A", "B")))

    def test_install_uses_target_and_data_preserving_flag_only(self):
        client = AdbClient("adb.exe")
        with patch.object(client, "_run", return_value=(0, "Performing Streamed Install\nSuccess\n")) as run:
            client.install("USB123", Path("安装包.apk"), lambda: False)
            arguments = run.call_args.args[0]
            self.assertEqual(arguments, ["-s", "USB123", "install", "-r", "安装包.apk"])

    def test_signature_and_downgrade_failures_explain_without_uninstall(self):
        for code in ("INSTALL_FAILED_UPDATE_INCOMPATIBLE", "INSTALL_FAILED_VERSION_DOWNGRADE"):
            client = AdbClient("adb.exe")
            with patch.object(client, "_run", return_value=(1, f"Failure [{code}]")) as run:
                with self.assertRaisesRegex(InstallError, "未卸载"):
                    client.install("SERIAL", Path("app.apk"), lambda: False)
                self.assertEqual(run.call_count, 1)

    def test_zero_exit_without_success_is_not_reported_as_installed(self):
        client = AdbClient("adb.exe")
        with patch.object(client, "_run", return_value=(0, "unexpected result")):
            with self.assertRaises(InstallError):
                client.install("S", Path("a.apk"), lambda: False)

    def test_shell_is_disabled_and_selected_executable_is_used(self):
        process = unittest.mock.Mock()
        process.communicate.return_value = (b"Success\n", None)
        process.returncode = 0
        process.poll.return_value = 0
        with patch("apk_placer.adb.subprocess.Popen", return_value=process) as popen:
            AdbClient("C:/tools with spaces/adb.exe").install("S", Path("C:/apk files/a.apk"), lambda: False)
            self.assertFalse(popen.call_args.kwargs["shell"])
            self.assertEqual(popen.call_args.args[0][0], "C:/tools with spaces/adb.exe")

    def test_timeout_terminates_only_the_client_process(self):
        process = unittest.mock.Mock()
        process.communicate.return_value = (b"", None)
        process.poll.return_value = None
        with patch("apk_placer.adb.subprocess.Popen", return_value=process), patch("apk_placer.adb.time.monotonic", side_effect=[0, 20]):
            with self.assertRaises(InstallError):
                AdbClient("adb.exe")._run(["devices"], 1)
            process.kill.assert_called_once()

    def test_saved_adb_path_survives_selecting_new_apk(self):
        with tempfile.TemporaryDirectory() as directory, patch("apk_placer.core.data_directory", return_value=Path(directory)):
            save_path("first.apk")
            save_setting("adb_path", "C:/工具/adb.exe")
            save_path("second.apk")
            self.assertEqual(load_path(), "second.apk")
            self.assertEqual(load_adb_path(), "C:/工具/adb.exe")

    def test_configured_adb_discovered(self):
        with tempfile.TemporaryDirectory() as directory, patch("apk_placer.adb.bundled_adb", return_value=""):
            executable = Path(directory) / "adb.exe"
            executable.write_bytes(b"test fixture")
            self.assertEqual(find_adb(str(executable)), str(executable.resolve()))

    def test_portable_adb_overrides_old_saved_and_environment_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = root / "platform-tools"
            included.mkdir()
            for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
                (included / name).write_bytes(b"fixture")
            old = root / "old-adb.exe"
            old.write_bytes(b"old fixture")
            with patch("apk_placer.adb.sys.frozen", True, create=True), patch("apk_placer.adb.sys.executable", str(root / "App.exe")), patch("apk_placer.adb.shutil.which") as lookup:
                self.assertEqual(find_adb(str(old)), str((included / "adb.exe").resolve()))
                lookup.assert_not_called()

    def test_incomplete_portable_adb_uses_configured_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "platform-tools").mkdir()
            (root / "platform-tools/adb.exe").write_bytes(b"fixture")
            fallback = root / "external-adb.exe"
            fallback.write_bytes(b"fixture")
            with patch("apk_placer.adb.sys.frozen", True, create=True), patch("apk_placer.adb.sys.executable", str(root / "App.exe")):
                self.assertEqual(find_adb(str(fallback)), str(fallback.resolve()))

    def test_portable_adb_follows_moved_program_in_unicode_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("before", "移动后的程序"):
                root = Path(directory) / name
                (root / "platform-tools").mkdir(parents=True)
                for filename in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
                    (root / "platform-tools" / filename).write_bytes(b"fixture")
                with patch("apk_placer.adb.sys.frozen", True, create=True), patch("apk_placer.adb.sys.executable", str(root / "App.exe")):
                    self.assertEqual(find_adb(), str((root / "platform-tools/adb.exe").resolve()))


if __name__ == "__main__":
    unittest.main()
