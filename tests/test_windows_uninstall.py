"""Windows cleanup keeps encrypted files and pauses only the public settings."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QLockFile
    from timeshow import _windows_uninstall
except ModuleNotFoundError:
    raise unittest.SkipTest("Install the gui extra for Windows cleanup checks")

from timeshow.photos import PhotosError
from timeshow.processes import operation_lock
from timeshow.scheduling import Scheduler
from timeshow.settings import publish_settings


class WindowsUninstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "config"
        publish_settings({"running": True, "interval": 120}, self.directory)
        (self.directory / "state.enc").write_bytes(b"synthetic encrypted data")
        (self.directory / "key.json").write_bytes(b"synthetic wrapped key")

    def cleanup(self, remove_task):
        with patch.object(_windows_uninstall, "sys") as system, patch.object(
            _windows_uninstall, "config_directory", return_value=self.directory
        ), patch.object(Scheduler, "_remove_windows_task", remove_task), patch.object(
            _windows_uninstall, "report"
        ):
            system.platform = "win32"
            return _windows_uninstall.main()

    def test_cleanup_is_idempotent_and_does_not_unlock_or_delete_private_files(self):
        with patch.object(Scheduler, "_remove_windows_task") as remove_task:
            self.assertEqual(self.cleanup(remove_task), 0)
            self.assertEqual(self.cleanup(remove_task), 0)
            self.assertEqual(remove_task.call_count, 2)
        self.assertEqual(json.loads((self.directory / "settings.json").read_text()),
                         {"running": False, "interval": 120})
        self.assertEqual((self.directory / "state.enc").read_bytes(), b"synthetic encrypted data")
        self.assertEqual((self.directory / "key.json").read_bytes(), b"synthetic wrapped key")

    def test_scheduler_failure_keeps_settings_for_retry(self):
        with patch.object(Scheduler, "_remove_windows_task", side_effect=PhotosError("synthetic failure")) as remove_task:
            self.assertEqual(self.cleanup(remove_task), 1)
        self.assertTrue(json.loads((self.directory / "settings.json").read_text())["running"])

    def test_running_gui_or_worker_blocks_cleanup(self):
        lock = QLockFile(str(self.directory / "gui.lock"))
        self.assertTrue(lock.tryLock(100))
        try:
            with patch.object(Scheduler, "_remove_windows_task") as remove_task:
                self.assertEqual(self.cleanup(remove_task), 1)
                remove_task.assert_not_called()
        finally:
            lock.unlock()
        with operation_lock(self.directory), patch.object(Scheduler, "_remove_windows_task") as remove_task:
            self.assertEqual(self.cleanup(remove_task), 1)
            remove_task.assert_not_called()

    def test_task_removal_disables_then_deletes_only_timeshow(self):
        tasks = '"\\Unrelated","synthetic","Ready"\n"\\Timeshow","synthetic","Ready"\n'
        with patch("timeshow.scheduling.subprocess.run", return_value=subprocess.CompletedProcess([], 0, tasks)), patch.object(
            Scheduler, "_run"
        ) as run, patch("timeshow.scheduling.sys") as system:
            system.platform = "win32"
            Scheduler(self.directory)._remove_windows_task()
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["schtasks.exe", "/Change", "/TN", "Timeshow", "/DISABLE"],
            ["schtasks.exe", "/Delete", "/TN", "Timeshow", "/F"],
        ])

    def test_task_listing_failure_is_not_treated_as_missing_task(self):
        with patch("timeshow.scheduling.subprocess.run", side_effect=subprocess.CalledProcessError(1, "schtasks")):
            with self.assertRaises(PhotosError):
                Scheduler(self.directory)._remove_windows_task()
