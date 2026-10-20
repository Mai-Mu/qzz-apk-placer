import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_placer.core import Device
from apk_placer.worker import TransferWorker


class ClockStop:
    """Advance polling immediately; each callback models the next USB state."""
    def __init__(self, ticks):
        self.ticks = ticks
        self.tick = 0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        if self.tick < len(self.ticks):
            action = self.ticks[self.tick]
            self.tick += 1
            action()
        else:
            self.stopped = True


class FakeBackend:
    def __init__(self):
        self.devices = [Device("usb-1", "Test PDA")]
        self.transfers = []
        self.failure = False

    def list_devices(self):
        return self.devices

    def open(self, device):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def transfer(self, source, progress, cancelled):
        if self.failure:
            raise OSError("device disconnected")
        self.transfers.append(source.read_bytes())
        progress(source.stat().st_size, source.stat().st_size)


class WorkerTests(unittest.TestCase):
    def test_success_not_repeated_until_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "client.apk"
            source.write_bytes(b"first version")
            worker = TransferWorker(str(source))
            backend = FakeBackend()
            device = backend.devices[:]
            worker.stopping = ClockStop([
                lambda: None,
                lambda: setattr(backend, "devices", []),
                lambda: setattr(backend, "devices", device),
            ])
            worker._monitor(backend)
            self.assertEqual(backend.transfers, [b"first version", b"first version"])

    def test_restored_path_remains_paused_until_explicit_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "client.apk"
            source.write_bytes(b"old version")
            worker = TransferWorker(str(source))
            backend = FakeBackend()
            counts = []

            def restore():
                source.write_bytes(b"new version")

            def reselect():
                counts.append(len(backend.transfers))
                worker.command("select", str(source))

            worker.stopping = ClockStop([source.unlink, restore, reselect])
            worker._monitor(backend)
            self.assertEqual(counts, [1])
            self.assertEqual(backend.transfers, [b"old version", b"new version"])

    def test_failed_item_is_reported_without_repeating_the_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "client.apk"
            source.write_bytes(b"data")
            worker = TransferWorker(str(source))
            backend = FakeBackend()
            backend.failure = True
            worker.stopping = ClockStop([])
            with patch("apk_placer.worker.log.exception"):
                worker._monitor(backend)
            self.assertTrue(worker.policy.completed)
            self.assertEqual(worker.results[0].transfer, "传输失败")
            self.assertEqual(len(backend.transfers), 0)


if __name__ == "__main__":
    unittest.main()
