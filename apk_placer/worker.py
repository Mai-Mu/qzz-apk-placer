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
from .core import Device, DeliveryPolicy, Snapshot, load_adb_path, list_errors, unique_paths
from .wpd import WpdBackend

log = logging.getLogger(__name__)


@dataclass
class BatchItem:
    path: str
    transfer: str = "等待传输"
    install: str = "未启用"
    detail: str = ""
    snapshot: Snapshot | None = None
    source: Path | None = None

    def close(self):
        if self.snapshot:
            self.snapshot.__exit__()
            self.snapshot = None


@dataclass
class Batch:
    device: Device
    items: list[BatchItem]
    install_requested: bool
    serials: tuple[str, ...]
    stage: str = "copy"
    copy_index: int = 0
    install_index: int = 0
    missing_since: float | None = None

    @property
    def source(self):
        return next((item.source for item in self.items if item.source), None)


class TransferWorker(QThread):
    status = Signal(str, str, str)
    device_changed = Signal(str)
    progress = Signal("qlonglong", "qlonglong")
    busy_changed = Signal(bool)
    record = Signal(str)
    transfer_state = Signal(str)
    install_state = Signal(str, str)
    results_changed = Signal(object)

    def __init__(self, paths: str | list[str], backend_factory=WpdBackend, installer_factory=AdbClient, adb_locator=find_adb):
        super().__init__()
        self.policy = DeliveryPolicy()
        self.policy.paths = unique_paths([paths] if isinstance(paths, str) and paths else paths if isinstance(paths, list) else [])
        self.commands = queue.Queue()
        self.stopping = threading.Event()
        self.backend_factory = backend_factory
        self.installer_factory = installer_factory
        self.adb_locator = adb_locator
        self.adb_path = load_adb_path()
        self.auto_install = False
        self.pending: Batch | None = None
        self.results: list[BatchItem] = []
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

    def _emit_results(self):
        self.results_changed.emit([{"path": item.path, "transfer": item.transfer,
                                    "install": item.install, "detail": item.detail} for item in self.results])

    def _discard_pending(self, reason="任务已取消"):
        if self.pending:
            for item in self.pending.items:
                if item.transfer in ("等待传输", "正在传输"):
                    item.transfer = "已取消"
                    item.detail = reason
                if item.install in ("等待安装", "正在安装"):
                    item.install = "已取消"
                item.close()
            self.pending = None
            self._emit_results()

    def _commands(self):
        while True:
            try:
                action, value = self.commands.get_nowait()
            except queue.Empty:
                return
            if action in ("apply", "select", "manual"):
                self._discard_pending("已开始新任务")
                self.reenumerating_completion = None
                if action in ("apply", "select"):
                    self.policy.select(value)
                    self.results = []
                    self._emit_results()
                else:
                    self.policy.manual = True
                    self.policy.retry_after = 0
            elif action == "pause":
                self.policy.paused = bool(value)
            elif action == "auto_install":
                self.auto_install = bool(value)
                if not self.auto_install and self.pending:
                    self.pending.install_requested = False
                    for item in self.pending.items:
                        if item.install == "等待安装":
                            item.install = "未启用"
                        if item.transfer == "已传输":
                            item.close()
                    if self.pending.stage == "install":
                        self._finish()
                    self._emit_results()
                self.install_state.emit("ready" if self.auto_install else "off",
                                        "已开启 · 从下一批任务生效" if self.auto_install else "已关闭 · 仅传输 APK")
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
            self._discard_pending("程序已退出")
            comtypes.CoUninitialize()

    def _monitor(self, backend):
        policy = self.policy
        last_devices = None
        while not self.stopping.is_set():
            self._commands()
            errors = list_errors(policy.paths)
            if errors and policy.paths:
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
            if errors or policy.path_lost:
                self._discard_pending("列表路径失效，整批已暂停")
                detail = next(iter(errors.values())) if errors else "请修正列表并重新点击「应用列表」"
                self.announce("invalid", "等待应用 APK 列表" if not policy.paths else "整批任务已暂停", detail)
                self.install_state.emit("blocked", "等待有效列表" if self.auto_install else "已关闭 · 仅传输 APK")
            elif policy.paused:
                self.announce("paused", "批量任务已暂停", "当前文件已处理结束，恢复后继续剩余项")
            elif len(devices) > 1:
                self.announce("paused", "请只连接一台设备", "保留目标 Pad / PDA 后会自动继续")
            elif self.pending:
                self._continue_batch(backend, devices)
            elif not devices:
                self.announce("waiting", "就绪，等待设备接入", f"已应用 {len(policy.paths)} 个 APK，连接后自动处理")
            elif policy.ready(devices):
                self._start_batch(backend, devices[0])
            self.stopping.wait(1.5)

    def _start_batch(self, backend, device):
        requested = self.auto_install
        items = [BatchItem(path, install="等待安装" if requested else "未启用") for path in self.policy.paths]
        self.results = items
        self.pending = Batch(device, items, requested, device.serials)
        self.busy_changed.emit(True)
        self.announce("copying", "正在准备整批 APK", f"共 {len(items)} 个文件，先生成稳定副本")
        try:
            for item in items:
                if self.stopping.is_set():
                    raise InterruptedError()
                try:
                    item.snapshot = Snapshot(item.path)
                    item.source = item.snapshot.__enter__()
                except Exception as exc:
                    if item.snapshot and hasattr(item.snapshot, "directory"):
                        item.close()
                    else:
                        item.snapshot = None
                    item.transfer = "传输失败"
                    item.install = "跳过（传输失败）" if requested else "未启用"
                    item.detail = str(exc)[:1500]
            # All source paths are checked again before the first device write.
            if list_errors(self.policy.paths):
                self.policy.path_lost = True
                self._discard_pending("路径失效，未开始传输")
                return
            self._emit_results()
        except InterruptedError:
            self._discard_pending()
        finally:
            self.busy_changed.emit(False)
        if self.pending:
            self._copy_next(backend)

    def _continue_batch(self, backend, devices):
        batch = self.pending
        if not batch:
            return
        if devices:
            current = devices[0]
            overlap = bool({s.casefold() for s in current.serials} & {s.casefold() for s in batch.serials})
            same = overlap or (current.id == batch.device.id and (not current.serials or not batch.device.serials))
            if not same:
                self._discard_pending("目标设备已更换")
                self.record.emit("目标设备已更换，旧批次剩余项已取消")
                return
            batch.device = current
            batch.missing_since = None
            self.policy.completed.add(current.id)
        else:
            if batch.missing_since is None:
                batch.missing_since = time.monotonic()
            if time.monotonic() - batch.missing_since >= 20:
                self._discard_pending("设备已断开")
                self.record.emit("设备已断开，批次剩余项已取消")
                return
            if batch.stage == "copy":
                self.announce("waiting", "等待设备重新连接", "保留已完成项，短暂重新连接后继续传输")
                return
        if batch.stage == "copy":
            self._copy_next(backend)
        else:
            self._install_next(devices)

    def _copy_next(self, backend):
        batch = self.pending
        item = batch.items[batch.copy_index]
        number = batch.copy_index + 1
        if item.transfer != "传输失败":
            self.busy_changed.emit(True)
            item.transfer = "正在传输"
            self._emit_results()
            self.announce("copying", f"正在传输 {number}/{len(batch.items)}", Path(item.path).name)
            try:
                with backend.open(batch.device) as session:
                    if batch.install_requested:
                        serial = session.serial_number()
                        batch.serials = tuple(dict.fromkeys((*batch.serials, *([serial] if serial else []))))
                    session.transfer(item.source, self.progress.emit, self.stopping.is_set)
                item.transfer = "已传输"
                self.record.emit(f"传输成功 {number}/{len(batch.items)}：{Path(item.path).name}")
                if not batch.install_requested:
                    item.close()
            except InterruptedError:
                self._discard_pending("传输已取消")
                return
            except Exception as exc:
                log.exception("Batch item transfer failed")
                item.transfer = "传输失败"
                item.install = "跳过（传输失败）" if batch.install_requested else "未启用"
                item.detail = str(exc)[:1500]
                item.close()
                self.record.emit(f"传输失败：{Path(item.path).name} · {item.detail}")
            finally:
                self.busy_changed.emit(False)
        batch.copy_index += 1
        self._emit_results()
        self._emit_counts()
        if batch.copy_index == len(batch.items):
            if batch.install_requested and any(item.transfer == "已传输" for item in batch.items):
                batch.stage = "install"
                self.announce("waiting_install", "文件传输阶段已结束", "开始按列表顺序安装已传输的 APK")
            else:
                self._finish()

    def _wait_install(self, detail):
        self.install_state.emit("waiting", detail)
        self.announce("waiting_install", "文件已送达，等待安装", detail)

    def _install_next(self, devices):
        batch = self.pending
        while batch.install_index < len(batch.items) and batch.items[batch.install_index].transfer != "已传输":
            batch.install_index += 1
        if batch.install_index == len(batch.items):
            self._finish(devices)
            return
        adb_path = self.adb_locator(self.adb_path)
        if not adb_path:
            self._wait_install("未找到 ADB，请点击「配置 ADB」选择官方工具")
            return
        if not batch.serials:
            self._wait_install("无法取得目标 USB 序列号，请重新连接后重试")
            return
        installer = self.installer_factory(adb_path)
        try:
            target = match_device(installer.devices(self.stopping.is_set), batch.serials)
        except InterruptedError:
            self._discard_pending()
            return
        except (OSError, RuntimeError) as exc:
            self._wait_install(f"ADB 暂未就绪：{str(exc)[:200]}")
            return
        if not target or target.state != "device":
            self._wait_install("请在设备上允许这台电脑进行 USB 调试" if target and target.state == "unauthorized"
                               else "等待目标设备的 USB 调试连接，请检查调试开关和驱动")
            return
        item = batch.items[batch.install_index]
        item.install = "正在安装"
        self._emit_results()
        self.busy_changed.emit(True)
        self.install_state.emit("installing", f"正在安装 {batch.install_index + 1}/{len(batch.items)}")
        self.announce("installing", f"正在安装 {batch.install_index + 1}/{len(batch.items)}", Path(item.path).name)
        try:
            installer.install(target.serial, item.source, self.stopping.is_set)
            item.install = "安装成功"
            self.record.emit(f"安装成功：{Path(item.path).name}")
        except InterruptedError:
            self._discard_pending("停止等待安装结果，请在设备上检查")
            return
        except Exception as exc:
            log.exception("Batch item install failed")
            item.install = "安装失败"
            item.detail = str(exc)[:1500]
            self.record.emit(f"安装失败：{Path(item.path).name} · {item.detail}")
        finally:
            item.close()
            self.busy_changed.emit(False)
        batch.install_index += 1
        self._emit_results()
        self._emit_counts()
        if not any(item.transfer == "已传输" and item.install == "等待安装" for item in batch.items):
            self._finish(devices)

    def _emit_counts(self):
        total = len(self.results)
        copied = sum(item.transfer == "已传输" for item in self.results)
        copy_failed = sum(item.transfer == "传输失败" for item in self.results)
        installed = sum(item.install == "安装成功" for item in self.results)
        install_failed = sum(item.install == "安装失败" for item in self.results)
        self.transfer_state.emit(f"已传输 {copied}/{total}" + (f" · 失败 {copy_failed}" if copy_failed else ""))
        if self.pending and self.pending.install_requested:
            self.install_state.emit("error" if install_failed else "ready", f"安装成功 {installed}/{copied}" + (f" · 失败 {install_failed}" if install_failed else ""))

    def _finish(self, devices=None):
        batch = self.pending
        if not batch:
            return
        self.policy.success(batch.device)
        copied = sum(item.transfer == "已传输" for item in batch.items)
        installed = sum(item.install == "安装成功" for item in batch.items)
        failed = [item for item in batch.items if item.transfer == "传输失败" or item.install == "安装失败"]
        summary = f"传输 {copied}/{len(batch.items)}"
        if batch.install_requested or installed:
            summary += f"，安装成功 {installed}/{copied}"
        if failed:
            summary += "；失败：" + "、".join(Path(item.path).name for item in failed)
        self.announce("warning" if failed else "success", "批次结束，部分项目失败" if failed else "批量传输与安装完成" if batch.install_requested else "批量传输完成", summary)
        self.record.emit(f"批次汇总：{summary}")
        self._emit_counts()
        for item in batch.items:
            item.close()
        if devices == []:
            self.reenumerating_completion = (batch.serials, time.monotonic() + 20)
        self.pending = None
        self._emit_results()
