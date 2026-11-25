"""Automatic setup uses temporary storage and synthetic credential backends."""

from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeshow._setup import _initialize_storage, main
from timeshow.photos import PhotosError
from timeshow.security import DPAPIProtector, KeyringProtector, PasswordProtector, Vault
from timeshow.worker import open_vault


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "config"
        self.cache = self.root / "cache"

    def test_default_storage_reopens_in_worker_and_keeps_history(self):
        for platform, protector in [("win32", DPAPIProtector), ("linux", KeyringProtector)]:
            with self.subTest(platform=platform):
                directory = self.directory / platform
                wrapper = PasswordProtector("synthetic storage password")
                with patch("timeshow._setup.sys") as system, patch.object(
                    protector, "protect", side_effect=wrapper.protect
                ) as protect, patch.object(protector, "unlock", side_effect=wrapper.unlock):
                    system.platform = platform
                    vault = _initialize_storage(directory, self.cache / platform)
                    self.assertEqual(Vault.mode(directory), protector.mode)
                    state = vault.load_state()
                    state["show_order"] = ["synthetic-image"]
                    state["cursor"] = 0
                    vault.save_state(state)
                    key_before = (directory / "key.json").read_bytes()
                    self.assertIsNone(_initialize_storage(directory, self.cache / platform))
                    reopened = open_vault(directory, self.cache / platform)
                    self.assertEqual(reopened.load_state()["show_order"], ["synthetic-image"])
                    self.assertEqual((directory / "key.json").read_bytes(), key_before)
                    protect.assert_called_once()

    def test_existing_password_storage_is_not_changed_or_unlocked(self):
        vault = Vault.open(self.directory, PasswordProtector("synthetic old password"), self.cache)
        vault.save_state(vault.load_state())
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        with patch.object(KeyringProtector, "protect") as protect:
            self.assertIsNone(_initialize_storage(self.directory, self.cache))
        protect.assert_not_called()
        for name, body in before.items():
            self.assertEqual((self.directory / name).read_bytes(), body)

    def test_missing_key_never_replaces_encrypted_data(self):
        self.directory.mkdir()
        state = self.directory / "state.enc"
        state.write_bytes(b"synthetic encrypted data")
        with self.assertRaisesRegex(PhotosError, "Refusing to replace"):
            _initialize_storage(self.directory, self.cache)
        self.assertFalse((self.directory / "key.json").exists())
        self.assertEqual(state.read_bytes(), b"synthetic encrypted data")

    def test_unavailable_secure_storage_fails_without_fallback(self):
        with patch("timeshow._setup.sys") as system, patch.object(
            KeyringProtector, "protect", side_effect=PhotosError("synthetic backend details")
        ), patch.object(PasswordProtector, "protect") as password:
            system.platform = "linux"
            with self.assertRaisesRegex(PhotosError, "desktop password store"):
                _initialize_storage(self.directory, self.cache)
        password.assert_not_called()
        self.assertFalse((self.directory / "key.json").exists())

    def test_installer_failure_returns_error_and_allows_retry(self):
        output = StringIO()
        with patch("timeshow._setup.config_directory", return_value=self.directory), patch(
            "timeshow._setup.app_directory", return_value=self.root / "data"
        ), patch("timeshow._setup.sys") as system, patch.object(
            KeyringProtector, "protect", side_effect=PhotosError("synthetic backend details")
        ):
            system.platform = "linux"
            system.stderr = output
            self.assertEqual(main(), 1)
        self.assertIn("desktop password store", output.getvalue())
        self.assertNotIn("synthetic backend details", output.getvalue())
        with patch.object(KeyringProtector, "protect", side_effect=PasswordProtector(
            "synthetic retry password"
        ).protect), patch("timeshow._setup.sys") as system:
            system.platform = "linux"
            self.assertIsNotNone(_initialize_storage(self.directory, self.cache))
