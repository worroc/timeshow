# Google Photos retrieval library

This library owns listing and pulling images from Google Photos link-shared
albums. It does not choose random images, write files, track history, change
wallpaper, or create a GUI. It has no runtime dependencies outside Python.

## Public interface

```python
from timeshow.photos import PhotosClient, PhotosError

client = PhotosClient()
# album_url comes from private local configuration; never hard-code it here.
images = client.list_images(album_url)
if images:
    downloaded = client.pull_image(images[0])
    # downloaded.body contains bytes; downloaded.extension identifies the format.
```

- `PhotosClient.list_images(album_url)` returns `list[ImageCandidate]`. Each
  candidate has `media_id`, `url`, `width`, `height`, and `capture_time_ms`.
- `PhotosClient.pull_image(candidate)` returns `DownloadedImage`, containing
  `body: bytes` and `extension: str`. It fetches exactly one display image.
- `PhotosError` identifies expected retrieval and parsing failures. A caller can
  report its message without exposing the private URL.

Treat candidates and their URLs as private. An empty image list means no eligible
photos. A listing failure raises instead of returning an incomplete result.
Network errors abort the current operation; there are no automatic retries.
An invalid image response also raises. No bytes are written by the library.

## Implementation

The client shares one HTTP transport between listing and pulling. It validates
HTTPS destinations and redirects, limits response size, and uses request timeouts.
Listing parses the shared page, follows continuation tokens, removes duplicate
media IDs, and excludes detected videos. Video detection is best-effort.

`_album.py`, `_http.py`, and `_image.py` are implementation details. Application
code should import from `timeshow.photos`. Tests can inject a transport into
`PhotosClient(transport=...)` to supply synthetic HTTP responses.

Google's shared-page format and pagination RPC are undocumented and can change.
Images are display versions, not guaranteed archival originals. This library
does not provide account authorization or make link-shared albums private.

Protocol reference:
https://github.com/vikas5914/google-photos-album-image-url-fetch
