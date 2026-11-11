"""Application workflow: enumerate, select, download once, stop."""

from dataclasses import asdict, dataclass
from pathlib import Path
import secrets

from .http import HttpClient, TimeshowError
from .photos import ImageCandidate, PhotosClient
from .storage import write_json, write_private


@dataclass(frozen=True)
class DownloadResult:
    candidate_count: int
    image_path: Path


def select_image(album_url: str, output: Path, client: HttpClient) -> tuple[ImageCandidate, int]:
    """List the complete album, save candidates, and choose uniformly by media ID."""
    images = PhotosClient(client).list_images(album_url)
    if not images:
        raise TimeshowError("The shared album contains no eligible images.")
    write_json(output / "candidates.json", [asdict(image) for image in images])
    return secrets.choice(images), len(images)


def download_image(image: ImageCandidate, output: Path, client: HttpClient) -> Path:
    """Fetch and save exactly one display image, then record the completed selection."""
    downloaded = PhotosClient(client).pull_image(image)
    image_path = output / f"image-{secrets.token_hex(8)}{downloaded.extension}"
    write_private(image_path, downloaded.body)
    write_json(output / "selection.json", {"candidate": asdict(image), "filename": image_path.name})
    return image_path


def download_one(album_url: str, output: Path, client: HttpClient | None = None) -> DownloadResult:
    client = client if client is not None else HttpClient()
    image, count = select_image(album_url, output, client)
    return DownloadResult(count, download_image(image, output, client))
