from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def data_directory() -> Path:
    if os.environ.get("QZZ_APK_PLACER_DATA_DIR"):
        return Path(os.environ["QZZ_APK_PLACER_DATA_DIR"]).resolve()
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "QzzApkPlacer"


def load_path() -> str:
    paths = load_paths()
    return paths[0] if paths else ""


def load_paths() -> list[str]:
    try:
        settings = json.loads((data_directory() / "settings.json").read_text("utf-8"))
        if "apk_paths" in settings:
            values = settings["apk_paths"]
            return unique_paths(values) if isinstance(values, list) and all(isinstance(p, str) for p in values) else []
        legacy = settings.get("apk_path", "")
        return [legacy] if isinstance(legacy, str) and legacy else []
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def save_path(path: str) -> None:
    save_paths([path] if path else [])


def save_paths(paths: list[str]) -> None:
    save_setting("apk_paths", unique_paths(paths))


def path_identity(path: str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def unique_paths(paths: list[str]) -> list[str]:
    seen, result = set(), []
    for path in paths:
        identity = path_identity(path)
        if identity not in seen:
            result.append(path)
            seen.add(identity)
    return result


def list_errors(paths: list[str]) -> dict[str, str]:
    if not paths:
        return {"": "请添加至少一个 APK 并应用列表"}
    errors = {}
    names = {}
    for path in paths:
        error = validate_apk(path)
        if error:
            errors[path] = error
        name = Path(path).name.casefold()
        if name in names and path_identity(names[name]) != path_identity(path):
            message = f"文件名冲突：{Path(path).name}，请先重命名其中一个"
            errors[path] = errors[names[name]] = message
        names[name] = path
    return errors


def load_adb_path() -> str:
    try:
        return str(json.loads((data_directory() / "settings.json").read_text("utf-8")).get("adb_path", ""))
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def save_setting(name: str, value: str | list[str]) -> None:
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads((directory / "settings.json").read_text("utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}
    settings[name] = value
    temporary = directory / "settings.tmp"
    temporary.write_text(json.dumps(settings, ensure_ascii=False), "utf-8")
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
    serials: tuple[str, ...] = ()


class DeliveryPolicy:
    """One successful transfer per physical connection; retry transient failures."""

    def __init__(self):
        self.paths: list[str] = []
        self.present: set[str] = set()
        self.completed: set[str] = set()
        self.retry_after = 0.0
        self.manual = False
        self.paused = False
        self.path_lost = False

    @property
    def path(self) -> str:
        return self.paths[0] if self.paths else ""

    @path.setter
    def path(self, value: str):
        self.paths = [value] if value else []

    def select(self, paths: str | list[str]):
        self.paths = unique_paths([paths] if isinstance(paths, str) else paths)
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

