"""Use isolated Linux settings and services, never the user's desktop or keyring."""

import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import secretstorage
except ImportError:
    secretstorage = None

from timeshow.desktop import Desktop
from timeshow.scheduling import Scheduler
from timeshow.security import KeyringProtector, Vault


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux")
class LinuxIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gsettings"), "Requires gsettings and GNOME schemas")
    def test_gnome_wallpaper_settings_use_an_isolated_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"XDG_CONFIG_HOME": str(root / "config"),
                           "GSETTINGS_BACKEND": "keyfile", "XDG_CURRENT_DESKTOP": "GNOME"}
            with patch.dict(os.environ, environment):
                schemas = subprocess.run(["gsettings", "list-schemas"], capture_output=True,
                                         text=True, check=True, timeout=10).stdout.splitlines()
                if "org.gnome.desktop.background" not in schemas:
                    self.skipTest("Install gsettings-desktop-schemas")
                image = root / "synthetic wallpaper.jpg"
                image.write_bytes(b"Synthetic path; gsettings does not decode this file")
                Desktop().set_wallpaper(image)
                keys = subprocess.run(
                    ["gsettings", "list-keys", "org.gnome.desktop.background"],
                    capture_output=True, text=True, check=True, timeout=10,
                ).stdout.splitlines()
                for key in {"picture-uri", "picture-uri-dark"}.intersection(keys):
                    result = subprocess.run(
                        ["gsettings", "get", "org.gnome.desktop.background", key],
                        capture_output=True, text=True, check=True, timeout=10,
                    )
                    self.assertEqual(result.stdout.strip().strip("'"), image.as_uri())

    @unittest.skipUnless(os.environ.get("TIMESHOW_TEST_SYSTEMD_VERIFY") == "1",
                         "Opt in to systemd unit verification outside restricted sandboxes")
    def test_generated_user_units_pass_systemd_verification(self):
        self.assertIsNotNone(shutil.which("systemd-analyze"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            environment = {"XDG_CONFIG_HOME": str(root / "config"),
                           "XDG_RUNTIME_DIR": str(runtime)}
            with patch.dict(os.environ, environment), patch.object(Scheduler, "_run"):
                Scheduler(root / "config/timeshow").enable(300)
                units = root / "config/systemd/user"
                result = subprocess.run(
                    ["systemd-analyze", "--user", "verify", "--man=no",
                     str(units / "timeshow.service"), str(units / "timeshow.timer")],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get("TIMESHOW_TEST_SECRET_SERVICE") == "1",
                         "Run explicitly inside dbus-run-session with gnome-keyring installed")
    def test_unattended_child_unlocks_an_isolated_system_keyring(self):
        self.assertIsNotNone(secretstorage, "Install the Linux keyring dependencies")
        self.assertIsNotNone(shutil.which("gnome-keyring-daemon"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = root / "control"
            control.mkdir(mode=0o700)
            environment = {"XDG_DATA_HOME": str(root / "data"),
                           "XDG_CONFIG_HOME": str(root / "config"),
                           "KEYRING_PROPERTY_PREFERRED_COLLECTION": "/org/freedesktop/secrets/collection/login"}
            with patch.dict(os.environ, environment):
                daemon = subprocess.Popen(
                    ["gnome-keyring-daemon", "--foreground", "--unlock",
                     "--components=secrets", "--control-directory", str(control)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                try:
                    daemon.stdin.write(b"synthetic integration password\n")
                    daemon.stdin.close()
                    self._wait_for_unlocked_keyring(daemon)
                    vault = Vault.open(root / "vault", KeyringProtector(), root / "cache")
                    state = vault.load_state()
                    state["seen"] = ["synthetic-shown-image"]
                    vault.save_state(state)
                    script = (
                        "from pathlib import Path; import sys; "
                        "from timeshow.worker import open_vault; "
                        "vault = open_vault(Path(sys.argv[1]), Path(sys.argv[2])); "
                        "assert vault.load_state()['seen'] == ['synthetic-shown-image']"
                    )
                    result = subprocess.run(
                        [sys.executable, "-c", script, str(root / "vault"), str(root / "cache")],
                        stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, "Child could not unlock the system keyring vault")
                    record = json.loads((root / "vault/key.json").read_text())
                    self.assertEqual(set(record), {"version", "mode", "account"})
                finally:
                    daemon.terminate()
                    try:
                        daemon.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        daemon.kill()
                        daemon.wait(timeout=5)
                    daemon.stdout.close()

    def _wait_for_unlocked_keyring(self, daemon):
        # Foreground GNOME keyring closes stdout after initialization. Querying
        # D-Bus earlier can auto-start a different, locked daemon on the bus.
        deadline = time.monotonic() + 5
        with selectors.DefaultSelector() as selector:
            selector.register(daemon.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if selector.select(timeout=max(0, deadline - time.monotonic())):
                    if not daemon.stdout.read1(4096):
                        break
            else:
                self.fail("The isolated GNOME keyring did not finish initialization")
        self.assertIsNone(daemon.poll(), "The isolated GNOME keyring exited during startup")
        connection = secretstorage.dbus_init()
        try:
            collection = secretstorage.Collection(connection, "/org/freedesktop/secrets/collection/login")
            self.assertFalse(collection.is_locked(), "The isolated login keyring is locked")
        finally:
            connection.close()
