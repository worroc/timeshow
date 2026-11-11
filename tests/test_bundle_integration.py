"""Exercise the actual bundled worker with a temporary vault and no wallpaper changes."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.fernet import Fernet

from timeshow.security import PasswordProtector, Vault


@unittest.skipUnless(os.environ.get("TIMESHOW_TEST_BUNDLE"), "Build and select a bundle first")
class BundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.executable = Path(os.environ["TIMESHOW_TEST_BUNDLE"]).resolve()
        self.assertTrue(self.executable.is_file(), "The selected bundle executable is missing")
        config = root / "config" / ("Timeshow" if sys.platform == "win32" else "timeshow")
        self.vault = Vault.open(config, PasswordProtector("synthetic bundle password"), root / "cache")
        self.vault.save_state(self.vault.load_state())
        self.environment = dict(os.environ)
        self.environment.update(
            XDG_CONFIG_HOME=str(root / "config"), APPDATA=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"), LOCALAPPDATA=str(root / "data"),
            XDG_RUNTIME_DIR=str(root / "runtime"),
        )

    def run_worker(self, key):
        return subprocess.run(
            [str(self.executable), "--mode", "worker", "--action", "tick", "--session-key"],
            input=key, capture_output=True, env=self.environment, timeout=30,
        )

    def test_paused_worker_reads_the_key_and_exits(self):
        result = self.run_worker(self.vault.session_key())
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        self.assertEqual(self.vault.load_state()["seen"], [])

    def test_wrong_key_reports_an_error_through_the_output_pipe(self):
        result = self.run_worker(Fernet.generate_key())
        self.assertEqual(result.returncode, 1)
        self.assertIn("encrypted state", result.stdout.decode(errors="replace"))
