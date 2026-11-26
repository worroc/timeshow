"""Scheduler commands are recorded, never registered on the test machine."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeshow.desktop import Desktop, app_directory, config_directory
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
    def test_frozen_linux_scheduler_restores_original_environment(self):
        environment = {"LD_LIBRARY_PATH": "/synthetic/bundle", "LD_LIBRARY_PATH_ORIG": "/synthetic/system",
                       "DBUS_SESSION_BUS_ADDRESS": "unix:path=/synthetic/bus", "DISPLAY": ":99"}
        with patch("sys.platform", "linux"), patch("sys.frozen", True, create=True), patch.dict(
            os.environ, environment, clear=True
        ), patch("timeshow.scheduling.subprocess.run") as run:
            Scheduler(Path("synthetic-config"))._run(["systemctl", "--version"])
            child = run.call_args.kwargs["env"]
            self.assertEqual(child["LD_LIBRARY_PATH"], "/synthetic/system")
            self.assertEqual(child["DBUS_SESSION_BUS_ADDRESS"], environment["DBUS_SESSION_BUS_ADDRESS"])
            self.assertEqual(child["DISPLAY"], ":99")
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/synthetic/bundle")

    def test_frozen_linux_scheduler_handles_unset_or_empty_original_path(self):
        for original in (None, ""):
            environment = {"LD_LIBRARY_PATH": "/synthetic/bundle"}
            if original is not None:
                environment["LD_LIBRARY_PATH_ORIG"] = original
            with self.subTest(original=original), patch("sys.platform", "linux"), patch(
                "sys.frozen", True, create=True
            ), patch.dict(os.environ, environment, clear=True), patch(
                "timeshow.scheduling.subprocess.run"
            ) as run:
                Scheduler(Path("synthetic-config"))._run(["systemctl", "--version"])
                child = run.call_args.kwargs["env"]
                if original is None:
                    self.assertNotIn("LD_LIBRARY_PATH", child)
                else:
                    self.assertEqual(child["LD_LIBRARY_PATH"], "")
                self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/synthetic/bundle")

    def test_source_and_windows_scheduler_keep_inherited_environment(self):
        for platform, frozen in [("linux", False), ("win32", True)]:
            with self.subTest(platform=platform), patch("sys.platform", platform), patch(
                "sys.frozen", frozen, create=True
            ), patch("timeshow.scheduling.subprocess.run") as run:
                Scheduler(Path("synthetic-config"))._run(["synthetic-scheduler"])
                self.assertIsNone(run.call_args.kwargs["env"])

    def test_open_folder_opens_directory_itself_on_each_platform(self):
        folder = Path("synthetic-config").resolve()
        for platform, executable in [("linux", "xdg-open"), ("win32", "explorer.exe")]:
            with patch("sys.platform", platform), patch("timeshow.desktop.platform.run_command") as run:
                Desktop().open_folder(folder)
                run.assert_called_once_with([executable, str(folder)])

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

    def test_deb_install_uses_package_service_and_only_writes_user_timer(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "linux"), patch(
            "sys.frozen", True, create=True
        ), patch("sys.executable", "/opt/timeshow/Timeshow"), patch.object(Path, "is_file", return_value=True):
            root = Path(temporary)
            scheduler = RecordingScheduler(root / "timeshow")
            scheduler.enable(300)
            self.assertTrue((root / "systemd/user/timeshow.timer").exists())
            self.assertFalse((root / "systemd/user/timeshow.service").exists())
            self.assertTrue(all(call[:2] == ["systemctl", "--user"] for call in scheduler.calls))

    def test_invalid_interval_never_registers_a_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            scheduler = RecordingScheduler(Path(temporary))
            with self.assertRaises(PhotosError):
                scheduler.enable(10)
            self.assertEqual(scheduler.calls, [])

    def test_public_settings_never_include_album_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publish_settings({"interval": 300, "running": True, "change_on_login": True,
                              "albums": [{"url": "synthetic-secret"}]}, root)
            self.assertEqual(public_settings(root), {"interval": 300, "running": True, "change_on_login": True})
            self.assertNotIn("secret", (root / "settings.json").read_text())

    def test_overlapping_operations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with operation_lock(Path(temporary)):
                with self.assertRaises(PhotosError):
                    with operation_lock(Path(temporary)):
                        self.fail("Second operation unexpectedly acquired the lock")
