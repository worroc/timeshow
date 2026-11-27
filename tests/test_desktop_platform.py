"""Check desktop command environments without changing the user's desktop."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from timeshow.desktop import Desktop
from timeshow.desktop.platform import run_command


class DesktopPlatformTests(unittest.TestCase):
    def test_all_gnome_calls_restore_system_libraries_and_keep_session(self):
        for original in (None, "", "/synthetic/system"):
            environment = {
                "LD_LIBRARY_PATH": "/synthetic/bundle", "XDG_CURRENT_DESKTOP": "GNOME",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/synthetic/bus", "DISPLAY": ":99",
                "WAYLAND_DISPLAY": "wayland-99",
            }
            if original is not None:
                environment["LD_LIBRARY_PATH_ORIG"] = original
            with self.subTest(original=original), patch("sys.platform", "linux"), patch(
                "sys.frozen", True, create=True
            ), patch.dict(os.environ, environment, clear=True), patch(
                "timeshow.desktop.platform.subprocess.run"
            ) as run:
                run.return_value.stdout = "picture-uri\npicture-uri-dark\n"
                Desktop().set_wallpaper(Path("synthetic wallpaper.jpg"))
                self.assertEqual(run.call_count, 3)
                self.assertEqual([call.args[0][1] for call in run.call_args_list],
                                 ["set", "list-keys", "set"])
                for call in run.call_args_list:
                    child = call.kwargs["env"]
                    if original is None:
                        self.assertNotIn("LD_LIBRARY_PATH", child)
                    else:
                        self.assertEqual(child["LD_LIBRARY_PATH"], original)
                    for name in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY"):
                        self.assertEqual(child[name], environment[name])
                self.assertEqual(dict(os.environ), environment)

    def test_source_and_windows_commands_keep_inherited_environment(self):
        for platform, frozen in [("linux", False), ("win32", True)]:
            with self.subTest(platform=platform), patch("sys.platform", platform), patch(
                "sys.frozen", frozen, create=True
            ), patch("timeshow.desktop.platform.subprocess.run") as run:
                run_command(["synthetic-desktop-command"])
                self.assertIsNone(run.call_args.kwargs["env"])
