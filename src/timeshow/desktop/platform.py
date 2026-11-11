"""Keep OS calls out of the rotation and GUI logic."""

import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

from ..photos import PhotosError
from ..http import validate_url
from ..storage import private_directory


def app_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Timeshow"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "timeshow"


def config_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Timeshow"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "timeshow"


def runtime_directory() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") if sys.platform != "win32" else None
    path = Path(base) / "timeshow" if base else app_directory() / "runtime"
    private_directory(path)
    return path


def run_command(arguments: list[str]) -> None:
    try:
        subprocess.run(arguments, check=True, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise PhotosError("Desktop operation failed. Check the selected desktop and session.") from None


class Desktop:
    def set_wallpaper(self, path: Path) -> None:
        path = path.resolve()
        if sys.platform == "win32":
            # SPIF_UPDATEINIFILE | SPIF_SENDCHANGE; SPI_SETDESKWALLPAPER.
            if not ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3):
                raise PhotosError("Windows could not change the wallpaper.")
            return
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "gnome" in desktop or "ubuntu" in desktop:
            run_command(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", path.as_uri()])
            # Older GNOME versions do not have the dark wallpaper key.
            keys = subprocess.run(
                ["gsettings", "list-keys", "org.gnome.desktop.background"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout.splitlines()
            if "picture-uri-dark" in keys:
                run_command(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", path.as_uri()])
            return
        if "kde" in desktop:
            executable = shutil.which("qdbus6") or shutil.which("qdbus")
            if not executable:
                raise PhotosError("KDE wallpaper support needs qdbus6 or qdbus.")
            script = (
                'var screens = desktops(); for (var i=0; i<screens.length; i++) {'
                'var d=screens[i]; d.wallpaperPlugin="org.kde.image";'
                'd.currentConfigGroup=["Wallpaper","org.kde.image","General"];'
                f'd.writeConfig("Image",{json.dumps(path.as_uri())});}}'
            )
            run_command([executable, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script])
            return
        raise PhotosError("Wallpaper changes support Windows, Ubuntu/GNOME, and KDE Plasma.")

    def reveal(self, path: Path) -> None:
        if sys.platform == "win32":
            run_command(["explorer.exe", "/select," + str(path.resolve())])
        else:
            run_command(["xdg-open", str(path.resolve().parent)])

    def open_album(self, url: str) -> None:
        from_url = url.strip()
        validate_url(from_url, album=True)
        if not webbrowser.open(from_url):
            raise PhotosError("Could not open the default browser.")
