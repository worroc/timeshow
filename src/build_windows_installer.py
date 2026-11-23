#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyinstaller>=6.10,<7", "PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
"""Build the per-user Windows installer with the existing bundle and Inno Setup."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from build_bundle import _check_bundle, main as build_bundle


def _compiler() -> Path:
    executable = shutil.which("ISCC.exe")
    if executable:
        return Path(executable)
    for directory in ("ProgramFiles(x86)", "ProgramFiles"):
        if directory in os.environ:
            for major in (6, 7):
                candidate = Path(os.environ[directory]) / f"Inno Setup {major}/ISCC.exe"
                if candidate.is_file():
                    return candidate
    raise FileNotFoundError("Install Inno Setup or pass --iscc with the path to ISCC.exe.")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Use an existing clean Windows bundle.")
    parser.add_argument("--iscc", type=Path, help="Path to the Inno Setup compiler.")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: dist).")
    args = parser.parse_args(arguments)
    if sys.platform != "win32":
        parser.error("Build on Windows, for example with the repository's Windows GitHub Actions job.")
    project = Path(__file__).resolve().parent.parent
    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    compiler = args.iscc.resolve() if args.iscc else _compiler()
    if args.bundle is None:
        build_bundle()
    bundle = (args.bundle if args.bundle is not None else project / "dist/Timeshow").resolve()
    _check_bundle(bundle, executable="Timeshow.exe", version=version)
    output_dir = (args.output_dir if args.output_dir is not None else project / "dist").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(compiler), f"/DAppVersion={version}", f"/DBundleDir={bundle}",
        f"/DProjectDir={project}", f"/DInstallerOutputDir={output_dir}",
        str(project / "src/windows_installer.iss"),
    ], check=True)
    output = output_dir / f"Timeshow-{version}-Setup.exe"
    if not output.is_file():
        raise FileNotFoundError("Inno Setup did not produce the expected installer.")
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (output_dir / "SHA256SUMS-windows").write_text(f"{digest}  {output.name}\n")
    print(f"Built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
