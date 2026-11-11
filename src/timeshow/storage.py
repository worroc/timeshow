"""Private, atomic output storage. File permissions are not encryption."""

import json
import os
from pathlib import Path
import tempfile

from .http import TimeshowError
from .photos._image import image_extension  # Keep the original import path working.


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise TimeshowError("Private output directory must not be a symbolic link.")
    path.chmod(0o700)


def write_private(path: Path, body: bytes) -> None:
    private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".timeshow-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    write_private(path, (json.dumps(value, indent=2) + "\n").encode())


