"""Public interface for listing photos and pulling one selected image."""

from dataclasses import dataclass

from ._album import GooglePhotosAlbum, ImageCandidate
from ._http import HttpClient
from ._image import image_extension


@dataclass(frozen=True)
class DownloadedImage:
    """Image bytes in memory and a validated filename extension."""

    body: bytes
    extension: str


class PhotosClient:
    """Own all Google Photos retrieval; leave selection and storage to the caller."""

    def __init__(self, transport: HttpClient | None = None):
        self._transport = transport if transport is not None else HttpClient()
        self._album = GooglePhotosAlbum(self._transport)

    def list_images(self, album_url: str) -> list[ImageCandidate]:
        """Return all unique photo candidates, or raise if any page fails."""
        return self._album.list_images(album_url)

    def pull_image(self, image: ImageCandidate) -> DownloadedImage:
        """Fetch one display image into memory, or raise on an invalid response."""
        response = self._transport.fetch(image.download_url)
        return DownloadedImage(response.body, image_extension(response.body))
