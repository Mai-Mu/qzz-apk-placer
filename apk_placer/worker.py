from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import queue
import threading
import time

import comtypes
from PySide6.QtCore import QThread, Signal

from .adb import AdbClient, find_adb, match_device
from .core import Device, DeliveryPolicy, Snapshot, load_adb_path, validate_apk
from .wpd import WpdBackend

log = logging.getLogger(__name__)


@dataclass
class PendingInstall:
    device: Device
    snapshot: Snapshot
    source: Path
    serials: tuple[str, ...]
    missing_since: float | None = None


class TransferWorker(QThread):
    status = Signal(str, str, str)
    device_changed = Signal(str)
    progress = Signal("qlonglong", "qlonglong")
    busy_changed = Signal(bool)
    record = Signal(str)
    transfer_state = Signal(str)
    install_state = Signal(str, str)

    def __init__(self, path: str, backend_factory=WpdBackend, installer_factory=AdbClient, adb_locator=find_adb):
        super().__init__()
        self.policy = DeliveryPolicy()
        self.policy.path = path
        self.commands = queue.Queue()
        self.stopping = threading.Event()
        self.backend_factory = backend_factory
        self.installer_factory = installer_factory
        self.adb_locator = adb_locator
        self.adb_path = load_adb_path()
        self.auto_install = False  # Deliberately not persisted between launches.
        self.pending: PendingInstall | None = None
        self.reenumerating_completion = None
        self.last_status = None

    def command(self, action: str, value=None):
        self.commands.put((action, value))

    def stop(self):
        self.stopping.set()

    def announce(self, state: str, title: str, detail: str):
        current = state, title, detail
        if current != self.last_status:
            self.last_status = current
            log.info("Status: %s | %s", state, title)
            self.status.emit(*current)

    def _discard_pending(self):
        if self.pending:
            self.pending.snapshot.__exit__()
            self.pending = None

    def _commands(self):
        while True:
            try:
                action, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if action in ("select", "manual"):
                self._discard_pending()
                self.reenumerating_completion = None
                if action == "select":
                    self.policy.select(value)
                else:
                    self.policy.manual = True
                    self.policy.retry_after = 0
            elif action == "pause":
                self.policy.paused = bool(value)
            elif action == "auto_install":
                self.auto_install = bool(value)
                if not self.auto_install and self.pending:
                    self._discard_pending()
                    self.announce("success", "文件已送达，已停止等待安装", "自动安装已关闭，后续任务只传输文件")
                self.install_state.emit("ready" if self.auto_install else "off",
                                        "已开启 · 从下一次传输任务生效" if self.auto_install else "已关闭 · 仅传输 APK")
            elif action == "adb_path":
                self.adb_path = value

    def run(self):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            backend = self.backend_factory()
            self._monitor(backend)
            del backend
        except Exception:
            log.exception("Device monitor failed")
            self.announce("error", "设备服务启动失败", "请退出后重新打开程序；详细原因已写入日志")
        finally:
            self._discard_pending()
            comtypes.CoUninitialize()

    def _monitor(self, backend):
        policy = self.policy
        last_devices = None
        while not self.stopping.is_set():
            self._commands()
            error = validate_apk(policy.path)
            if error and policy.path:
                policy.path_lost = True
            try:
                devices = backend.list_devices()
            except Exception:
                log.exception("Device enumeration failed")
                self.announce("error", "暂时无法读取设备", "请检查 USB 连接，程序将在后台继续检测")
                self.stopping.wait(3)
                continue
            policy.observe(devices)
            if self.reenumerating_completion:
                serials, expires = self.reenumerating_completion
                if time.monotonic() >= expires:
                    self.reenumerating_completion = None
                elif devices:
                    if {s.casefold() for s in devices[0].serials} & {s.casefold() for s in serials}:
                        policy.completed.add(devices[0].id)
                    self.reenumerating_completion = None
            names = tuple((d.id, d.name) for d in devices)
            if names != last_devices:
                label = "、".join(d.name for d in devices) or "尚未连接"
                self.device_changed.emit(label)
                self.record.emit(f"设备：{label}")
                last_devices = names
                if not devices and not self.pending:
                    self.transfer_state.emit("等待设备连接")
            if error or policy.path_lost:
                self._discard_pending()
                self.announce("invalid", "等待选择 APK" if not policy.path else "自动传输已暂停",
                              error or "请重新选择有效的 APK，以恢复自动传输")
                self.install_state.emit("blocked", "等待重新选择有效 APK" if self.auto_install else "已关闭 · 仅传输 APK")
            elif policy.paused:
                self.announce("paused", "自动传输已暂停", "点击「恢复自动传输」继续；待安装任务会保留")
            elif len(devices) > 1:
                self.announce("paused", "请只连接一台 PDA", "检测到多个 USB 便携设备，保留目标设备后会自动继续")
            elif self.pending:
                self._continue_install(devices)
            elif not devices:
                self.announce("waiting", "就绪，等待 PDA 接入", "连接 USB 数据线，在 PDA 上选择「文件传输」")
            elif policy.ready(devices):
                self._transfer(backend, devices[0])
            self.stopping.wait(1.5)

    def _transfer(self, backend, device: Device):
        # Capture the toggle at task start. Enabling it later never installs an
        # already completed copy. Commands queued during copying run next tick.
        install_requested = self.auto_install
        snapshot = Snapshot(self.policy.path)
        retained = False
        self.busy_changed.emit(True)
        self.transfer_state.emit("正在准备文件")
        self.install_state.emit("queued" if install_requested else "off",
                                "等待文件传输完成" if install_requested else "已关闭 · 仅传输 APK")
        self.announce("copying", "正在准备 APK", "正在生成稳定副本，请稍候")
        try:
            source = snapshot.__enter__()
            if self.stopping.is_set():
                raise InterruptedError("传输已取消")
            with backend.open(device) as session:
                serial = session.serial_number() if install_requested else ""
                serials = tuple(dict.fromkeys((*device.serials, *([serial] if serial else []))))
                self.transfer_state.emit("正在传输到 Download")
                self.announce("copying", "正在传输到 PDA", f"{device.name} · 内部存储 / Download")
                session.transfer(source, self.progress.emit, self.stopping.is_set)
            self.policy.success(device)
            self.transfer_state.emit("已传输到 Download")
            self.record.emit(f"传输成功：{source.name} → {device.name} / Download")
            log.info("Transferred %s to %s", source.name, device.name)
            if install_requested:
                self.pending = PendingInstall(device, snapshot, source, serials)
                retained = True
                self.announce("waiting_install", "文件已送达，等待安装", "正在检查 USB 调试连接和电脑授权")
            else:
                self.announce("success", "APK 已送达", "文件已保存到 Download；可在 PDA 上打开安装")
        except InterruptedError:
            self.record.emit("传输已取消")
        except Exception as exc:
            log.exception("Transfer failed")
            self.policy.failure()
            self.transfer_state.emit("传输失败，稍后重试")
            self.announce("error", "传输未完成，稍后自动重试", "请保持 PDA 解锁并使用文件传输模式，也可点击「立即传输」重试")
            self.record.emit(f"传输失败：{str(exc)[:240]}")
        finally:
            if not retained and hasattr(snapshot, "directory"):
                snapshot.__exit__()
            self.busy_changed.emit(False)

    def _wait_install(self, detail: str):
        self.install_state.emit("waiting", detail)
        self.announce("waiting_install", "文件已送达，等待安装", detail)

    def _continue_install(self, devices: list[Device]):
        pending = self.pending
        if not pending:
            return
        if devices:
            current = devices[0]
            same_id = current.id == pending.device.id
            same_serial = bool({s.casefold() for s in current.serials} & {s.casefold() for s in pending.serials})
            if not same_id and not same_serial:
                self._discard_pending()
                self.install_state.emit("ready", "设备已更换，等待新任务")
                return
            pending.missing_since = None
            self.policy.completed.add(current.id)
        else:
            # Enabling debugging may re-enumerate MTP. Retain the stable copy
            # briefly and require the exact same USB ADB serial before installing.
            if pending.missing_since is None:
                pending.missing_since = time.monotonic()
            if time.monotonic() - pending.missing_since >= 20:
                self._discard_pending()
                self.install_state.emit("ready", "设备已断开，等待下次传输")
                return
        adb_path = self.adb_locator(self.adb_path)
        if not adb_path:
            self._wait_install("未找到 ADB，请点击「配置 ADB」选择官方工具")
            return
        if not pending.serials:
            self._wait_install("无法取得这台 PDA 的 USB 序列号，请重新连接设备后重试")
            return
        try:
            installer = self.installer_factory(adb_path)
            try:
                candidates = installer.devices(self.stopping.is_set)
            except (OSError, RuntimeError) as exc:
                self._wait_install(f"ADB 连接暂未就绪：{str(exc)[:200]}")
                return
            target = match_device(candidates, pending.serials)
            if not target:
                self._wait_install("等待这台 PDA 的 USB 调试连接；请开启 USB 调试并检查驱动")
                return
            if target.state != "device":
                self._wait_install("请在 PDA 上允许这台电脑进行 USB 调试" if target.state == "unauthorized"
                                   else "调试设备尚未就绪，请保持 PDA 解锁并检查 USB 连接")
                return
            self.busy_changed.emit(True)
            self.install_state.emit("installing", "正在安装，请保持 USB 连接")
            self.announce("installing", "文件已送达，正在安装", f"{pending.device.name} · 保留应用数据覆盖更新")
            installer.install(target.serial, pending.source, self.stopping.is_set)
            self.install_state.emit("success", "安装成功")
            self.announce("success", "APK 已传输并安装", "安装成功，可在 PDA 上打开应用")
            self.record.emit(f"安装成功：{pending.source.name} → {pending.device.name}")
            log.info("Installed %s to %s", pending.source.name, pending.device.name)
            if not devices:
                self.reenumerating_completion = (pending.serials, time.monotonic() + 20)
            self._discard_pending()
        except InterruptedError:
            self.record.emit("已停止等待安装结果，请在 PDA 上检查安装状态")
            self._discard_pending()
        except Exception as exc:
            # Installation failures can be permanent (signature/version/policy).
            # Keep the successful copy, avoid an endless install/uninstall loop.
            detail = str(exc)[:1500]
            log.exception("Install failed")
            self.install_state.emit("error", detail)
            self.announce("error", "文件已送达，安装未完成", detail)
            self.record.emit(f"安装失败：{detail}")
            self._discard_pending()
        finally:
            self.busy_changed.emit(False)
