"""Uninstall uses temporary user directories and a fake credential store."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from timeshow import _uninstall
from timeshow.photos import PhotosError


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux uninstall")
class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config/timeshow"
        self.data = self.root / "data/timeshow"
        self.runtime = self.root / "runtime/timeshow"
        for directory in (self.config, self.data, self.runtime):
            directory.mkdir(parents=True)
            (directory / "synthetic-data").write_text("synthetic")
        self.environment = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_uninstall(self, *arguments, answer="n"):
        with patch.object(_uninstall, "_stop_processes"), patch.object(
            _uninstall.Scheduler, "_run"
        ), patch.object(os, "getuid", return_value=1000), patch(
            "builtins.input", return_value=answer
        ), patch("builtins.print"):
            return _uninstall.main(list(arguments))

    def test_default_keeps_data_and_removes_only_integration(self):
        owned = self.root / "data/applications/timeshow.desktop"
        unrelated = owned.with_name("other.desktop")
        owned.parent.mkdir(parents=True)
        owned.write_text("synthetic launcher")
        unrelated.write_text("keep")
        settings = self.config / "settings.json"
        settings.write_text(json.dumps({"running": True, "interval": 120}))
        self.assertEqual(self.run_uninstall(), 0)
        self.assertEqual(json.loads(settings.read_text()), {"running": False, "interval": 120})
        self.assertFalse(owned.exists())
        self.assertTrue(unrelated.exists())
        for directory in (self.config, self.data, self.runtime):
            self.assertTrue((directory / "synthetic-data").exists())

    def test_yes_deletes_exact_key_and_all_app_data(self):
        (self.config / "key.json").write_text(json.dumps({"mode": "keyring", "account": "synthetic-account"}))
        backend = Mock()
        backend.get_password.return_value = "synthetic-key"
        unrelated = self.root / "data/other-app"
        unrelated.mkdir()
        with patch.object(_uninstall.KeyringProtector, "_backend", return_value=backend):
            self.assertEqual(self.run_uninstall("--yes"), 0)
        backend.delete_password.assert_called_once_with("Timeshow", "synthetic-account")
        for directory in (self.config, self.data, self.runtime):
            self.assertFalse(directory.exists())
        self.assertTrue(unrelated.exists())

    def test_failed_key_removal_keeps_data_for_retry(self):
        record = self.config / "key.json"
        record.write_text(json.dumps({"mode": "keyring", "account": "synthetic-account"}))
        with patch.object(_uninstall.KeyringProtector, "_backend", side_effect=PhotosError("locked")):
            self.assertEqual(self.run_uninstall("--yes"), 1)
        self.assertTrue(record.exists())
        self.assertTrue((self.data / "synthetic-data").exists())

    def test_repeated_removal_with_missing_files_succeeds(self):
        self.assertEqual(self.run_uninstall("--yes"), 0)
        self.assertEqual(self.run_uninstall("--yes"), 0)

    def test_data_symlink_does_not_delete_target(self):
        outside = self.root / "unrelated"
        outside.mkdir()
        marker = outside / "keep"
        marker.write_text("keep")
        (self.config / "outside").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_uninstall("--yes"), 0)
        self.assertTrue(marker.exists())
