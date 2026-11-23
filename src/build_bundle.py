#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyinstaller>=6.10,<7", "PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
"""Build on the target OS. Package only code and required dependency licenses."""

from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def _check_bundle(bundle: Path, executable: str = "Timeshow", version: str | None = None) -> None:
    expected = {executable, "_internal", "LICENSE", "dependency-licenses"}
    if {path.name for path in bundle.iterdir()} != expected:
        raise ValueError("Expected a clean Timeshow bundle with executable, libraries, and license notices.")
    if not os.access(bundle / executable, os.X_OK):
        raise ValueError("The Timeshow bundle executable is missing or not executable.")
    for path in bundle.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError("Bundle contains a symbolic link outside its directory.")
        if path.name in {".private", ".git", ".env", "key.json", "state.enc", "settings.json"}:
            raise ValueError("Bundle contains local state or private inputs.")
    if version is not None:
        bundled_version = bundle / "_internal/timeshow/_version.txt"
        if not bundled_version.is_file() or bundled_version.read_text().strip() != version:
            raise ValueError("Bundle version differs from pyproject.toml. Rebuild the desktop bundle first.")


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    version_file = project / "build/timeshow-version/_version.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(version + "\n")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--windowed", "--name", "Timeshow", "--paths", str(project / "src"),
        "--copy-metadata", "keyring",
        "--add-data", str(project / "src/timeshow/assets") + ":timeshow/assets",
        "--add-data", str(version_file) + ":timeshow",
        "--icon", str(project / "src/timeshow/assets/timeshow.ico"),
        "--hidden-import", "timeshow.worker", "--hidden-import", "timeshow.tray",
        "--hidden-import", "timeshow._windows_uninstall",
        "--hidden-import", "timeshow.gui.window", str(project / "src/desktop_main.py"),
    ], cwd=project, check=True)
    bundle = project / "dist/Timeshow"
    shutil.copy2(project / "LICENSE", bundle / "LICENSE")
    notices = bundle / "dependency-licenses"
    notices.mkdir(exist_ok=True)
    for name in ["PySide6-Essentials", "shiboken6", "cryptography", "keyring", "Pillow"]:
        distribution = metadata.distribution(name)
        for entry in distribution.files or []:
            if "license" in str(entry).lower() or "copying" in str(entry).lower():
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    destination = notices / name / str(entry).replace("..", "_")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    print(f"Built {bundle}. Private inputs and application data are not bundled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
