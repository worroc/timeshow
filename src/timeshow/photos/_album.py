"""Read-only access to Google's undocumented shared-album pages."""

from dataclasses import dataclass
import json
import re
from urllib.parse import urlencode

from ._http import HttpClient, TimeshowError, validate_url

CALLBACK = re.compile(r"AF_initDataCallback\(\{key:\s*['\"][^'\"]+['\"]")
PAGE_REQUEST = re.compile(
    r'snAcKc[^}]*?request:\s*\[\s*"([A-Za-z0-9_-]+)"\s*,\s*null\s*,\s*null'
    r'\s*,\s*"([A-Za-z0-9_-]+)"', re.S
)
RPC_URL = "https://photos.google.com/u/0/_/PhotosUi/data/batchexecute?rpcids=snAcKc"
MAX_PAGES = 100


@dataclass(frozen=True)
class ImageCandidate:
    media_id: str
    url: str
    width: int
    height: int
    capture_time_ms: int | None

    @property
    def download_url(self) -> str:
        # Request a display image at its reported dimensions, not an archival original.
        base = self.url.split("=", 1)[0]
        return f"{base}=w{min(self.width, 16383)}-h{min(self.height, 16383)}"


def parse_initial_page(html: str) -> list:
    decoder = json.JSONDecoder()
    for match in CALLBACK.finditer(html):
        start = html.find("data:", match.end())
        if start < 0:
            continue
        try:
            data, _ = decoder.raw_decode(html[start + 5:].lstrip())
        except ValueError:
            continue
        if isinstance(data, list) and len(data) > 3 and isinstance(data[1], list):
            return data
    raise TimeshowError("Cannot read album data. Check link sharing; Google may have changed its page.")


def parse_rpc_page(body: str) -> list:
    try:
        for line in body.splitlines():
            if not line.lstrip().startswith("[["):
                continue
            for entry in json.loads(line):
                if isinstance(entry, list) and entry[:2] == ["wrb.fr", "snAcKc"]:
                    data = json.loads(entry[2])
                    if isinstance(data, list):
                        return data
    except (ValueError, IndexError, TypeError):
        pass
    raise TimeshowError("Cannot read an album continuation page; listing was stopped.")


def page_items(data: list) -> tuple[list[ImageCandidate], str | None]:
    if len(data) < 3 or not isinstance(data[1], list):
        raise TimeshowError("Unexpected album page structure; listing was stopped.")
    images = []
    for item in data[1]:
        try:
            media_id, detail = item[:2]
            url, width, height = detail[:3]
            if not isinstance(media_id, str) or not media_id:
                raise ValueError
            if not isinstance(url, str):
                raise ValueError
            validate_url(url)
            if type(width) is not int or type(height) is not int or min(width, height) <= 0:
                raise ValueError
            metadata = item[9] if len(item) > 9 else {}
            if isinstance(metadata, dict) and "76647426" in metadata:
                continue
            capture_time = item[2] if len(item) > 2 and type(item[2]) is int else None
            images.append(ImageCandidate(media_id, url, width, height, capture_time))
        except (ValueError, TypeError, IndexError):
            raise TimeshowError("Unexpected media entry; refusing to silently skip album items.") from None
    token = data[2]
    if token is not None and not isinstance(token, str):
        raise TimeshowError("Unexpected album continuation token.")
    return images, token or None


class GooglePhotosAlbum:
    def __init__(self, client: HttpClient):
        self.client = client

    def list_images(self, album_url: str) -> list[ImageCandidate]:
        validate_url(album_url, album=True)
        html = self.client.fetch(album_url).body.decode("utf-8")
        data = parse_initial_page(html)
        request = PAGE_REQUEST.search(html)
        candidates: dict[str, ImageCandidate] = {}
        seen_tokens: set[str] = set()
        for _ in range(MAX_PAGES):
            images, token = page_items(data)
            for image in images:
                candidates.setdefault(image.media_id, image)
            if token is None:
                return list(candidates.values())
            if token in seen_tokens:
                raise TimeshowError("Album pagination repeated a token; listing was stopped.")
            if request is None:
                raise TimeshowError("Album has more pages, but its continuation request is missing.")
            seen_tokens.add(token)
            payload = json.dumps([request[1], token, None, request[2]])
            envelope = json.dumps([[["snAcKc", payload, None, "generic"]]])
            response = self.client.fetch(RPC_URL, urlencode({"f.req": envelope}).encode())
            data = parse_rpc_page(response.body.decode("utf-8"))
        raise TimeshowError("Album exceeded the 100-page limit; refusing an incomplete listing.")
