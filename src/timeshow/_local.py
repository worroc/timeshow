"""Read local photos using the same candidate and download records as albums."""

from datetime import datetime
import hashlib
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .photos import DownloadedImage, ImageCandidate, PhotosError
from .photos._image import image_extension


_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _capture_time(image: Image.Image) -> int | None:
    exif = image.getexif()
    detail = exif.get_ifd(34665)
    value = detail.get(36867) or exif.get(36867)
    if not value:
        return None
    try:
        captured = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        offset = detail.get(36881) or exif.get(36881)
        if offset:
            captured = datetime.fromisoformat(captured.isoformat() + offset)
        return int(captured.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _walk_error(error: OSError) -> None:
    raise error


class _LocalPhotos:
    def list_images(self, directory: str) -> list[ImageCandidate]:
        try:
            root = Path(directory).resolve(strict=True)
            if not root.is_dir():
                raise OSError
            images = []
            for folder, directories, files in os.walk(root, onerror=_walk_error, followlinks=False):
                directories[:] = sorted(name for name in directories
                                        if not (Path(folder) / name).is_symlink())
                for name in sorted(files):
                    path = Path(folder) / name
                    if path.suffix.lower() not in _EXTENSIONS or path.is_symlink():
                        continue
                    with Image.open(path) as image:
                        if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                            raise ValueError
                        image.verify()
                    with Image.open(path) as image:
                        width, height = image.size
                        captured = _capture_time(image)
                    identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
                    images.append(ImageCandidate("local:" + identity, str(path), width, height, captured))
            return images
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            raise PhotosError(
                "Could not read the complete local photo folder. "
                "Check that the folder is available and its image files are readable and valid."
            ) from None

    def pull_image(self, image: ImageCandidate) -> DownloadedImage:
        try:
            body = Path(image.url).read_bytes()
            return DownloadedImage(body, image_extension(body))
        except (OSError, ValueError):
            raise PhotosError("Could not read the local photo. Check that its folder is available.") from None
