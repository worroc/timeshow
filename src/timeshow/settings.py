"""Plain user preferences. Never write album links or image identities here."""

import json
from pathlib import Path

from .desktop import config_directory
from .photos import PhotosError
from .storage import write_json

PUBLIC_FIELDS = frozenset({"running", "interval", "fit", "after", "before", "screen_size"})


def public_settings(directory: Path | None = None) -> dict:
    path = (directory if directory is not None else config_directory()) / "settings.json"
    if not path.exists():
        return {"running": False, "interval": 300}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError
        return {key: entry for key, entry in value.items() if key in PUBLIC_FIELDS}
    except (ValueError, OSError):
        raise PhotosError("The user settings file cannot be read.") from None


def publish_settings(state: dict, directory: Path) -> None:
    preferences = {key: state[key] for key in PUBLIC_FIELDS if key in state}
    write_json(directory / "settings.json", preferences)
