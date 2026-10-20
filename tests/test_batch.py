import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apk_placer.core import list_errors, load_paths, save_paths, save_setting, unique_paths
from apk_placer.adb import InstallError
from apk_placer.worker import TransferWorker
from test_worker import ClockStop
from test_install_flow import InstallBackend, FakeInstaller


class BatchConfigurationTests(unittest.TestCase):
    def test_legacy_path_is_loaded_as_one_item(self):
        with tempfile.TemporaryDirectory() as directory, patch("apk_placer.core.data_directory", return_value=Path(directory)):
            save_setting("apk_path", "C:/old.apk")
            self.assertEqual(load_paths(), ["C:/old.apk"])

    def test_list_order_and_adb_setting_preserved_and_empty_overrides_legacy(self):
        with tempfile.TemporaryDirectory() as directory, patch("apk_placer.core.data_directory", return_value=Path(directory)):
            save_setting("apk_path", "legacy.apk")
            save_setting("adb_path", "tools/adb.exe")
            save_paths(["second.apk", "first.apk"])
            self.assertEqual(load_paths(), ["second.apk", "first.apk"])
            self.assertEqual(json.loads((Path(directory) / "settings.json").read_text())["adb_path"], "tools/adb.exe")
            save_paths([])
            self.assertEqual(load_paths(), [])

    def test_duplicate_path_ignored_and_same_filename_in_other_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "other").mkdir()
            first, second = root / "app.apk", root / "other" / "APP.apk"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            self.assertEqual(unique_paths([str(first), str(first)]), [str(first)])
            errors = list_errors([str(first), str(second)])
            self.assertEqual(len(errors), 2)
            self.assertTrue(all("文件名冲突" in error for error in errors.values()))


class BatchFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.paths = [str(Path(self.directory.name) / f"app-{i}.apk") for i in range(3)]
        for i, path in enumerate(self.paths):
            Path(path).write_bytes(f"version-{i}".encode())
        self.events = []
        self.backend = InstallBackend()
        self.installer = FakeInstaller()
        base_transfer = self.backend.transfer
        base_install = self.installer.install
        self.fail_transfer = set()
        self.fail_install = set()

        def transfer(source, progress, cancelled):
            self.events.append(("copy", source.name))
            if source.name in self.fail_transfer:
                raise OSError("fixture transfer failure")
            base_transfer(source, progress, cancelled)

        def install(serial, source, cancelled):
            self.events.append(("install", source.name))
            if source.name in self.fail_install:
                raise InstallError("fixture signature conflict")
            base_install(serial, source, cancelled)

        self.backend.transfer = transfer
        self.installer.install = install
        self.worker = TransferWorker(self.paths, installer_factory=lambda _: self.installer, adb_locator=lambda _: "adb.exe")
        self.statuses = []
        self.worker.status.connect(lambda *args: self.statuses.append(args))

    def tearDown(self):
        self.worker._discard_pending()
        self.directory.cleanup()

    def run_ticks(self, actions=None):
        self.worker.stopping = ClockStop(actions if actions is not None else [lambda: None] * 10)
        with patch("apk_placer.worker.log.exception"):
            self.worker._monitor(self.backend)

    def test_all_copies_happen_before_ordered_installations(self):
        self.worker.command("auto_install", True)
        self.run_ticks()
        names = [Path(path).name for path in self.paths]
        self.assertEqual(self.events, [("copy", name) for name in names] + [("install", name) for name in names])
        self.assertTrue(all(item.install == "安装成功" for item in self.worker.results))

    def test_one_failed_transfer_does_not_block_others_and_is_not_installed(self):
        self.worker.command("auto_install", True)
        self.fail_transfer.add("app-1.apk")
        self.run_ticks()
        self.assertEqual([name for stage, name in self.events if stage == "install"], ["app-0.apk", "app-2.apk"])
        self.assertEqual(self.worker.results[1].transfer, "传输失败")
        self.assertEqual(self.statuses[-1][0], "warning")
        self.assertIn("app-1.apk", self.statuses[-1][2])

    def test_one_failed_install_does_not_block_later_install_or_repeat_batch(self):
        self.worker.command("auto_install", True)
        self.fail_install.add("app-1.apk")
        self.run_ticks()
        self.assertEqual(len(self.events), 6)
        self.assertEqual([item.install for item in self.worker.results], ["安装成功", "安装失败", "安装成功"])

    def test_any_invalid_path_blocks_entire_batch_before_first_copy(self):
        Path(self.paths[1]).unlink()
        self.run_ticks()
        self.assertFalse(self.events)
        self.assertTrue(self.worker.policy.path_lost)

    def test_lost_path_during_batch_stops_all_remaining_items(self):
        self.worker.command("auto_install", True)
        self.run_ticks([lambda: Path(self.paths[2]).unlink(), lambda: None])
        self.assertEqual(self.events, [("copy", "app-0.apk")])
        self.assertIsNone(self.worker.pending)
        self.assertTrue(self.worker.policy.path_lost)

    def test_pause_and_resume_continue_remaining_items_without_recopy(self):
        counts = []

        def resume():
            counts.append(len(self.events))
            self.worker.command("pause", False)

        self.run_ticks([lambda: self.worker.command("pause", True), resume] + [lambda: None] * 5)
        self.assertEqual(counts, [1])
        self.assertEqual(len(self.events), 3)

    def test_enable_during_copy_does_not_retroactively_install_batch(self):
        self.run_ticks([lambda: self.worker.command("auto_install", True)] + [lambda: None] * 7)
        self.assertEqual(len(self.events), 3)
        self.assertTrue(all(stage == "copy" for stage, _ in self.events))

    def test_disable_during_copy_finishes_all_copies_but_does_not_install(self):
        self.worker.command("auto_install", True)
        self.run_ticks([lambda: self.worker.command("auto_install", False)] + [lambda: None] * 7)
        self.assertEqual(len(self.events), 3)
        self.assertTrue(all(item.snapshot is None for item in self.worker.results))

    def test_applied_empty_list_stops_all_automatic_processing(self):
        self.worker.command("apply", [])
        self.run_ticks()
        self.assertFalse(self.events)
        self.assertEqual(self.worker.policy.paths, [])

    def test_list_order_is_respected_after_apply(self):
        self.worker.command("apply", self.paths[::-1])
        self.run_ticks()
        self.assertEqual([name for _, name in self.events], ["app-2.apk", "app-1.apk", "app-0.apk"])

    def test_not_limited_to_two_apks(self):
        paths = []
        for i in range(8):
            path = Path(self.directory.name) / f"many-{i}.apk"
            path.write_bytes(b"data")
            paths.append(str(path))
        self.worker.command("apply", paths)
        self.run_ticks([lambda: None] * 12)
        self.assertEqual(len(self.events), 8)


if __name__ == "__main__":
    unittest.main()
