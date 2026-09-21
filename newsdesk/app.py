from __future__ import annotations

import hashlib
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QAction, QCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from .config import Config, data_dir
from .controller import Controller
from .storage import Store
from .ui import Panel, Settings, make_icon


class Application:
    def __init__(self, app: QApplication, config: Config, offline: bool = False):
        self.app = app
        self.store = Store(data_dir() / "cache.sqlite3")
        self.controller = Controller(config, self.store)
        self.panel = Panel(self.controller)
        self.panel.settings_requested.connect(self.settings)
        self.tray = QSystemTrayIcon(make_icon(), app)
        self.tray.setToolTip("知更 NewsDesk · 悬停阅读，右键设置")
        self.menu = QMenu()
        for title, handler in [("打开信息窗", lambda: self.show_panel(False)), ("全部更新", self.controller.refresh),
                               ("设置", self.settings), ("重新加载配置", self.reload)]:
            action = QAction(title, self.menu)
            action.triggered.connect(lambda checked=False, fn=handler: fn())
            self.menu.addAction(action)
        self.menu.addSeparator()
        quit_action = QAction("退出知更", self.menu)
        quit_action.triggered.connect(self.quit)
        self.menu.addAction(quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activated)
        self.tray.messageClicked.connect(lambda: self.show_panel(False))
        self.controller.notice.connect(self.notify)
        self.hover_start = 0.0
        self.outside_start = 0.0
        self.hover_latched = False
        self.dialog_open = False
        self.poll = QTimer(app)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self.poll_hover)
        self.tray.show()
        self.poll.start()
        if not offline:
            QTimer.singleShot(100, self.controller.start)

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel(False)

    def show_panel(self, hover=True):
        if self.dialog_open:
            return
        self.panel.hover_mode = hover
        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        work = screen.availableGeometry()
        width, height = min(1180, work.width() - 24), min(800, work.height() - 24)
        self.panel.resize(width, height)
        anchor = self.tray.geometry()
        if anchor.isEmpty():
            x, y = work.right() - width - 12, work.bottom() - height - 12
        else:
            x = max(work.left() + 12, min(anchor.center().x() - width // 2, work.right() - width - 12))
            y = anchor.top() - height - 10
            if y < work.top() + 12:
                y = min(anchor.bottom() + 10, work.bottom() - height - 12)
            y = max(work.top() + 12, y)
        self.panel.move(x, y)
        self.panel.show()
        self.panel.raise_()
        if not hover:
            self.panel.activateWindow()

    def poll_hover(self):
        # QSystemTrayIcon ToolTip events exist only on X11. Geometry polling is native on Windows
        # and also handles icons in the expanded overflow tray, using Qt's DPI-aware coordinates.
        pos = QCursor.pos()
        rect = self.tray.geometry()
        over_icon = not rect.isEmpty() and rect.contains(pos)
        now = time.monotonic()
        if self.menu.isVisible() or self.dialog_open:
            return
        if over_icon:
            self.outside_start = 0
            if not self.hover_start:
                self.hover_start = now
            if not self.hover_latched and now - self.hover_start >= self.controller.config.hover_delay_ms / 1000:
                self.hover_latched = True
                if not self.panel.isVisible():
                    self.show_panel(True)
        else:
            self.hover_start = 0
            self.hover_latched = False
        inside = self.panel.isVisible() and self.panel.frameGeometry().adjusted(-10, -10, 10, 10).contains(pos)
        if over_icon or inside or self.panel.pinned or not self.panel.hover_mode:
            self.outside_start = 0
        elif self.panel.isVisible():
            if not self.outside_start:
                self.outside_start = now
            elif now - self.outside_start > 0.7:
                self.panel.hide()

    def notify(self, title, body):
        if QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 7000)

    def settings(self):
        self.dialog_open = True
        dialog = Settings(self.controller.config, self.panel)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.controller.config = dialog.result_config
                self.controller.next_due.clear()
                self.controller.ai_status = "OpenClaw 已授权 · 点击生成摘要" if self.controller.config.ai_enabled else "AI 摘要未启用"
                self.controller.refresh()
        finally:
            self.dialog_open = False
        self.panel.render()

    def reload(self):
        try:
            self.controller.config = Config.load()
            self.controller.next_due.clear()
            self.controller.ai_status = "OpenClaw 已授权 · 点击生成摘要" if self.controller.config.ai_enabled else "AI 摘要未启用"
            self.controller.refresh()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self.panel, "配置未加载", str(exc))

    def quit(self):
        self.poll.stop()
        self.controller.shutdown()
        self.tray.hide()
        self.panel.hide()
        self.app.quit()


def run(show=False, smoke_seconds=0, screenshot: Path | None = None, offline=False, settings=False) -> int:
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("NewsDesk")
    app.setOrganizationName("NewsDesk")
    app.setWindowIcon(make_icon())
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "app.lock"))
    lock.setStaleLockTime(0)
    name = "NewsDesk-" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:16]
    if not lock.tryLock(100):
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(1000):
            socket.write(b"show")
            socket.waitForBytesWritten(1000)
        return 0
    try:
        config = Config.load()
    except (ValueError, OSError, TypeError) as exc:
        QMessageBox.critical(None, "知更配置错误", f"配置文件未被覆盖，请修正 {directory / 'config.json'}\n\n{exc}")
        return 1
    if not QSystemTrayIcon.isSystemTrayAvailable() and not smoke_seconds:
        QMessageBox.critical(None, "系统托盘不可用", "请在已登录的 Windows 桌面会话中运行知更。")
        return 1
    instance = Application(app, config, offline)
    server = QLocalServer(app)
    QLocalServer.removeServer(name)
    server.listen(name)
    def incoming():
        client = server.nextPendingConnection()
        instance.show_panel(False)
        if client:
            client.disconnectFromServer()
            client.deleteLater()
    server.newConnection.connect(incoming)
    if show or smoke_seconds:
        QTimer.singleShot(300, lambda: instance.show_panel(False))
    if settings:
        QTimer.singleShot(500, instance.settings)
    if smoke_seconds:
        def finish():
            if screenshot:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                target = app.activeModalWidget() or instance.panel
                if not target.grab().save(str(screenshot)):
                    logging.error("Screenshot could not be written")
            instance.quit()
        QTimer.singleShot(int(smoke_seconds * 1000), finish)
    code = app.exec()
    # Workers never access SQLite. Retain their QObjects until bounded requests finish.
    instance.controller.pool.waitForDone()
    instance.store.close()
    server.close()
    lock.unlock()
    return code
