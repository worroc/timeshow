"""Compatibility imports; new callers should use timeshow.photos.PhotosClient."""

from .photos._album import (
    CALLBACK,
    MAX_PAGES,
    PAGE_REQUEST,
    RPC_URL,
    GooglePhotosAlbum,
    ImageCandidate,
    page_items,
    parse_initial_page,
    parse_rpc_page,
)

__all__ = [
    "CALLBACK", "MAX_PAGES", "PAGE_REQUEST", "RPC_URL", "GooglePhotosAlbum",
    "ImageCandidate", "page_items", "parse_initial_page", "parse_rpc_page",
]
