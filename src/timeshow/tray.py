"""Resident tray process. It never imports the image engine or holds vault keys."""

import sys

from PySide6.QtCore import QLockFile, QProcess
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .desktop import config_directory
from .processes import command, spawn
from .scheduling import public_settings
from .storage import private_directory
from .ui_icon import app_icon


class Tray:
    def __init__(self, app: QApplication):
        self.app = app
        self.job: QProcess | None = None
        self.icon = QSystemTrayIcon(app_icon())
        self.menu = QMenu()
        self.actions = {}
        for key, label in [("next", "Next"), ("previous", "Previous"), ("toggle", "Start"),
                           ("web", "Open album in browser"), ("settings", "Settings"),
                           ("quit", "Quit tray")]:
            action = QAction(label, self.menu)
            action.triggered.connect(lambda checked=False, name=key: self.activate(name))
            self.menu.addAction(action)
            self.actions[key] = action
        self.menu.aboutToShow.connect(self.update_menu)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self.clicked)
        self.update_menu()

    def update_menu(self) -> None:
        try:
            running = public_settings().get("running", False)
            self.actions["toggle"].setText("Pause" if running else "Start")
            self.icon.setToolTip("Timeshow — " + ("scheduled" if running else "paused"))
        except Exception:
            self.icon.setToolTip("Timeshow — open Settings to check configuration")

    def clicked(self, reason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            spawn("gui")

    def activate(self, action: str) -> None:
        if action == "settings":
            spawn("gui")
            return
        if action == "quit":
            self.app.quit()
            return
        if self.job is not None:
            return
        if action == "toggle":
            action = "pause" if public_settings().get("running", False) else "resume"
        arguments = command("worker", "--action", action)
        self.job = QProcess()
        self.job.setProgram(arguments[0])
        self.job.setArguments(arguments[1:])
        self.job.finished.connect(self.finished)
        self.job.errorOccurred.connect(self.failed)
        self.job.start()

    def failed(self, error) -> None:
        if self.job is not None and self.job.state() == QProcess.ProcessState.NotRunning:
            self.icon.showMessage("Timeshow", "Could not launch the worker. Open Settings.")
            self.job.deleteLater()
            self.job = None

    def finished(self, code, status) -> None:
        if self.job is None:
            return
        if code:
            message = bytes(self.job.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            self.icon.showMessage("Timeshow", message or "The operation failed. Open Settings.")
        self.job.deleteLater()
        self.job = None
        self.update_menu()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Timeshow tray")
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 0
    directory = config_directory()
    private_directory(directory)
    lock = QLockFile(str(directory / "tray.lock"))
    if not lock.tryLock(100):
        return 0
    tray = Tray(app)
    tray.icon.show()
    return app.exec()
