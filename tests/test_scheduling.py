"""Scheduler commands are recorded, never registered on the test machine."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeshow.desktop import app_directory, config_directory
from timeshow.photos import PhotosError
from timeshow.processes import operation_lock
from timeshow.scheduling import Scheduler, public_settings, publish_settings


class RecordingScheduler(Scheduler):
    def __init__(self, directory):
        super().__init__(directory)
        self.calls = []

    def _run(self, arguments):
        self.calls.append(arguments)


class SchedulingTests(unittest.TestCase):
    def test_linux_paths_follow_xdg_separation(self):
        with patch("sys.platform", "linux"), patch.dict(os.environ, {
            "XDG_CONFIG_HOME": "/tmp/synthetic-config", "XDG_DATA_HOME": "/tmp/synthetic-data",
        }):
            self.assertEqual(config_directory(), Path("/tmp/synthetic-config/timeshow"))
            self.assertEqual(app_directory(), Path("/tmp/synthetic-data/timeshow"))

    def test_windows_config_uses_roaming_and_cache_uses_local(self):
        with patch("sys.platform", "win32"), patch.dict(os.environ, {
            "APPDATA": "/tmp/synthetic-roaming", "LOCALAPPDATA": "/tmp/synthetic-local",
        }):
            self.assertEqual(config_directory(), Path("/tmp/synthetic-roaming/Timeshow"))
            self.assertEqual(app_directory(), Path("/tmp/synthetic-local/Timeshow"))

    def test_linux_timer_is_user_scoped_and_runs_one_worker(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "linux"):
            root = Path(temporary)
            scheduler = RecordingScheduler(root / "timeshow")
            scheduler.enable(300)
            timer = (root / "systemd/user/timeshow.timer").read_text()
            service = (root / "systemd/user/timeshow.service").read_text()
            self.assertIn("OnUnitActiveSec=300s", timer)
            self.assertIn("Type=oneshot", service)
            self.assertIn('"worker"', service)
            self.assertTrue(all(call[:2] == ["systemctl", "--user"] for call in scheduler.calls))

    def test_windows_task_is_interactive_and_limited(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "win32"):
            scheduler = RecordingScheduler(Path(temporary))
            scheduler.enable(120)
            arguments = scheduler.calls[-1]
            self.assertIn("/IT", arguments)
            self.assertIn("LIMITED", arguments)
            self.assertNotIn("HIGHEST", arguments)
            self.assertEqual(arguments[arguments.index("/MO") + 1], "2")

    def test_invalid_interval_never_registers_a_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            scheduler = RecordingScheduler(Path(temporary))
            with self.assertRaises(PhotosError):
                scheduler.enable(10)
            self.assertEqual(scheduler.calls, [])

    def test_public_settings_never_include_album_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publish_settings({"interval": 300, "running": True,
                              "albums": [{"url": "synthetic-secret"}]}, root)
            self.assertEqual(public_settings(root), {"interval": 300, "running": True})
            self.assertNotIn("secret", (root / "settings.json").read_text())

    def test_overlapping_operations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with operation_lock(Path(temporary)):
                with self.assertRaises(PhotosError):
                    with operation_lock(Path(temporary)):
                        self.fail("Second operation unexpectedly acquired the lock")
