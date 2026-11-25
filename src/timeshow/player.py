"""Persistent rotation logic, independent of Qt and platform implementation."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import secrets
import time

from PIL import Image, ImageOps, UnidentifiedImageError

from .desktop import Desktop
from ._local import _LocalPhotos
from ._rotation import _migrate_order, _next_cycle, _reconcile_order
from .http import validate_url
from .photos import ImageCandidate, PhotosClient, PhotosError
from .security import Vault
from .storage import private_directory, write_private


class CollectionExhausted(PhotosError):
    """There are no eligible photos to display."""


@dataclass(frozen=True)
class DisplayedPhoto:
    media_id: str
    body: bytes
    path: Path
    width: int
    height: int
    capture_time_ms: int | None
    album: str


class Player:
    def __init__(self, vault: Vault, desktop: Desktop, runtime: Path,
                 source: PhotosClient | None = None):
        self.vault = vault
        self.desktop = desktop
        self.runtime = runtime
        self.source = source if source is not None else PhotosClient()
        self._local_source = _LocalPhotos()
        self.state = vault.load_state()
        _migrate_order(self.state, set(self.eligible()))
        self.current: DisplayedPhoto | None = None
        self.screen_size = (1920, 1080)
        private_directory(runtime)

    def save(self) -> None:
        self.state["show_order"], self.state["cursor"] = _reconcile_order(self.state, set(self.eligible()))
        self.vault.save_state(self.state)

    def reload(self) -> None:
        self.state = self.vault.load_state()
        _migrate_order(self.state, set(self.eligible()))

    def restore_current(self) -> DisplayedPhoto | None:
        entry = self.state.get("current")
        self.current = None
        if not entry:
            return None
        key = entry["media_id"]
        body = self.vault.get_image(key)
        if body is None:
            return None
        item = self.state["images"].get(key, entry.get("photo"))
        if item is None:
            return None
        labels = [a["label"] for a in self.state["albums"] if a["id"] in item["album_ids"]]
        self.current = DisplayedPhoto(key, body, Path(entry["path"]), item["width"], item["height"],
                                      item["capture_time_ms"], ", ".join(labels) or entry.get("album", ""))
        return self.current

    def add_album(self, label: str, url: str) -> None:
        validate_url(url, album=True)
        if any(album.get("url") == url for album in self.state["albums"]):
            raise PhotosError("That album is already configured.")
        self.state["albums"].append({"id": secrets.token_hex(8), "label": label.strip() or "Album",
                                     "url": url, "enabled": True})
        self.save()

    def add_folder(self, label: str, path: Path) -> None:
        try:
            directory = Path(path).expanduser().resolve(strict=True)
            if not directory.is_dir():
                raise OSError
        except (OSError, ValueError, RuntimeError):
            raise PhotosError("Choose an existing, readable photo folder.") from None
        if any(album.get("path") == str(directory) for album in self.state["albums"]):
            raise PhotosError("That folder is already configured.")
        self.state["albums"].append({"id": secrets.token_hex(8), "label": label.strip() or directory.name,
                                     "kind": "folder", "path": str(directory), "enabled": True})
        self.save()

    def remove_album(self, album_id: str) -> None:
        self.state["albums"] = [a for a in self.state["albums"] if a["id"] != album_id]
        for image in self.state["images"].values():
            image["album_ids"] = [key for key in image["album_ids"] if key != album_id]
        self.save()

    def enable_album(self, album_id: str, enabled: bool) -> None:
        for album in self.state["albums"]:
            if album["id"] == album_id:
                album["enabled"] = enabled
        self.save()

    def refresh(self) -> int:
        # Build a complete replacement before saving, so failure never publishes
        # a partial listing or discards an earlier successful album listing.
        updated = deepcopy(self.state)
        current = updated.get("current")
        if current and current["media_id"] in updated["images"]:
            current["photo"] = deepcopy(updated["images"][current["media_id"]])
            current["album"] = ", ".join(album["label"] for album in updated["albums"]
                                          if album["id"] in current["photo"]["album_ids"])
        enabled = [album for album in updated["albums"] if album["enabled"]]
        if not enabled:
            raise PhotosError("Add and enable at least one album or folder first.")
        updated["images"] = {}
        for album in enabled:
            local = album.get("kind") == "folder"
            images = (self._local_source.list_images(album["path"]) if local
                      else self.source.list_images(album["url"]))
            for image in images:
                previous = updated["images"].get(image.media_id, {})
                memberships = set(previous.get("album_ids", [])) | {album["id"]}
                updated["images"][image.media_id] = {**asdict(image), "album_ids": sorted(memberships),
                                                      "source": "folder" if local else "google"}
        updated["show_order"], updated["cursor"] = _reconcile_order(
            updated, set(self._eligible(updated)), reshuffle=True,
        )
        self.vault.save_state(updated)
        self.state = updated
        return len(self.eligible())

    def eligible(self) -> list[str]:
        return self._eligible(self.state)

    @staticmethod
    def _eligible(state: dict) -> list[str]:
        enabled = {album["id"] for album in state["albums"] if album["enabled"]}
        excluded = set(state["excluded"])
        after = state.get("after", "")
        before = state.get("before", "")
        result = []
        for key, image in state["images"].items():
            if key in excluded or not enabled.intersection(image["album_ids"]):
                continue
            timestamp = image["capture_time_ms"]
            if after or before:
                if timestamp is None:
                    continue
                day = datetime.fromtimestamp(timestamp / 1000).date().isoformat()
                if (after and day < after) or (before and day > before):
                    continue
            result.append(key)
        return result

    def remaining(self) -> int:
        eligible = set(self.eligible())
        order = self.state["show_order"]
        ahead = sum(key in eligible for key in order[self.state["cursor"] + 1:])
        return ahead + len(eligible - set(order))

    def configure(self, interval: int, fit: str, after: str, before: str, cache_limit: int) -> None:
        if interval < 10 or fit not in {"fill", "fit"} or not 1 <= cache_limit <= 500:
            raise PhotosError("Use an interval of at least 10 seconds and a cache limit of 1–500.")
        try:
            for value in [after, before]:
                if value:
                    date.fromisoformat(value)
        except ValueError:
            raise PhotosError("Dates must use YYYY-MM-DD.") from None
        if after and before and after > before:
            raise PhotosError("The start date must be before the end date.")
        # Keep accepting the old argument, but retention is now always one image.
        self.state.update(interval=interval, fit=fit, after=after, before=before, cache_limit=1)
        self.save()

    def next(self) -> DisplayedPhoto:
        eligible = set(self.eligible())
        if not eligible:
            raise CollectionExhausted("No eligible photos are available. Check sources and filters, then refresh the photo list.")
        order, cursor = _reconcile_order(self.state, eligible)
        if len(eligible) == 1:
            index = max(0, cursor)
            return self._show(order[index], index, order)
        last_shown = self.state.get("current", {}).get("media_id")
        index = cursor + 1
        while index < len(order) and order[index] == last_shown:
            index += 1
        if index == len(order):
            order, cursor = _next_cycle(order, eligible, last_shown)
            index = cursor + 1
        return self._show(order[index], index, order)

    def previous(self) -> DisplayedPhoto:
        order, cursor = _reconcile_order(self.state, set(self.eligible()))
        current_id = self.state.get("current", {}).get("media_id")
        index = cursor - 1
        if cursor >= 0 and current_id is not None and order[cursor] != current_id:
            index = cursor
        if index < 0:
            raise PhotosError("There is no previous photo.")
        return self._show(order[index], index, order)

    def _candidate(self, media_id: str) -> ImageCandidate:
        item = self.state["images"][media_id]
        fields = {key: item[key] for key in ["media_id", "url", "width", "height", "capture_time_ms"]}
        return ImageCandidate(**fields)

    def _body(self, media_id: str) -> bytes:
        body = self.vault.get_image(media_id)
        if body is None:
            source = (self._local_source if self.state["images"][media_id].get("source") == "folder"
                      else self.source)
            body = source.pull_image(self._candidate(media_id)).body
        return body

    def _wallpaper(self, body: bytes) -> bytes:
        try:
            with Image.open(BytesIO(body)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                if self.state["fit"] == "fill":
                    image = ImageOps.fit(image, self.screen_size, method=Image.Resampling.LANCZOS)
                else:
                    image.thumbnail(self.screen_size, Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", self.screen_size, (20, 24, 30))
                    canvas.paste(image, ((canvas.width-image.width)//2, (canvas.height-image.height)//2))
                    image = canvas
                stream = BytesIO()
                image.save(stream, format="JPEG", quality=92)
                return stream.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise PhotosError("The image could not be decoded for wallpaper display.") from None

    def _show(self, media_id: str, cursor: int, order: list[str]) -> DisplayedPhoto:
        body = self._body(media_id)
        path = self.runtime / f"wallpaper-{secrets.token_hex(8)}.jpg"
        write_private(path, self._wallpaper(body))
        try:
            self.desktop.set_wallpaper(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        item = self.state["images"][media_id]
        labels = [a["label"] for a in self.state["albums"] if a["id"] in item["album_ids"]]
        self.current = DisplayedPhoto(media_id, body, path, item["width"], item["height"],
                                      item["capture_time_ms"], ", ".join(labels))
        try:
            # Store the new original only after the desktop accepts the switch.
            self.vault.put_image(media_id, body)
            self.state["show_order"] = order
            self.state["cursor"] = cursor
            self.state["current"] = {"media_id": media_id, "path": str(path),
                                      "photo": deepcopy(item), "album": self.current.album}
            self.state["last_switch"] = time.time()
            self.save()
        finally:
            # Once a switch succeeds, remove old downloads and display copies
            # even if saving history fails. Unlink directly; never use the trash.
            for old in self.runtime.glob("wallpaper-*.jpg"):
                if old != path:
                    old.unlink(missing_ok=True)
            self._prune_cache()
        return self.current

    def _prune_cache(self) -> None:
        keep = self.vault.cache_path(self.current.media_id) if self.current else None
        for pattern in ["*.image", "*.enc"]:
            for path in self.vault.cache_directory.glob(pattern):
                if path != keep:
                    path.unlink(missing_ok=True)

    def exclude_current(self) -> None:
        if not self.current:
            raise PhotosError("No photo is currently displayed.")
        excluded = set(self.state["excluded"])
        excluded.add(self.current.media_id)
        self.state["excluded"] = sorted(excluded)
        self.save()
        self.vault.delete_image(self.current.media_id)

    def reset_history(self) -> None:
        order, cursor = _reconcile_order(self.state, set(self.eligible()))
        self.state["show_order"], self.state["cursor"] = _next_cycle(
            order[:cursor + 1], set(self.eligible()), self.state.get("current", {}).get("media_id"),
        )
        self.save()

    def clear_exclusions(self) -> None:
        self.state["excluded"] = []
        self.save()

    def open_current_album(self) -> None:
        if not self.current:
            raise PhotosError("No photo is currently displayed.")
        image = self.state["images"].get(self.current.media_id, self.state.get("current", {}).get("photo"))
        if image is None:
            raise PhotosError("The photo source is no longer configured.")
        for album in self.state["albums"]:
            if album["id"] in image["album_ids"]:
                if album.get("kind") == "folder":
                    self.desktop.open_folder(Path(album["path"]))
                else:
                    self.desktop.open_album(album["url"])
                return
        raise PhotosError("The photo source is no longer configured.")

    def export_current(self, path: Path) -> None:
        if not self.current:
            raise PhotosError("No photo is currently displayed.")
        write_private(path, self.current.body)
