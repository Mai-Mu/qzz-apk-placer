from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QSystemTrayIcon,
    QTextEdit, QVBoxLayout, QWidget, QAbstractButton, QScrollArea, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from .core import data_directory, load_paths, save_paths, list_errors, unique_paths, path_identity, load_adb_path, save_setting
from .adb import find_adb, PLATFORM_TOOLS_URL
from .worker import TransferWorker
from . import __version__

STYLE = """
QMainWindow, QWidget#root { background: #F5F7FB; }
QWidget { color: #17243B; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 21px; font-weight: 700; }
QLabel#eyebrow { color: #3473EF; font-size: 11px; font-weight: 700; }
QLabel#headline { font-size: 27px; font-weight: 700; }
QLabel#muted { color: #758198; }
QLabel#section { color: #8490A3; font-size: 11px; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #E7EBF2; border-radius: 16px; }
QFrame#status { background: #EAF1FF; border: 1px solid #DDE8FF; border-radius: 16px; }
QLabel#statusTitle { font-size: 19px; font-weight: 700; }
QLabel#filename { font-size: 16px; font-weight: 600; }
QLabel#badge { color: #3473EF; background: #EAF1FF; border-radius: 11px; padding: 5px 10px; font-size: 11px; }
QPushButton { background: white; border: 1px solid #DFE5EF; border-radius: 9px; padding: 10px 18px; font-weight: 600; }
QPushButton:hover { background: #F3F6FC; border-color: #BCCBE2; }
QPushButton:pressed { background: #E9EFF9; }
QPushButton:disabled { color: #ADB6C5; background: #F1F3F7; border-color: #E6EAF0; }
QPushButton#primary { background: #3473EF; color: white; border: 1px solid #3473EF; }
QPushButton#primary:hover { background: #2463DE; }
QPushButton#primary:disabled { background: #ADC4F0; border-color: #ADC4F0; }
QPushButton#link { background: transparent; color: #758198; border: none; padding: 5px 0; font-weight: 400; text-align: left; }
QProgressBar { background: #D5E2FA; border: none; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #3473EF; border-radius: 3px; }
QTextEdit { background: white; border: 1px solid #E7EBF2; border-radius: 10px; padding: 8px; color: #66758D; font-size: 11px; }
QMenu { background: white; border: 1px solid #E4E9F1; padding: 6px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #EAF1FF; border-radius: 5px; }
QTableWidget { background: #FFFFFF; border: 1px solid #E7EBF2; border-radius: 8px; gridline-color: #EEF1F6; selection-background-color: #EAF1FF; selection-color: #17243B; }
QHeaderView::section { background: #F7F9FC; color: #758198; border: none; padding: 8px; font-size: 11px; }
QTableWidget::item { padding: 7px; border-bottom: 1px solid #F0F3F8; }
QPushButton#compact { padding: 6px 12px; font-size: 12px; }
"""


def app_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#3473EF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 120, 120, 28, 28)
    painter.setPen(QPen(QColor("white"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawLine(64, 30, 64, 76)
    painter.drawLine(47, 61, 64, 78)
    painter.drawLine(81, 61, 64, 78)
    painter.drawLine(34, 83, 34, 96)
    painter.drawLine(34, 96, 94, 96)
    painter.drawLine(94, 96, 94, 83)
    painter.end()
    return QIcon(pixmap)


def label(text: str, name: str = "", wrap=False) -> QLabel:
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3473EF" if self.isChecked() else "#C4CDD9"))
        painter.drawRoundedRect(1, 1, 44, 24, 12, 12)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(24 if self.isChecked() else 4, 4, 18, 18)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#8AABF3"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(0, 0, 45, 25, 12, 12)


class MainWindow(QMainWindow):
    def __init__(self, start_worker=True):
        super().__init__()
        self.setWindowTitle(f"APK 送达 v{__version__} · 多 APK 批量处理")
        self.setWindowIcon(app_icon())
        available_height = QApplication.primaryScreen().availableGeometry().height()
        self.resize(940, min(920, available_height - 50))
        self.setMinimumSize(790, 620)
        self.applied_paths = load_paths()
        self.draft_paths = self.applied_paths[:]
        self.item_results = {}
        self.paused = False
        self.busy = False
        self.device_name = "尚未连接"
        self.quitting = False
        self.worker = TransferWorker(self.applied_paths)
        self.build_ui()
        self.setup_tray()
        self.refresh_file()
        self.worker.status.connect(self.set_status)
        self.worker.device_changed.connect(self.set_device)
        self.worker.progress.connect(self.set_progress)
        self.worker.busy_changed.connect(self.set_busy)
        self.worker.record.connect(self.add_record)
        self.worker.transfer_state.connect(self.transfer_result.setText)
        self.worker.install_state.connect(self.set_install_state)
        self.worker.results_changed.connect(self.set_results)
        if start_worker:
            self.worker.start()

    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(14)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(34, 34))
        top.addWidget(icon)
        top.addSpacing(4)
        top.addWidget(label("APK 送达", "brand"))
        top.addStretch()
        top.addWidget(label("USB  ·  多 APK 批量处理", "badge"))
        layout.addLayout(top)

        intro = QVBoxLayout()
        intro.setSpacing(7)
        intro.addWidget(label("PDA FILE DELIVERY", "eyebrow"))
        intro.addWidget(label("配好一份列表，整批送达。", "headline"))
        intro.addWidget(label("先传完全部 APK，再按列表顺序安装。适用于 Android Pad / PDA。", "muted"))
        layout.addLayout(intro)

        self.status_card = QFrame()
        self.status_card.setObjectName("status")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(22, 19, 22, 18)
        status_layout.setSpacing(9)
        row = QHBoxLayout()
        self.status_dot = label("●")
        self.status_dot.setStyleSheet("color: #3473EF; font-size: 20px;")
        row.addWidget(self.status_dot)
        self.status_title = label("正在启动设备检测", "statusTitle")
        row.addWidget(self.status_title, 1)
        self.percent = label("", "muted")
        row.addWidget(self.percent)
        status_layout.addLayout(row)
        self.status_detail = label("应用 APK 列表后，连接设备即可批量处理", "muted", True)
        status_layout.addWidget(self.status_detail)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        status_layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_card)

        file_card = QFrame()
        file_card.setObjectName("card")
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(18, 13, 18, 14)
        file_layout.setSpacing(8)
        file_row = QHBoxLayout()
        self.file_count = label("01  /  APK 列表 · 0 项", "section")
        file_row.addWidget(self.file_count)
        file_row.addStretch()
        self.choose_button = QPushButton("＋ 添加 APK")
        self.choose_button.setObjectName("compact")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.clicked.connect(self.select_file)
        file_row.addWidget(self.choose_button)
        file_layout.addLayout(file_row)
        self.apk_table = QTableWidget(0, 4)
        self.apk_table.setHorizontalHeaderLabels(["APK 文件", "本地路径", "传输", "安装"])
        self.apk_table.verticalHeader().hide()
        self.apk_table.setShowGrid(False)
        self.apk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.apk_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.apk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.apk_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        header = self.apk_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.apk_table.setColumnWidth(0, 175)
        self.apk_table.setColumnWidth(2, 115)
        self.apk_table.setColumnWidth(3, 125)
        self.apk_table.setFixedHeight(150)
        self.apk_table.verticalHeader().setDefaultSectionSize(36)
        self.apk_table.itemSelectionChanged.connect(self.update_actions)
        file_layout.addWidget(self.apk_table)
        edit_row = QHBoxLayout()
        self.edit_buttons = []
        for text, callback in (("替换", self.replace_file), ("移除", self.remove_file),
                               ("上移", lambda: self.move_file(-1)), ("下移", lambda: self.move_file(1))):
            button = QPushButton(text)
            button.setObjectName("compact")
            button.clicked.connect(callback)
            self.edit_buttons.append(button)
            edit_row.addWidget(button)
        edit_row.addStretch()
        self.apply_button = QPushButton("应用列表")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply_list)
        edit_row.addWidget(self.apply_button)
        file_layout.addLayout(edit_row)
        self.list_hint = label("添加 APK 后点击「应用列表」，支持不同目录。", "muted", True)
        file_layout.addWidget(self.list_hint)
        layout.addWidget(file_card)

        details_row = QHBoxLayout()
        details_row.setSpacing(14)
        target_card = QFrame()
        target_card.setObjectName("card")
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(22, 17, 22, 18)
        target_layout.setSpacing(12)
        target_layout.addWidget(label("02  /  目标设备", "section"))
        device_row = QHBoxLayout()
        device_row.addWidget(label("连接设备", "muted"))
        self.device_label = label("尚未连接")
        device_row.addStretch()
        device_row.addWidget(self.device_label)
        target_layout.addLayout(device_row)
        destination = QHBoxLayout()
        destination.addWidget(label("保存位置", "muted"))
        destination.addStretch()
        destination.addWidget(label("内部存储  /  Download"))
        target_layout.addLayout(destination)
        result_row = QHBoxLayout()
        result_row.addWidget(label("传输结果", "muted"))
        result_row.addStretch()
        self.transfer_result = label("等待传输")
        result_row.addWidget(self.transfer_result)
        target_layout.addLayout(result_row)
        details_row.addWidget(target_card, 1)

        install_card = QFrame()
        install_card.setObjectName("card")
        install_layout = QVBoxLayout(install_card)
        install_layout.setContentsMargins(22, 16, 22, 16)
        install_layout.setSpacing(9)
        switch_row = QHBoxLayout()
        switch_row.addWidget(label("03  /  自动安装", "section"))
        switch_row.addStretch()
        self.auto_switch = ToggleSwitch()
        self.auto_switch.setAccessibleName("自动安装")
        self.auto_switch.setToolTip("每次启动默认关闭；从下一次传输任务生效，进行中的安装会先完成")
        self.auto_switch.toggled.connect(self.toggle_install)
        switch_row.addWidget(self.auto_switch)
        install_layout.addLayout(switch_row)
        self.install_result = label("已关闭 · 仅传输 APK", "muted", True)
        install_layout.addWidget(self.install_result)
        help_row = QHBoxLayout()
        help_row.addWidget(label("保留应用数据覆盖更新，需 USB 调试授权", "muted", True), 1)
        self.adb_button = QPushButton("配置 ADB")
        self.adb_button.setObjectName("link")
        self.adb_button.clicked.connect(self.configure_adb)
        help_row.addWidget(self.adb_button)
        install_layout.addLayout(help_row)
        details_row.addWidget(install_card, 1)
        layout.addLayout(details_row)

        actions = QHBoxLayout()
        self.pause_button = QPushButton("暂停任务")
        self.pause_button.setToolTip("当前文件处理完成后暂停，恢复时继续剩余项")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)
        actions.addStretch()
        self.send_button = QPushButton("立即处理整批")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(lambda: self.worker.command("manual"))
        self.send_button.setEnabled(False)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)

        footer = QHBoxLayout()
        footer.addWidget(label("同名覆盖  ·  关闭窗口后在托盘继续运行", "muted"))
        footer.addStretch()
        self.log_button = QPushButton("传输记录  ↗")
        self.log_button.setObjectName("link")
        self.log_button.clicked.connect(self.toggle_log)
        footer.addWidget(self.log_button)
        layout.addLayout(footer)
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.document().setMaximumBlockCount(150)
        self.history.setFixedHeight(130)
        self.history.hide()
        layout.addWidget(self.history)
        layout.addStretch(1)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("APK 送达 · PDA 自动传输")
        menu = QMenu(self)
        show_action = QAction("打开主窗口", self)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)
        self.tray_pause = QAction("暂停自动传输", self)
        self.tray_pause.triggered.connect(self.toggle_pause)
        menu.addAction(self.tray_pause)
        menu.addSeparator()
        exit_action = QAction("退出程序", self)
        exit_action.triggered.connect(self.quit_app)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh_file(self):
        selected = self.apk_table.currentRow()
        scroll = self.apk_table.verticalScrollBar().value()
        errors = list_errors(self.draft_paths)
        self.apk_table.blockSignals(True)
        self.apk_table.setRowCount(len(self.draft_paths))
        for row, path in enumerate(self.draft_paths):
            result = self.item_results.get(path_identity(path), {})
            error = errors.get(path, "")
            texts = [Path(path).name, path, "路径失效" if error else result.get("transfer", "等待传输"), result.get("install", "等待任务")]
            tooltip = error or result.get("detail", "")
            for column, text in enumerate(texts):
                cell = QTableWidgetItem(text)
                cell.setToolTip((path + "\n" + tooltip).strip() if column < 2 else tooltip or text)
                if error or "失败" in text:
                    cell.setForeground(QColor("#C3634D"))
                elif text in ("已传输", "安装成功"):
                    cell.setForeground(QColor("#1C9766"))
                self.apk_table.setItem(row, column, cell)
        if 0 <= selected < len(self.draft_paths):
            self.apk_table.selectRow(selected)
        self.apk_table.verticalScrollBar().setValue(scroll)
        self.apk_table.blockSignals(False)
        self.file_count.setText(f"01  /  APK 列表 · {len(self.draft_paths)} 项")
        dirty = self.draft_paths != self.applied_paths
        if self.draft_paths and errors:
            self.list_hint.setText(f"列表有 {len(errors)} 个问题，请替换或移除标红项后重新应用。")
        elif dirty:
            self.list_hint.setText(f"草稿未生效 · 当前已应用 {len(self.applied_paths)} 项，请点击「应用列表」。")
        elif not self.draft_paths:
            self.list_hint.setText("列表为空 · 添加 APK 后应用；应用空列表会暂停自动处理。")
        else:
            self.list_hint.setText(f"已应用 {len(self.applied_paths)} 项 · 按列表顺序处理，可随时编辑后重新应用。")
        self.update_actions()

    def select_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加 APK（可多选）", str(Path(self.draft_paths[-1]).parent) if self.draft_paths else "", "Android 安装包 (*.apk)")
        if paths:
            self.set_draft(self.draft_paths + paths)

    def set_draft(self, paths):
        paths = unique_paths(paths)
        names = [Path(path).name.casefold() for path in paths]
        if len(names) != len(set(names)):
            QMessageBox.warning(self, "文件名冲突", "不同目录的 APK 文件名相同，请先重命名其中一个再添加，避免在 Download 中互相覆盖。")
            return False
        self.draft_paths = paths
        self.refresh_file()
        return True

    def replace_file(self):
        row = self.apk_table.currentRow()
        if row < 0:
            return
        path, _ = QFileDialog.getOpenFileName(self, "替换所选 APK", str(Path(self.draft_paths[row]).parent), "Android 安装包 (*.apk)")
        if path:
            paths = self.draft_paths[:]
            paths[row] = path
            self.set_draft(paths)

    def remove_file(self):
        row = self.apk_table.currentRow()
        if row >= 0:
            self.set_draft(self.draft_paths[:row] + self.draft_paths[row + 1:])

    def move_file(self, delta):
        row = self.apk_table.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < len(self.draft_paths):
            self.draft_paths[row], self.draft_paths[target] = self.draft_paths[target], self.draft_paths[row]
            self.refresh_file()
            self.apk_table.selectRow(target)

    def apply_list(self):
        errors = list_errors(self.draft_paths) if self.draft_paths else {}
        if errors:
            QMessageBox.warning(self, "列表无效", next(iter(errors.values())))
            return
        try:
            save_paths(self.draft_paths)
        except OSError:
            QMessageBox.warning(self, "无法保存列表", "请检查当前用户的数据目录权限")
            return
        self.applied_paths = self.draft_paths[:]
        self.worker.command("apply", self.applied_paths[:])
        self.item_results = {}
        self.refresh_file()
        self.add_record(f"已应用列表：{len(self.applied_paths)} 个 APK")

    def set_results(self, results):
        self.item_results = {path_identity(item["path"]): item for item in results}
        self.refresh_file()

    def toggle_pause(self):
        self.paused = not self.paused
        text = "恢复任务" if self.paused else "暂停任务"
        self.pause_button.setText(text)
        self.tray_pause.setText(text)
        self.worker.command("pause", self.paused)
        self.update_actions()

    def toggle_install(self, enabled):
        self.worker.command("auto_install", enabled)
        self.set_install_state("ready" if enabled else "off",
                               "已开启 · 从下一次传输任务生效" if enabled else "已关闭 · 仅传输 APK")
        self.add_record("自动安装已开启，从下一次传输任务生效" if enabled else "自动安装已关闭")

    def set_install_state(self, state, detail):
        self.install_result.setText(detail[:220])
        self.install_result.setToolTip(detail)
        color = {"success": "#1C9766", "error": "#C3634D", "waiting": "#AE812B",
                 "installing": "#3473EF", "ready": "#3473EF"}.get(state, "#758198")
        self.install_result.setStyleSheet(f"color: {color};")

    def configure_adb(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("配置 Android ADB 工具")
        dialog.setMinimumWidth(510)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("选择官方 Platform-Tools 中的 adb.exe", "filename"))
        layout.addWidget(label("下载并完整解压工具包，保留 adb.exe 旁边的 DLL。\nPDA 需开启 USB 调试，并允许这台电脑连接。", "muted", True))
        current = find_adb(load_adb_path())
        current_label = label(current or "暂未找到 ADB，请下载后选择", "muted", True)
        current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(current_label)
        download = QPushButton("打开官方下载页面")
        download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PLATFORM_TOOLS_URL)))
        layout.addWidget(download)
        choose = QPushButton("选择 adb.exe")
        choose.setObjectName("primary")

        def select_adb():
            path, _ = QFileDialog.getOpenFileName(dialog, "选择 adb.exe", str(Path(current).parent) if current else "", "Android 调试工具 (adb.exe)")
            if not path:
                return
            if Path(path).name.casefold() != "adb.exe" or not Path(path).is_file():
                QMessageBox.warning(dialog, "工具无效", "请选择官方 Platform-Tools 文件夹里的 adb.exe")
                return
            try:
                save_setting("adb_path", path)
            except OSError:
                QMessageBox.warning(dialog, "无法保存", "请检查当前用户的数据目录权限")
                return
            self.worker.command("adb_path", path)
            self.add_record("已配置 ADB，正在等待的安装任务会继续检查连接")
            dialog.accept()

        choose.clicked.connect(select_adb)
        layout.addWidget(choose)
        dialog.exec()

    def set_status(self, state, title, detail):
        self.status_title.setText(title)
        self.status_detail.setText(detail)
        palettes = {
            "success": ("#EAF7F0", "#CFECDD", "#1C9766"),
            "error": ("#FFF0EE", "#F8DDD8", "#D16A50"),
            "invalid": ("#FFF6E7", "#F4E5C7", "#B98628"),
            "paused": ("#EEF0F5", "#DFE4ED", "#8591A4"),
            "warning": ("#FFF6E7", "#F4E5C7", "#B98628"),
        }
        background, border, accent = palettes.get(state, ("#EAF1FF", "#DDE8FF", "#3473EF"))
        self.status_card.setStyleSheet(f"QFrame#status {{background:{background};border:1px solid {border};border-radius:16px;}}")
        self.status_dot.setStyleSheet(f"color:{accent};font-size:20px;")
        self.tray.setToolTip(f"APK 送达 · {title}")
        if state not in ("copying", "installing"):
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100 if state in ("success", "warning", "waiting_install") else 0)
            self.percent.setText("完成" if state == "success" else "已结束" if state == "warning" else "已传输" if state == "waiting_install" else "")
        else:
            self.progress_bar.setRange(0, 0)
            self.percent.setText("")
        if state == "success" and not self.isVisible():
            self.tray.showMessage(title, detail, QSystemTrayIcon.MessageIcon.Information, 3500)
        self.refresh_file()
        self.update_actions()

    def set_device(self, name):
        self.device_name = name
        self.device_label.setText(name)
        self.update_actions()

    def set_busy(self, value):
        self.busy = value
        self.update_actions()

    def update_actions(self):
        if not hasattr(self, "send_button"):
            return
        self.choose_button.setEnabled(not self.busy and not self.quitting)
        selected = self.apk_table.currentRow()
        for button in self.edit_buttons:
            button.setEnabled(selected >= 0 and not self.busy and not self.quitting)
        valid_draft = not self.draft_paths or not list_errors(self.draft_paths)
        self.apply_button.setEnabled(valid_draft and not self.busy and not self.quitting)
        self.auto_switch.setEnabled(not self.quitting)
        self.adb_button.setEnabled(not self.busy and not self.quitting)
        self.send_button.setEnabled(not self.busy and not self.paused and not self.quitting
                                    and self.device_name != "尚未连接" and self.draft_paths == self.applied_paths
                                    and not list_errors(self.applied_paths)
                                    and not self.worker.policy.path_lost)
        self.send_button.setText("正在处理…" if self.busy else "立即处理整批")

    def set_progress(self, sent, total):
        self.progress_bar.setRange(0, 100)
        percent = int(sent * 100 / total) if total else 0
        self.progress_bar.setValue(percent)
        self.percent.setText("正在校验" if percent == 100 else f"{percent}%")

    def add_record(self, text):
        from datetime import datetime, timedelta, timezone
        # Insert plain text: device/file names must never be interpreted as HTML.
        self.history.moveCursor(self.history.textCursor().MoveOperation.End)
        self.history.insertPlainText(f"{datetime.now(timezone(timedelta(hours=8))):%H:%M:%S}  {text}\n")

    def toggle_log(self):
        visible = not self.history.isVisible()
        self.history.setVisible(visible)
        self.log_button.setText("收起记录  ↗" if visible else "传输记录  ↗")
        self.resize(self.width(), self.height() + (140 if visible else -140))

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.ignore()
            self.quit_app()

    def quit_app(self):
        if self.quitting:
            return
        self.quitting = True
        self.worker.stop()
        self.update_actions()
        self.set_status("paused", "正在退出", "正在等待设备操作安全结束，请稍候")
        self.exit_timer = QTimer(self)
        self.exit_timer.timeout.connect(self.finish_quit)
        self.exit_timer.start(100)
        self.finish_quit()

    def finish_quit(self):
        if not self.worker.isRunning():
            self.tray.hide()
            QApplication.instance().quit()


def main():
    if os.name != "nt":
        raise SystemExit("本程序仅支持 Windows")
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "app.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("APK 送达")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Qzz")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    # Allow isolated packaging tests without interacting with a user's running app.
    session_name = os.environ.get("QZZ_APK_PLACER_SESSION", "QzzApkPlacer.v1")
    socket = QLocalSocket()
    socket.connectToServer(session_name)
    if socket.waitForConnected(600):
        socket.write(b"show")
        socket.waitForBytesWritten(600)
        return 0
    server = QLocalServer()
    if not server.listen(session_name):
        QMessageBox.warning(None, "无法启动", "无法创建程序服务，请确认程序是否已在托盘运行")
        return 1
    window = MainWindow()

    def activate_existing():
        connection = server.nextPendingConnection()
        if connection:
            connection.close()
            connection.deleteLater()
        window.show_window()

    server.newConnection.connect(activate_existing)
    window.show()
    return app.exec()
