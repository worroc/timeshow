"""Exercise the actual bundled worker with a temporary vault and no wallpaper changes."""

import os
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from cryptography.fernet import Fernet
from PIL import Image

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

    def run_worker(self, key, action="tick"):
        return subprocess.run(
            [str(self.executable), "--mode", "worker", "--action", action, "--session-key"],
            input=key, capture_output=True, env=self.environment, timeout=30,
        )

    def test_paused_worker_reads_the_key_and_exits(self):
        result = self.run_worker(self.vault.session_key())
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        self.assertEqual(self.vault.load_state()["show_order"], [])
        self.assertEqual(self.vault.load_state()["cursor"], -1)

    def test_wrong_key_reports_an_error_through_the_output_pipe(self):
        result = self.run_worker(Fernet.generate_key())
        self.assertEqual(result.returncode, 1)
        self.assertIn("encrypted state", result.stdout.decode(errors="replace"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux scheduler environment")
    def test_start_restores_system_library_path_without_changing_desktop(self):
        root = self.vault.directory.parent / "synthetic-start"
        trace = self._start_commands(root)
        self._start_vault(root)
        result = self.run_worker(self.vault.session_key(), action="resume")
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        updated = self.vault.load_state()
        self.assertTrue(updated["running"])
        self.assertEqual(updated["cursor"], 0)
        self.assertEqual(updated["current"]["media_id"], "synthetic-image")
        self.assertIn("--user restart timeshow.timer", trace.read_text().splitlines())

    def _start_commands(self, root):
        self.environment["XDG_CONFIG_HOME"] = str(root / "config")
        self.environment["XDG_CURRENT_DESKTOP"] = "GNOME"
        self.environment.pop("LD_LIBRARY_PATH", None)
        self.environment.pop("LD_LIBRARY_PATH_ORIG", None)
        commands = root / "bin"
        commands.mkdir(parents=True)
        scheduler = commands / "systemctl"
        scheduler.write_text(
            '#!/bin/sh\n'
            'if [ -n "${LD_LIBRARY_PATH-}" ]; then exit 97; fi\n'
            'printf "%s\\n" "$*" >> "$TIMESHOW_TEST_SCHEDULER_TRACE"\n'
        )
        scheduler.chmod(0o700)
        desktop = commands / "gsettings"
        desktop.write_text('#!/bin/sh\nif [ "$1" = "list-keys" ]; then printf "picture-uri\\n"; fi\nexit 0\n')
        desktop.chmod(0o700)
        trace = root / "scheduler-calls"
        self.environment["TIMESHOW_TEST_SCHEDULER_TRACE"] = str(trace)
        self.environment["PATH"] = str(commands) + os.pathsep + os.environ["PATH"]
        return trace

    def _start_vault(self, root):
        protector = Mock(mode="keyring")
        protector.protect.return_value = {"account": "synthetic-account"}
        cache = Path(self.environment["XDG_DATA_HOME"]) / "timeshow/cache"
        self.vault = Vault.open(root / "config/timeshow", protector, cache)
        body = BytesIO()
        Image.new("RGB", (32, 24), (60, 110, 150)).save(body, format="JPEG")
        self.vault.put_image("synthetic-image", body.getvalue())
        state = self.vault.load_state()
        state["albums"] = [{"id": "synthetic-album", "label": "Synthetic album", "enabled": True,
                            "url": "https://photos.google.com/share/synthetic?key=synthetic"}]
        state["images"] = {"synthetic-image": {"media_id": "synthetic-image",
                            "url": "https://lh3.googleusercontent.com/synthetic", "width": 32,
                            "height": 24, "capture_time_ms": None, "album_ids": ["synthetic-album"]}}
        state.update(show_order=["synthetic-image"], screen_size=[40, 30], interval=60)
        self.vault.save_state(state)
