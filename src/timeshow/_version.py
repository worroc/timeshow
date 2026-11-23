"""Read the shared project version in a checkout, wheel, or frozen bundle."""

from importlib.metadata import version
from pathlib import Path
import tomllib


def _read_version() -> str:
    bundled = Path(__file__).with_name("_version.txt")
    if bundled.is_file():
        return bundled.read_text().strip()
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if project.is_file():
        return tomllib.loads(project.read_text())["project"]["version"]
    return version("timeshow")


APP_VERSION = _read_version()
