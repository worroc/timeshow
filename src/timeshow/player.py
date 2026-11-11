"""Persistent rotation logic, independent of Qt and platform implementation."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
import secrets
import time

from PIL import Image, ImageOps, UnidentifiedImageError

from .desktop import Desktop
from .http import validate_url
from .photos import ImageCandidate, PhotosClient, PhotosError
from .security import Vault
from .storage import private_directory, write_private


class CollectionExhausted(PhotosError):
    """All eligible photos have already appeared; rotation must pause."""


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
        self.state = vault.load_state()
        self.current: DisplayedPhoto | None = None
        self.screen_size = (1920, 1080)
        private_directory(runtime)

    def save(self) -> None:
        self.vault.save_state(self.state)

    def reload(self) -> None:
        self.state = self.vault.load_state()

    def restore_current(self) -> DisplayedPhoto | None:
        entry = self.state.get("current")
        self.current = None
        if not entry or entry["media_id"] not in self.state["images"]:
            return None
        key = entry["media_id"]
        body = self.vault.get_image(key)
        if body is None:
            return None
        item = self.state["images"][key]
        labels = [a["label"] for a in self.state["albums"] if a["id"] in item["album_ids"]]
        self.current = DisplayedPhoto(key, body, Path(entry["path"]), item["width"], item["height"],
                                      item["capture_time_ms"], ", ".join(labels))
        return self.current

    def add_album(self, label: str, url: str) -> None:
        validate_url(url, album=True)
        if any(album["url"] == url for album in self.state["albums"]):
            raise PhotosError("That album is already configured.")
        self.state["albums"].append({"id": secrets.token_hex(8), "label": label.strip() or "Album",
                                     "url": url, "enabled": True})
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
        enabled = [album for album in updated["albums"] if album["enabled"]]
        if not enabled:
            raise PhotosError("Add and enable at least one album first.")
        for album in enabled:
            images = self.source.list_images(album["url"])
            for record in updated["images"].values():
                record["album_ids"] = [key for key in record["album_ids"] if key != album["id"]]
            for image in images:
                previous = updated["images"].get(image.media_id, {})
                memberships = set(previous.get("album_ids", [])) | {album["id"]}
                updated["images"][image.media_id] = {**asdict(image), "album_ids": sorted(memberships)}
        self.vault.save_state(updated)
        self.state = updated
        return len(self.eligible())

    def eligible(self) -> list[str]:
        enabled = {album["id"] for album in self.state["albums"] if album["enabled"]}
        excluded = set(self.state["excluded"])
        after = self.state.get("after", "")
        before = self.state.get("before", "")
        result = []
        for key, image in self.state["images"].items():
            if key in excluded or not enabled.intersection(image["album_ids"]):
                continue
            timestamp = image["capture_time_ms"]
            if after or before:
                if timestamp is None:
                    continue
                day = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()
                if (after and day < after) or (before and day > before):
                    continue
            result.append(key)
        return result

    def remaining(self) -> int:
        return len(set(self.eligible()) - set(self.state["seen"]))

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
        history = self.state["history"]
        cursor = self.state["cursor"]
        excluded = set(self.state["excluded"])
        for index in range(cursor + 1, len(history)):
            if history[index] not in excluded:
                return self._show(history[index], cursor=index)
        unseen = list(set(self.eligible()) - set(self.state["seen"]))
        if not unseen:
            raise CollectionExhausted("Every eligible photo has been shown. Add photos or reset history to start again.")
        return self._show(secrets.choice(unseen))

    def previous(self) -> DisplayedPhoto:
        excluded = set(self.state["excluded"])
        for index in range(self.state["cursor"] - 1, -1, -1):
            key = self.state["history"][index]
            if key not in excluded:
                return self._show(key, cursor=index)
        raise PhotosError("There is no previous photo.")

    def _candidate(self, media_id: str) -> ImageCandidate:
        item = self.state["images"][media_id]
        fields = {key: item[key] for key in ["media_id", "url", "width", "height", "capture_time_ms"]}
        return ImageCandidate(**fields)

    def _body(self, media_id: str) -> bytes:
        body = self.vault.get_image(media_id)
        if body is None:
            body = self.source.pull_image(self._candidate(media_id)).body
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

    def _show(self, media_id: str, cursor: int | None = None) -> DisplayedPhoto:
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
            if cursor is None:
                self.state["history"].append(media_id)
                cursor = len(self.state["history"]) - 1
            self.state["cursor"] = cursor
            self.state["seen"] = sorted(set(self.state["seen"]) | {media_id})
            self.state["current"] = {"media_id": media_id, "path": str(path)}
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
        self.state.update(seen=[], history=[], cursor=-1)
        self.save()

    def clear_exclusions(self) -> None:
        self.state["excluded"] = []
        self.save()

    def open_current_album(self) -> None:
        if not self.current:
            raise PhotosError("No photo is currently displayed.")
        image = self.state["images"][self.current.media_id]
        for album in self.state["albums"]:
            if album["id"] in image["album_ids"]:
                self.desktop.open_album(album["url"])
                return
        raise PhotosError("The source album is no longer configured.")

    def export_current(self, path: Path) -> None:
        if not self.current:
            raise PhotosError("No photo is currently displayed.")
        write_private(path, self.current.body)
