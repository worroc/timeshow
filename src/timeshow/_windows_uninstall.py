"""Pause and remove this user's schedule before the Windows uninstaller runs."""

from contextlib import nullcontext
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile

from .desktop import config_directory
from .photos import PhotosError
from .processes import operation_lock
from .scheduling import Scheduler
from .settings import public_settings, publish_settings
from .worker_io import report


def _gui_locks(directory: Path) -> list[QLockFile]:
    locks = []
    if directory.exists():
        for name in ("gui.lock", "tray.lock"):
            lock = QLockFile(str(directory / name))
            if not lock.tryLock(100):
                raise PhotosError("Close Timeshow and its tray before uninstalling.")
            locks.append(lock)
    return locks


def main() -> int:
    if sys.platform != "win32":
        report("This cleanup operation is only available on Windows.")
        return 1
    directory = config_directory()
    gui_locks = []
    try:
        gui_locks = _gui_locks(directory)
        # Refuse cleanup while a switch is writing state. A retry is safe.
        lock = operation_lock(directory) if directory.exists() else nullcontext()
        with lock:
            Scheduler(directory)._remove_windows_task()
            if (directory / "settings.json").exists():
                settings = public_settings(directory)
                settings["running"] = False
                publish_settings(settings, directory)
        return 0
    except (PhotosError, OSError):
        report("Close Timeshow and its tray, wait for any wallpaper change to finish, then retry uninstall. Check Task Scheduler access if cleanup still fails.")
        return 1
    finally:
        for lock in gui_locks:
            lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
