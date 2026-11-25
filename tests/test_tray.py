"""Login triggers use fake processes and never change the desktop."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from timeshow.photos import PhotosError
from timeshow.tray import Tray, main


class TrayLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        icon = patch("timeshow.tray.QSystemTrayIcon")
        self.icon = icon.start()
        self.addCleanup(icon.stop)
        settings = patch("timeshow.tray.public_settings", return_value={})
        self.settings = settings.start()
        self.addCleanup(settings.stop)
        self.tray = Tray(self.app)

    def test_login_does_not_launch_worker_when_paused_or_unchecked(self):
        for preferences in ({}, {"running": True}, {"change_on_login": True}):
            with self.subTest(preferences=preferences), patch.object(self.tray, "activate") as activate:
                self.settings.return_value = preferences
                self.tray._login()
                activate.assert_not_called()

    def test_login_launches_one_worker(self):
        self.settings.return_value = {"running": True, "change_on_login": True}
        with patch("timeshow.tray.QProcess") as process, patch(
            "timeshow.tray.command", return_value=["synthetic-worker", "--action", "login"]
        ) as command:
            self.tray._login()
            self.tray._login()
            process.return_value.start.assert_called_once()
            command.assert_called_once_with("worker", "--action", "login")

    def test_bad_settings_report_error_without_launching_worker(self):
        self.settings.side_effect = PhotosError("The user settings file cannot be read.")
        with patch.object(self.tray, "activate") as activate:
            self.tray._login()
            activate.assert_not_called()
        self.tray.icon.showMessage.assert_called_once_with("Timeshow", "The user settings file cannot be read.")

    def test_only_login_launcher_schedules_the_startup_callback(self):
        for login, locked in [(False, True), (True, True), (True, False)]:
            arguments = ["timeshow", "--mode", "tray"] + (["--login"] if login else [])
            with self.subTest(login=login, locked=locked), patch(
                "timeshow.tray.sys.argv", arguments
            ), patch("timeshow.tray.QApplication") as app, patch(
                "timeshow.tray.private_directory"
            ), patch("timeshow.tray.QLockFile") as lock, patch(
                "timeshow.tray.Tray"
            ) as tray, patch("timeshow.tray.QTimer.singleShot") as timer:
                app.return_value.exec.return_value = 0
                lock.return_value.tryLock.return_value = locked
                self.icon.isSystemTrayAvailable.return_value = True
                self.assertEqual(main(), 0)
                if login and locked:
                    timer.assert_called_once_with(0, tray.return_value._login)
                else:
                    timer.assert_not_called()
