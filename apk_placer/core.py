from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "QzzApkPlacer"


def load_path() -> str:
    try:
        return str(json.loads((data_directory() / "settings.json").read_text("utf-8"))["apk_path"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def save_path(path: str) -> None:
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "settings.tmp"
    temporary.write_text(json.dumps({"apk_path": path}, ensure_ascii=False), "utf-8")
    temporary.replace(directory / "settings.json")


def validate_apk(path: str) -> str | None:
    if not path:
        return "请选择要传输的 APK 文件"
    source = Path(path)
    if source.suffix.lower() != ".apk":
        return "请选择 .apk 文件"
    try:
        if not source.is_file():
            return "APK 路径已失效，请重新选择文件"
        if source.stat().st_size == 0:
            return "APK 文件为空，请重新选择文件"
        with source.open("rb") as stream:
            stream.read(1)
    except OSError:
        return "无法读取 APK，请检查文件权限或重新选择"
    return None


class Snapshot:
    """Finish a stable local copy before modifying anything on the PDA."""

    def __init__(self, path: str):
        self.source = Path(path)

    def __enter__(self) -> Path:
        error = validate_apk(str(self.source))
        if error:
            raise ValueError(error)
        self.directory = tempfile.TemporaryDirectory(prefix="qzz-apk-")
        target = Path(self.directory.name) / self.source.name
        try:
            before = self.source.stat()
            shutil.copyfile(self.source, target)
            after = self.source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("APK 正在更新，请等待更新结束后点击立即传输")
            return target
        except Exception:
            self.directory.cleanup()
            raise

    def __exit__(self, *_):
        self.directory.cleanup()


@dataclass(frozen=True)
class Device:
    id: str
    name: str


class DeliveryPolicy:
    """One successful transfer per physical connection; retry transient failures."""

    def __init__(self):
        self.path = ""
        self.present: set[str] = set()
        self.completed: set[str] = set()
        self.retry_after = 0.0
        self.manual = False
        self.paused = False
        self.path_lost = False

    def select(self, path: str):
        self.path = path
        self.path_lost = False
        self.completed.clear()
        self.retry_after = 0
        self.manual = True

    def observe(self, devices: list[Device]):
        self.present = {device.id for device in devices}
        self.completed.intersection_update(self.present)

    def ready(self, devices: list[Device], now: float | None = None) -> bool:
        if self.paused or self.path_lost or len(devices) != 1 or not self.path:
            return False
        now = time.monotonic() if now is None else now
        return (self.manual or devices[0].id not in self.completed) and now >= self.retry_after

    def success(self, device: Device):
        self.completed.add(device.id)
        self.manual = False
        self.retry_after = 0

    def failure(self, now: float | None = None):
        self.retry_after = (time.monotonic() if now is None else now) + 10

