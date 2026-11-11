"""Recognize supported image downloads without saving anything to disk."""

from ._http import TimeshowError


def image_extension(body: bytes) -> str:
    if body.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if body[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return ".webp"
    raise TimeshowError("Download was not a supported JPEG, PNG, WebP, or GIF image.")
