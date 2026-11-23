#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyinstaller>=6.10,<7", "PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
"""Build a native Debian package from the existing self-contained desktop bundle."""

import argparse
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib

from build_bundle import main as build_bundle


SERVICE = """[Unit]
Description=Switch Timeshow wallpaper once
After=graphical-session.target
ConditionPathIsExecutable=/opt/timeshow/Timeshow

[Service]
Type=oneshot
ExecStart=/opt/timeshow/Timeshow --mode worker
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Timeshow
Comment=Rotate photos from your selected albums
Exec=/usr/bin/timeshow
Icon=timeshow
StartupWMClass=timeshow
Terminal=false
Categories=Graphics;
StartupNotify=true
"""

AUTOSTART = """[Desktop Entry]
Type=Application
Name=Timeshow tray
Exec=/usr/bin/timeshow-tray
Icon=timeshow
Terminal=false
"""

CACHE_SCRIPT = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi
exit 0
"""


def _write(root: Path, name: str, text: str, mode: int = 0o644) -> None:
    destination = root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    destination.chmod(mode)


def _check_bundle(bundle: Path) -> None:
    expected = {"Timeshow", "_internal", "LICENSE", "dependency-licenses"}
    if {path.name for path in bundle.iterdir()} != expected:
        raise ValueError("Expected a clean Timeshow bundle with executable, libraries, and license notices.")
    if not os.access(bundle / "Timeshow", os.X_OK):
        raise ValueError("The Timeshow bundle executable is missing or not executable.")
    for path in bundle.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError("Bundle contains a symbolic link outside its directory.")
        if path.name in {".private", ".git", ".env", "key.json", "state.enc", "settings.json"}:
            raise ValueError("Bundle contains local state or private inputs.")


def _stage(project: Path, bundle: Path, root: Path, version: str, architecture: str) -> None:
    _check_bundle(bundle)
    bundled_version = bundle / "_internal/timeshow/_version.txt"
    if not bundled_version.is_file() or bundled_version.read_text().strip() != version:
        raise ValueError("Bundle version differs from pyproject.toml. Rebuild the desktop bundle first.")
    target = root / "opt/timeshow"
    target.parent.mkdir(parents=True)
    shutil.copytree(bundle, target, symlinks=True)
    # Package paths must be accessible regardless of the builder's umask.
    for path in (target, *target.rglob("*")):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    for executable, mode in [("timeshow", "gui"), ("timeshow-tray", "tray"), ("timeshow-worker", "worker")]:
        _write(root, "usr/bin/" + executable,
               f'#!/bin/sh\nexec /opt/timeshow/Timeshow --mode {mode} "$@"\n', 0o755)
    _write(root, "usr/share/applications/timeshow.desktop", DESKTOP)
    _write(root, "etc/xdg/autostart/timeshow-tray.desktop", AUTOSTART)
    _write(root, "usr/lib/systemd/user/timeshow.service", SERVICE)
    _write(root, "usr/share/icons/hicolor/scalable/apps/timeshow.svg",
           (project / "src/timeshow/assets/timeshow.svg").read_text())
    _write(root, "usr/share/doc/timeshow/copyright", (project / "LICENSE").read_text())
    _write(root, "DEBIAN/conffiles", "/etc/xdg/autostart/timeshow-tray.desktop\n")
    for name in ("postinst", "postrm"):
        _write(root, "DEBIAN/" + name, CACHE_SCRIPT, 0o755)
    glibc = os.confstr("CS_GNU_LIBC_VERSION").split()[1]
    dependencies = [
        f"libc6 (>= {glibc})", "libegl1", "libopengl0",
        "libglib2.0-0t64 | libglib2.0-0", "libglib2.0-bin", "libdbus-1-3",
        "libfontconfig1", "libfreetype6", "libx11-6", "libx11-xcb1", "libxext6",
        "libxrender1", "libxi6", "libsm6", "libice6", "libxcb1", "libxcb-cursor0",
        "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-render-util0",
        "libxcb-randr0", "libxcb-shape0", "libxcb-shm0", "libxcb-sync1",
        "libxcb-xfixes0", "libxcb-render0", "libxcb-xkb1", "libxkbcommon0",
        "libxkbcommon-x11-0", "libwayland-client0", "libwayland-cursor0",
        "libwayland-egl1", "xdg-utils", "hicolor-icon-theme", "gnome-keyring | kwalletmanager",
    ]
    installed_size = sum(path.stat().st_size for path in root.rglob("*")
                         if path.is_file() and not path.is_symlink()) // 1024 + 1
    _write(root, "DEBIAN/control", (
        "Package: timeshow\n"
        f"Version: {version}\nArchitecture: {architecture}\n"
        "Section: graphics\nPriority: optional\nMaintainer: Timeshow contributors\n"
        "Homepage: https://github.com/worroc/timeshow\n"
        f"Installed-Size: {installed_size}\nDepends: {', '.join(dependencies)}\n"
        "Description: Rotate desktop wallpaper from shared photo albums\n"
        " A desktop app with encrypted album links, persistent viewing history,\n"
        " a tray menu, and user-level scheduling. Includes Python and dependencies.\n"
    ))
    for directory in root.rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o755)
    root.chmod(0o755)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Use an already-built clean bundle instead of rebuilding.")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: dist).")
    args = parser.parse_args(arguments)
    if not sys.platform.startswith("linux") or not shutil.which("dpkg-deb") or not shutil.which("dpkg"):
        parser.error("Build on Debian or Ubuntu with dpkg and dpkg-deb installed. No sudo is needed.")
    project = Path(__file__).resolve().parent.parent
    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    subprocess.run(["dpkg", "--validate-version", version], check=True)
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    if args.bundle is None:
        build_bundle()
    bundle = (args.bundle if args.bundle is not None else project / "dist/Timeshow").resolve()
    output_dir = (args.output_dir if args.output_dir is not None else project / "dist").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"timeshow_{version}_{architecture}.deb"
    with tempfile.TemporaryDirectory(prefix="timeshow-deb-") as temporary:
        root = Path(temporary)
        _stage(project, bundle, root, version, architecture)
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(output)], check=True)
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
