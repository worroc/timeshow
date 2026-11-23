"""Remove this user's Linux integration and, only on request, private data."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

from .desktop import app_directory, config_directory
from .photos import PhotosError
from .processes import command, operation_lock
from .scheduling import Scheduler
from .security import KeyringProtector
from .settings import public_settings, publish_settings


def _stop_processes() -> None:
    prefixes = [command(mode) for mode in ("gui", "tray")]
    scripts = {str(Path(sys.executable).parent / name) for name in ("timeshow-gui", "timeshow-tray")}
    pending = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = os.fsdecode(entry.joinpath("cmdline").read_bytes()).strip("\0").split("\0")
            matches = any(args[:len(prefix)] == prefix for prefix in prefixes)
            matches = matches or bool(scripts.intersection(args[:2]))
            matches = matches or (args[:2] == [sys.executable, "-m"]
                                  and len(args) > 2 and args[2] in {"timeshow.gui", "timeshow.tray"})
            if matches:
                os.kill(int(entry.name), signal.SIGTERM)
                pending.append(entry)
        except (FileNotFoundError, ProcessLookupError):
            continue
    deadline = time.monotonic() + 5
    while any(entry.exists() for entry in pending):
        if time.monotonic() >= deadline:
            raise PhotosError("Timeshow is still closing. Close it and run uninstall again.")
        time.sleep(0.05)


def _remove_data(directory: Path) -> None:
    record_path = directory / "key.json"
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text())
            if record.get("mode") == "keyring":
                backend = KeyringProtector()._backend()
                account = record["account"]
                if backend.get_password("Timeshow", account) is not None:
                    backend.delete_password("Timeshow", account)
        except Exception:
            # Keep the key record so a failed credential deletion can be retried.
            raise PhotosError("Could not remove the saved key. User data was kept; unlock your credential store and retry.") from None
    data = app_directory()
    runtime_base = os.environ.get("XDG_RUNTIME_DIR")
    runtime = Path(runtime_base) / "timeshow" if runtime_base else data / "runtime"
    for path in (runtime, data, directory):
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--yes", action="store_true", help="Also delete settings, albums, history, images, and the saved key.")
    choice.add_argument("--keep-data", action="store_true", help="Keep all user data without prompting.")
    args = parser.parse_args(arguments)
    if not sys.platform.startswith("linux") or os.getuid() == 0:
        parser.error("Run uninstall as your normal Linux desktop user, without sudo.")
    remove_data = args.yes
    if not args.yes and not args.keep_data:
        try:
            remove_data = input("Remove Timeshow data (settings, albums, history, cache, key)? [y/N] ").strip().lower() in {"y", "yes"}
        except EOFError:
            remove_data = False
    directory = config_directory()
    units = directory.parent / "systemd/user"
    try:
        scheduler = Scheduler(directory)
        if (units / "timeshow.timer").exists():
            scheduler.disable()
        if (units / "timeshow.service").exists():
            scheduler._run(["systemctl", "--user", "stop", "timeshow.service"])
        _stop_processes()
        with operation_lock(directory):
            # The lock rejects cleanup while a manual worker is still active.
            if (directory / "settings.json").exists():
                settings = public_settings(directory)
                settings["running"] = False
                publish_settings(settings, directory)
            for name in ("timeshow.timer", "timeshow.service"):
                (units / name).unlink(missing_ok=True)
            if units.exists():
                scheduler._run(["systemctl", "--user", "daemon-reload"])
            data_base = app_directory().parent
            for path in (
                data_base / "applications/timeshow.desktop",
                data_base / "icons/hicolor/scalable/apps/timeshow.svg",
                directory.parent / "autostart/timeshow-tray.desktop",
            ):
                path.unlink(missing_ok=True)
            if remove_data:
                _remove_data(directory)
        print("User integration removed. " + ("User data deleted." if remove_data else "User data kept."))
        print("Choose another wallpaper in desktop Settings if needed. Checkout and PoC files are kept.")
        return 0
    except (PhotosError, OSError):
        print("Uninstall could not finish. Close Timeshow and check your user scheduler, file permissions, and unlocked credential store. User data may remain; retry uninstall.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
