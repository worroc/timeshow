#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyinstaller>=6.10,<7", "PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
"""Build on the target OS. Package only code and required dependency licenses."""

from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--windowed", "--name", "Timeshow", "--paths", str(project / "src"),
        "--copy-metadata", "keyring",
        "--hidden-import", "timeshow.worker", "--hidden-import", "timeshow.tray",
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
