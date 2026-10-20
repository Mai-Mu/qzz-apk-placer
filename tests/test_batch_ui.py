from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from apk_placer.ui import MainWindow


class BatchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.paths = [str(Path(self.directory.name) / f"file-{i}.apk") for i in range(3)]
        for path in self.paths:
            Path(path).write_bytes(b"test fixture")
        with patch("apk_placer.ui.load_paths", return_value=[]):
            self.window = MainWindow(start_worker=False)

    def tearDown(self):
        self.window.quitting = True
        self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_editing_draft_does_not_save_or_queue_processing(self):
        with patch("apk_placer.ui.save_paths") as save:
            self.window.set_draft(self.paths)
            self.assertFalse(save.called)
            self.assertTrue(self.window.worker.commands.empty())
            self.assertEqual(self.window.applied_paths, [])
            self.assertEqual(self.window.apk_table.rowCount(), 3)

    def test_apply_saves_entire_order_and_queues_one_batch(self):
        self.window.set_draft(self.paths)
        with patch("apk_placer.ui.save_paths") as save:
            self.window.apply_list()
            save.assert_called_once_with(self.paths)
        self.assertEqual(self.window.worker.commands.get_nowait(), ("apply", self.paths))
        self.assertTrue(self.window.worker.commands.empty())

    def test_reorder_remove_and_duplicate_add(self):
        self.window.set_draft(self.paths + [self.paths[0]])
        self.assertEqual(len(self.window.draft_paths), 3)
        self.window.apk_table.selectRow(2)
        self.window.move_file(-1)
        self.assertEqual(self.window.draft_paths, [self.paths[0], self.paths[2], self.paths[1]])
        self.window.remove_file()
        self.assertEqual(self.window.draft_paths, [self.paths[0], self.paths[1]])

    def test_same_filename_rejected_without_changing_draft(self):
        other = Path(self.directory.name) / "other"
        other.mkdir()
        duplicate = other / Path(self.paths[0]).name
        duplicate.write_bytes(b"different")
        self.window.set_draft(self.paths)
        with patch("apk_placer.ui.QMessageBox.warning") as warning:
            self.assertFalse(self.window.set_draft(self.paths + [str(duplicate)]))
            warning.assert_called_once()
        self.assertEqual(self.window.draft_paths, self.paths)

    def test_invalid_row_marked_and_apply_blocked(self):
        Path(self.paths[1]).unlink()
        self.window.set_draft(self.paths)
        self.assertEqual(self.window.apk_table.item(1, 2).text(), "路径失效")
        self.assertFalse(self.window.apply_button.isEnabled())

    def test_each_file_result_and_failure_detail_displayed(self):
        self.window.set_draft(self.paths)
        self.window.set_results([{"path": self.paths[1], "transfer": "已传输", "install": "安装失败", "detail": "signature conflict"}])
        self.assertEqual(self.window.apk_table.item(1, 2).text(), "已传输")
        self.assertEqual(self.window.apk_table.item(1, 3).text(), "安装失败")
        self.assertIn("signature conflict", self.window.apk_table.item(1, 3).toolTip())

    def test_empty_list_can_be_applied_to_stop_processing(self):
        with patch("apk_placer.ui.save_paths") as save:
            self.window.apply_list()
            save.assert_called_once_with([])
        self.assertEqual(self.window.worker.commands.get_nowait(), ("apply", []))
        self.assertFalse(self.window.send_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
