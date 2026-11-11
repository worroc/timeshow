"""User-owned OS scheduling. No resident scheduler process or elevated tasks."""

import os
from pathlib import Path
import subprocess
import sys

from .desktop import config_directory
from .photos import PhotosError
from .processes import command
from .storage import private_directory, write_private
from .settings import public_settings, publish_settings  # Preserve existing import paths.


def systemd_argument(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


class Scheduler:
    def __init__(self, directory: Path | None = None):
        self.directory = directory if directory is not None else config_directory()

    def _run(self, arguments: list[str]) -> None:
        try:
            subprocess.run(arguments, capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise PhotosError("Could not configure the user scheduler. Check your logged-in desktop session and permissions.") from None

    def enable(self, interval: int) -> None:
        if not 60 <= interval <= 86340 or interval % 60:
            raise PhotosError("Background rotation uses whole minutes, from 1 to 1439.")
        if sys.platform == "win32":
            self._run(["schtasks.exe", "/Create", "/TN", "Timeshow", "/SC", "MINUTE",
                       "/MO", str(interval // 60), "/TR", subprocess.list2cmdline(command("worker")),
                       "/IT", "/RL", "LIMITED", "/F"])
            return
        if not sys.platform.startswith("linux"):
            raise PhotosError("Background scheduling supports Windows and Linux.")
        units = self.directory.parent / "systemd/user"
        private_directory(units)
        invocation = " ".join(systemd_argument(part) for part in command("worker"))
        service = ("[Unit]\nDescription=Switch Timeshow wallpaper once\nAfter=graphical-session.target\n"
                   "[Service]\nType=oneshot\nExecStart=" + invocation + "\n")
        timer = ("[Unit]\nDescription=Timeshow user wallpaper timer\n"
                 f"[Timer]\nOnActiveSec={interval}s\nOnUnitActiveSec={interval}s\nAccuracySec=1s\n"
                 "[Install]\nWantedBy=timers.target\n")
        write_private(units / "timeshow.service", service.encode())
        write_private(units / "timeshow.timer", timer.encode())
        environment = [name for name in ["DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"] if name in os.environ]
        if environment:
            self._run(["systemctl", "--user", "import-environment", *environment])
        self._run(["systemctl", "--user", "daemon-reload"])
        self._run(["systemctl", "--user", "enable", "--now", "timeshow.timer"])
        self._run(["systemctl", "--user", "restart", "timeshow.timer"])

    def disable(self) -> None:
        if sys.platform == "win32":
            self._run(["schtasks.exe", "/Change", "/TN", "Timeshow", "/DISABLE"])
        else:
            self._run(["systemctl", "--user", "disable", "--now", "timeshow.timer"])
