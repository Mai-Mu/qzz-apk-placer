"""ADB discovery and explicitly targeted, data-preserving APK installation."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable

from .core import data_directory

PLATFORM_TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools"


def bundled_adb() -> str:
    """Prefer the complete portable bundle, including after moving its folder."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    directory = base / "platform-tools"
    if all((directory / name).is_file() for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")):
        return str((directory / "adb.exe").resolve())
    return ""


def find_adb(configured: str = "") -> str:
    included = bundled_adb()
    if included:
        return included
    candidates = [Path(configured)] if configured else []
    candidates.append(data_directory() / "platform-tools" / "adb.exe")
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "platform-tools" / "adb.exe")
    candidates.append(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    located = shutil.which("adb")
    if located:
        candidates.append(Path(located))
    return next((str(path.resolve()) for path in candidates if path.is_file()), "")


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str


def parse_devices(output: str) -> list[AdbDevice]:
    result = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[1] not in ("device", "unauthorized", "offline", "recovery", "sideload", "bootloader"):
            continue
        serial = fields[0]
        # Do not install into emulators or a remembered Wi-Fi ADB connection.
        if serial.startswith("emulator-") or ":" in serial or "._tcp" in serial:
            continue
        result.append(AdbDevice(serial, fields[1]))
    return result


def match_device(devices: list[AdbDevice], serials: tuple[str, ...]) -> AdbDevice | None:
    identities = {serial.casefold() for serial in serials if serial}
    matches = [device for device in devices if device.serial.casefold() in identities]
    return matches[0] if len(matches) == 1 else None


ERRORS = {
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": "签名与已安装应用不一致，请人工确认；未卸载旧应用",
    "INSTALL_FAILED_VERSION_DOWNGRADE": "设备上的版本更高，系统拒绝降级；未卸载旧应用",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": "PDA 存储空间不足，请清理空间后重试",
    "INSTALL_FAILED_USER_RESTRICTED": "设备策略或 USB 安装设置阻止安装，请在 PDA 上检查",
    "INSTALL_FAILED_OLDER_SDK": "APK 要求的 Android 版本高于当前设备",
    "INSTALL_FAILED_NO_MATCHING_ABIS": "APK 不支持这台 PDA 的处理器架构",
    "INSTALL_FAILED_INVALID_APK": "APK 无效或不完整，请检查安装包",
    "INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES": "安装包证书冲突，请人工确认；未卸载旧应用",
    "INSTALL_FAILED_VERIFICATION_FAILURE": "设备的安装验证未通过，请查看 PDA 提示",
}


class InstallError(RuntimeError):
    pass


def explain_failure(output: str) -> str:
    for code, message in ERRORS.items():
        if code in output:
            return f"{message}（{code}）"
    return (output.strip() or "ADB 未返回成功结果")[-1500:]


class AdbClient:
    def __init__(self, path: str):
        self.path = path

    def _run(self, arguments: list[str], timeout: float, cancelled: Callable[[], bool] = lambda: False) -> tuple[int, str]:
        if cancelled():
            raise InterruptedError("操作已取消")
        process = subprocess.Popen(
            [self.path, *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancelled():
                    raise InterruptedError("已停止等待 ADB；设备端安装可能已开始，请检查 PDA")
                if time.monotonic() >= deadline:
                    raise InstallError("ADB 操作超时，请检查 PDA 上的安装结果后手动重试")
                try:
                    output, _ = process.communicate(timeout=0.2)
                    return process.returncode, output.decode("utf-8", errors="replace")
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def devices(self, cancelled: Callable[[], bool] = lambda: False) -> list[AdbDevice]:
        code, output = self._run(["devices", "-l"], 12, cancelled)
        if code:
            raise InstallError(explain_failure(output))
        return parse_devices(output)

    def install(self, serial: str, source: Path, cancelled: Callable[[], bool]):
        # -s is mandatory: never allow adb to choose an arbitrary target.
        # -r keeps application data. No uninstall, downgrade or permission flags.
        code, output = self._run(["-s", serial, "install", "-r", str(source)], 300, cancelled)
        if code or not re.search(r"(?m)^\s*Success\s*$", output):
            raise InstallError(explain_failure(output))
