"""Encrypt links and identities; keep preferences and current image readable."""

import hashlib
import json
from pathlib import Path
from threading import RLock

from cryptography.fernet import Fernet, InvalidToken

from .keys import KeyProtector
from ..photos import PhotosError
from ..settings import PUBLIC_FIELDS, public_settings, publish_settings
from ..storage import private_directory, write_json, write_private


class Vault:
    def __init__(self, directory: Path, key: bytes, cache_directory: Path | None = None):
        self.directory = directory
        self.cache_directory = cache_directory if cache_directory is not None else directory / "cache"
        self._key = key
        self._cipher = Fernet(key)
        self._lock = RLock()
        private_directory(directory)
        private_directory(self.cache_directory)

    @staticmethod
    def mode(directory: Path) -> str | None:
        key_path = directory / "key.json"
        if not key_path.exists():
            if (directory / "state.enc").exists():
                raise PhotosError("The existing vault key file is missing. Refusing to replace it.")
            return None
        try:
            return json.loads(key_path.read_text())["mode"]
        except (ValueError, KeyError, OSError):
            raise PhotosError("The vault key file cannot be read.") from None

    @classmethod
    def open(cls, directory: Path, protector: KeyProtector,
             cache_directory: Path | None = None) -> "Vault":
        mode = cls.mode(directory)
        if mode is None:
            key = Fernet.generate_key()
            wrapped = protector.protect(key)
            private_directory(directory)
            write_json(directory / "key.json", {"version": 1, "mode": protector.mode, **wrapped})
        else:
            if mode != protector.mode:
                raise PhotosError("Use the protection method selected when this vault was created.")
            try:
                key = protector.unlock(json.loads((directory / "key.json").read_text()))
            except (ValueError, KeyError, TypeError):
                raise PhotosError("The vault key file is damaged.") from None
        try:
            vault = cls(directory, key, cache_directory)
            vault.load_state()
            return vault
        except (ValueError, TypeError):
            raise PhotosError("The vault key is invalid.") from None

    def load_state(self) -> dict:
        path = self.directory / "state.enc"
        if not path.exists():
            return {"version": 1, "albums": [], "images": {}, "seen": [], "excluded": [],
                    "history": [], "cursor": -1, "interval": 300, "fit": "fill",
                    **public_settings(self.directory)}
        with self._lock:
            try:
                state = json.loads(self._cipher.decrypt(path.read_bytes()))
                if not isinstance(state, dict) or state.get("version") != 1:
                    raise ValueError
                # Old vaults may also contain preferences. Public settings take
                # precedence so users can edit ordinary configuration directly.
                if (self.directory / "settings.json").exists():
                    state.update(public_settings(self.directory))
                state["cache_limit"] = 1
                return state
            except (InvalidToken, ValueError):
                raise PhotosError("The encrypted state is damaged or cannot be unlocked.") from None

    def save_state(self, state: dict) -> None:
        with self._lock:
            private = {key: value for key, value in state.items()
                       if key not in PUBLIC_FIELDS and key != "cache_limit"}
            write_private(self.directory / "state.enc", self._cipher.encrypt(json.dumps(private).encode()))
            publish_settings(state, self.directory)

    def cache_path(self, media_id: str) -> Path:
        return self.cache_directory / (hashlib.sha256(media_id.encode()).hexdigest() + ".image")

    def session_key(self) -> bytes:
        """Pass an unlocked key to a child worker through stdin, never arguments or files."""
        return self._key

    def put_image(self, media_id: str, body: bytes) -> None:
        with self._lock:
            write_private(self.cache_path(media_id), body)

    def get_image(self, media_id: str) -> bytes | None:
        with self._lock:
            path = self.cache_path(media_id)
            if path.exists():
                return path.read_bytes()
            legacy = path.with_suffix(".enc")
            if not legacy.exists():
                return None
            try:
                # Read old encrypted cache entries until the next successful
                # switch removes them. Never bulk-decrypt historical photos.
                return self._cipher.decrypt(legacy.read_bytes())
            except InvalidToken:
                raise PhotosError("A cached image is damaged. Delete its local copy and download it again.") from None

    def delete_image(self, media_id: str) -> None:
        with self._lock:
            self.cache_path(media_id).unlink(missing_ok=True)
            self.cache_path(media_id).with_suffix(".enc").unlink(missing_ok=True)
