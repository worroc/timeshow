"""Internal HTTPS transport. Errors must not disclose private request URLs."""

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
ALBUM_HOSTS = {"photos.app.goo.gl", "photos.google.com"}


class TimeshowError(Exception):
    """An expected failure that is safe to show to the user."""


def validate_url(url: str, *, album: bool = False) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        allowed = host in ALBUM_HOSTS
        if not album:
            allowed = allowed or host.endswith(".googleusercontent.com")
        valid = (
            parsed.scheme == "https"
            and allowed
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        raise TimeshowError("Expected an HTTPS Google Photos album or image URL.")


class GoogleRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str


class HttpClient:
    def __init__(self, timeout: float = 30):
        self.timeout = timeout
        self.opener = build_opener(GoogleRedirectHandler())

    def fetch(self, url: str, data: bytes | None = None) -> Response:
        validate_url(url)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Timeshow/0.1)",
                   "Accept-Language": "en-US,en;q=0.9"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        request = Request(url, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                validate_url(response.url)
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise TimeshowError("Google response exceeded the 64 MiB size limit.")
                return Response(body, response.headers.get_content_type())
        except HTTPError as error:
            raise TimeshowError(f"Google request failed with HTTP {error.code}.") from None
        except (URLError, TimeoutError, OSError):
            raise TimeshowError("Google request failed. Check your network and album sharing.") from None
