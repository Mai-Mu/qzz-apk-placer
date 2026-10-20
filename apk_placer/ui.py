from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QSystemTrayIcon,
    QTextEdit, QVBoxLayout, QWidget,
)

from .core import data_directory, load_path, save_path, validate_apk
from .worker import TransferWorker

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


class MainWindow(QMainWindow):
    def __init__(self, start_worker=True):
        super().__init__()
        self.setWindowTitle("APK 送达 · PDA 自动传输")
        self.setWindowIcon(app_icon())
        self.resize(790, 750)
        self.setMinimumSize(700, 720)
        self.apk_path = load_path()
        self.paused = False
        self.busy = False
        self.device_name = "尚未连接"
        self.quitting = False
        self.worker = TransferWorker(self.apk_path)
        self.build_ui()
        self.setup_tray()
        self.refresh_file()
        self.worker.status.connect(self.set_status)
        self.worker.device_changed.connect(self.set_device)
        self.worker.progress.connect(self.set_progress)
        self.worker.busy_changed.connect(self.set_busy)
        self.worker.record.connect(self.add_record)
        if start_worker:
            self.worker.start()

    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 28, 32, 22)
        layout.setSpacing(18)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(34, 34))
        top.addWidget(icon)
        top.addSpacing(4)
        top.addWidget(label("APK 送达", "brand"))
        top.addStretch()
        top.addWidget(label("USB  ·  自动传输", "badge"))
        layout.addLayout(top)

        intro = QVBoxLayout()
        intro.setSpacing(7)
        intro.addWidget(label("PDA FILE DELIVERY", "eyebrow"))
        intro.addWidget(label("选好 APK，连接即传。", "headline"))
        intro.addWidget(label("把安装包自动送到 PDA 的 Download 文件夹。", "muted"))
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
        self.status_detail = label("准备就绪后，连接 PDA 即可自动传输", "muted", True)
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
        file_layout.setContentsMargins(22, 17, 22, 18)
        file_layout.setSpacing(11)
        file_layout.addWidget(label("01  /  传输文件", "section"))
        file_row = QHBoxLayout()
        file_text = QVBoxLayout()
        file_text.setSpacing(6)
        self.filename = label("尚未选择 APK", "filename", True)
        self.file_info = label("选择一次，自动记住", "muted")
        file_text.addWidget(self.filename)
        file_text.addWidget(self.file_info)
        file_row.addLayout(file_text, 1)
        self.choose_button = QPushButton("选择 APK")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.clicked.connect(self.select_file)
        file_row.addWidget(self.choose_button)
        file_layout.addLayout(file_row)
        self.path_label = label("支持电脑上的 .apk 文件", "muted", True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_layout.addWidget(self.path_label)
        layout.addWidget(file_card)

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
        layout.addWidget(target_card)

        actions = QHBoxLayout()
        self.pause_button = QPushButton("暂停自动传输")
        self.pause_button.setToolTip("传输中的任务会完成；暂停后不再开始新任务")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)
        actions.addStretch()
        self.send_button = QPushButton("立即传输")
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
        if not self.apk_path:
            return
        source = Path(self.apk_path)
        self.filename.setText(source.name)
        self.path_label.setText(self.fontMetrics().elidedText(str(source), Qt.TextElideMode.ElideMiddle, 650))
        self.path_label.setToolTip(str(source))
        try:
            self.file_info.setText(f"{source.stat().st_size / (1024 * 1024):.1f} MB  ·  Android 安装包")
        except OSError:
            self.file_info.setText("文件路径已失效，请重新选择")
        self.choose_button.setText("更换 APK")

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择要自动传输的 APK", str(Path(self.apk_path).parent) if self.apk_path else "", "Android 安装包 (*.apk)")
        if not path:
            return
        error = validate_apk(path)
        if error:
            QMessageBox.warning(self, "无法选择文件", error)
            return
        try:
            save_path(path)
        except OSError:
            QMessageBox.warning(self, "无法保存设置", "无法保存 APK 路径，请检查当前用户的数据目录权限")
            return
        self.apk_path = path
        self.refresh_file()
        self.worker.command("select", path)
        self.add_record(f"已选择 APK：{Path(path).name}")

    def toggle_pause(self):
        self.paused = not self.paused
        text = "恢复自动传输" if self.paused else "暂停自动传输"
        self.pause_button.setText(text)
        self.tray_pause.setText(text)
        self.worker.command("pause", self.paused)
        self.update_actions()

    def set_status(self, state, title, detail):
        self.status_title.setText(title)
        self.status_detail.setText(detail)
        palettes = {
            "success": ("#EAF7F0", "#CFECDD", "#1C9766"),
            "error": ("#FFF0EE", "#F8DDD8", "#D16A50"),
            "invalid": ("#FFF6E7", "#F4E5C7", "#B98628"),
            "paused": ("#EEF0F5", "#DFE4ED", "#8591A4"),
        }
        background, border, accent = palettes.get(state, ("#EAF1FF", "#DDE8FF", "#3473EF"))
        self.status_card.setStyleSheet(f"QFrame#status {{background:{background};border:1px solid {border};border-radius:16px;}}")
        self.status_dot.setStyleSheet(f"color:{accent};font-size:20px;")
        self.tray.setToolTip(f"APK 送达 · {title}")
        if state != "copying":
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100 if state == "success" else 0)
            self.percent.setText("完成" if state == "success" else "")
        else:
            self.progress_bar.setRange(0, 0)
            self.percent.setText("")
        if state == "success" and not self.isVisible():
            self.tray.showMessage("APK 已送达", "安装包已保存到 PDA 的 Download 文件夹", QSystemTrayIcon.MessageIcon.Information, 3500)
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
        self.choose_button.setEnabled(not self.busy and not self.quitting)
        self.send_button.setEnabled(not self.busy and not self.paused and not self.quitting
                                    and self.device_name != "尚未连接" and validate_apk(self.apk_path) is None
                                    and not self.worker.policy.path_lost)
        self.send_button.setText("正在传输…" if self.busy else "立即传输")

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
    app.setOrganizationName("Qzz")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    socket = QLocalSocket()
    socket.connectToServer("QzzApkPlacer.v1")
    if socket.waitForConnected(600):
        socket.write(b"show")
        socket.waitForBytesWritten(600)
        return 0
    server = QLocalServer()
    if not server.listen("QzzApkPlacer.v1"):
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
