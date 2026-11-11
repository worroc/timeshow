#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
"""Measure separate processes with synthetic photos and no real wallpaper changes."""

import argparse
import ctypes
from ctypes import wintypes
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

PASSWORD = "synthetic benchmark password"


def memory() -> dict:
    if sys.platform.startswith("linux"):
        values = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value, _ = line.split()
                values[key.rstrip(":")] = int(value) / 1024
        return {"rss_mib": values["VmRSS"], "peak_rss_mib": values["VmHWM"]}
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise RuntimeError("Could not read process memory")
        return {"rss_mib": counters.WorkingSetSize / 1024**2,
                "peak_rss_mib": counters.PeakWorkingSetSize / 1024**2}
    raise RuntimeError("Memory profiling supports Windows and Linux")


class FakeDesktop:
    def set_wallpaper(self, path):
        if not path.is_file():
            raise RuntimeError("Synthetic wallpaper was not written")


class FakeScheduler:
    def enable(self, interval):
        pass

    def disable(self):
        pass


def fixture(directory: Path) -> None:
    image_module = importlib.import_module("PIL.Image")
    security = importlib.import_module("timeshow.security")
    storage = importlib.import_module("timeshow.storage")
    image = image_module.new("RGB", (4000, 3000), (50, 125, 105))
    image.save(directory / "synthetic.jpg", quality=90)
    image.close()
    vault = security.Vault.open(directory / "config", security.PasswordProtector(PASSWORD), directory / "cache")
    state = vault.load_state()
    state["albums"] = [{"id": "synthetic-album", "label": "Synthetic photos",
                         "url": "https://photos.google.com/share/synthetic?key=synthetic", "enabled": True}]
    for number in range(1103):
        key = f"synthetic-{number}"
        state["images"][key] = {"media_id": key, "url": "https://lh3.googleusercontent.com/synthetic",
                                 "width": 4000, "height": 3000, "capture_time_ms": None,
                                 "album_ids": ["synthetic-album"]}
    vault.put_image("synthetic-0", (directory / "synthetic.jpg").read_bytes())
    state["current"] = {"media_id": "synthetic-0", "path": str(directory / "synthetic.jpg")}
    state["history"] = ["synthetic-0"]
    state["seen"] = ["synthetic-0"]
    state["cursor"] = 0
    vault.save_state(state)
    storage.write_json(directory / "config/settings.json", {"running": False, "interval": 300})


def child(role: str, directory: Path) -> int:
    if role == "tray":
        widgets = importlib.import_module("PySide6.QtWidgets")
        core = importlib.import_module("PySide6.QtCore")
        tray_module = importlib.import_module("timeshow.tray")
        app = widgets.QApplication([])
        app.setQuitOnLastWindowClosed(False)
        tray = tray_module.Tray(app)
        started = time.process_time()
        core.QTimer.singleShot(2000, app.quit)
        app.exec()
        report = {**memory(), "idle_cpu_seconds_over_2s": time.process_time() - started,
                  "loaded_photo_engine": "timeshow.player" in sys.modules,
                  "loaded_crypto": "cryptography" in sys.modules}
        tray.icon.hide()
    else:
        security = importlib.import_module("timeshow.security")
        player_module = importlib.import_module("timeshow.player")
        photos = importlib.import_module("timeshow.photos")
        vault = security.Vault.open(directory / "config", security.PasswordProtector(PASSWORD), directory / "cache")
        class Source:
            def pull_image(self, image):
                return photos.DownloadedImage((directory / "synthetic.jpg").read_bytes(), ".jpg")
        player = player_module.Player(vault, FakeDesktop(), directory / "runtime", Source())
        if role == "worker":
            started = time.perf_counter()
            player.next()
            report = {**memory(), "switch_seconds": time.perf_counter() - started,
                      "loaded_qt": "PySide6" in sys.modules}
        else:
            widgets = importlib.import_module("PySide6.QtWidgets")
            core = importlib.import_module("PySide6.QtCore")
            window_module = importlib.import_module("timeshow.gui.window")
            app = widgets.QApplication([])
            window = window_module.Window(player, scheduler=FakeScheduler(), isolated=False)
            window.show()
            started = time.process_time()
            core.QTimer.singleShot(2000, app.quit)
            app.exec()
            report = {**memory(), "idle_cpu_seconds_over_2s": time.process_time() - started}
            window.quitting = True
            window.close()
    print(json.dumps({"role": role, **report}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["tray", "gui", "worker"])
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.role:
        return child(args.role, args.fixture)
    with tempfile.TemporaryDirectory(prefix="timeshow-footprint-") as temporary:
        directory = Path(temporary)
        fixture(directory)
        environment = dict(os.environ)
        environment.update(QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(directory),
                           XDG_DATA_HOME=str(directory / "data"))
        results = []
        for role in ["tray", "gui", "worker"]:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--role", role,
                                     "--fixture", str(directory)], env=environment,
                                    capture_output=True, text=True, check=True, timeout=60)
            results.append(json.loads(result.stdout.strip().splitlines()[-1]))
        report = {"platform": sys.platform, "python": sys.version.split()[0],
                  "fixture": "1103 synthetic candidates; 4000x3000 JPEG; 1920x1080 wallpaper",
                  "method": "Separate source processes, Qt offscreen, RSS includes shared libraries. No network or real wallpaper changes.",
                  "measurements": results, "between_switches_worker_rss_mib": 0,
                  "closed_gui_rss_mib": 0}
        text = json.dumps(report, indent=2)
        if args.output:
            args.output.write_text(text + "\n")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
