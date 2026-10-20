from __future__ import annotations

import logging
import queue
import threading
import time

import comtypes
from PySide6.QtCore import QThread, Signal

from .core import DeliveryPolicy, Snapshot, validate_apk
from .wpd import WpdBackend

log = logging.getLogger(__name__)


class TransferWorker(QThread):
    status = Signal(str, str, str)
    device_changed = Signal(str)
    progress = Signal("qlonglong", "qlonglong")
    busy_changed = Signal(bool)
    record = Signal(str)

    def __init__(self, path: str, backend_factory=WpdBackend):
        super().__init__()
        self.policy = DeliveryPolicy()
        self.policy.path = path
        self.commands = queue.Queue()
        self.stopping = threading.Event()
        self.backend_factory = backend_factory
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
            comtypes.CoUninitialize()

    def _monitor(self, backend):
        policy = self.policy
        last_devices = None
        while not self.stopping.is_set():
            while True:
                try:
                    action, value = self.commands.get_nowait()
                except queue.Empty:
                    break
                if action == "select":
                    policy.select(value)
                elif action == "manual":
                    policy.manual = True
                    policy.retry_after = 0
                elif action == "pause":
                    policy.paused = bool(value)
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
            names = tuple((d.id, d.name) for d in devices)
            if names != last_devices:
                label = "、".join(d.name for d in devices) or "尚未连接"
                self.device_changed.emit(label)
                self.record.emit(f"设备：{label}")
                last_devices = names
            if error or policy.path_lost:
                self.announce("invalid", "等待选择 APK" if not policy.path else "自动传输已暂停",
                              error or "请重新选择有效的 APK，以恢复自动传输")
            elif policy.paused:
                self.announce("paused", "自动传输已暂停", "点击「恢复自动传输」继续等待设备接入")
            elif len(devices) > 1:
                self.announce("paused", "请只连接一台 PDA", "检测到多个 USB 便携设备，保留目标设备后会自动继续")
            elif not devices:
                self.announce("waiting", "就绪，等待 PDA 接入", "连接 USB 数据线，在 PDA 上选择「文件传输」")
            elif policy.ready(devices):
                device = devices[0]
                self.busy_changed.emit(True)
                self.announce("copying", "正在准备 APK", "正在生成稳定副本，请稍候")
                try:
                    with Snapshot(policy.path) as source:
                        if self.stopping.is_set():
                            break
                        with backend.open(device) as session:
                            self.announce("copying", "正在传输到 PDA", f"{device.name} · 内部存储 / Download")
                            session.transfer(source, self.progress.emit, self.stopping.is_set)
                    policy.success(device)
                    self.announce("success", "APK 已送达", "文件已保存到 Download；可在 PDA 上打开安装")
                    self.record.emit(f"传输成功：{source.name} → {device.name} / Download")
                    log.info("Transferred %s to %s", source.name, device.name)
                except InterruptedError:
                    self.record.emit("传输已取消")
                except Exception as exc:
                    log.exception("Transfer failed")
                    policy.failure()
                    self.announce("error", "传输未完成，稍后自动重试", "请保持 PDA 解锁并使用文件传输模式，也可点击「立即传输」重试")
                    self.record.emit(f"传输失败：{str(exc)[:240]}")
                finally:
                    self.busy_changed.emit(False)
            self.stopping.wait(1.5)
