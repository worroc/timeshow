"""Set up encrypted user storage without asking users to choose a key method."""

import sys
from pathlib import Path

from .desktop import app_directory, config_directory
from .photos import PhotosError
from .processes import operation_lock
from .security import DPAPIProtector, KeyringProtector, Vault


def _initialize_storage(directory: Path, cache: Path) -> Vault | None:
    """Create storage once. Existing storage is left untouched, even if locked."""
    with operation_lock(directory):
        if Vault.mode(directory) is not None:
            return None
        protector = DPAPIProtector() if sys.platform == "win32" else KeyringProtector()
        try:
            return Vault.open(directory, protector, cache)
        except PhotosError:
            if sys.platform == "win32":
                message = "Timeshow could not set up secure storage for your Windows account."
            else:
                message = (
                    "Timeshow could not set up secure storage. "
                    "Make sure your desktop password store is installed and unlocked, then try again."
                )
            raise PhotosError(message) from None


def main() -> int:
    try:
        _initialize_storage(config_directory(), app_directory() / "cache")
    except (PhotosError, OSError) as error:
        message = str(error) if isinstance(error, PhotosError) else "Could not access private app storage."
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
