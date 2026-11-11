"""Compatibility imports for the original HTTP transport and error type."""

from .photos._http import (
    ALBUM_HOSTS,
    MAX_RESPONSE_BYTES,
    GoogleRedirectHandler,
    HttpClient,
    Response,
    TimeshowError,
    validate_url,
)

__all__ = [
    "ALBUM_HOSTS", "MAX_RESPONSE_BYTES", "GoogleRedirectHandler", "HttpClient",
    "Response", "TimeshowError", "validate_url",
]
