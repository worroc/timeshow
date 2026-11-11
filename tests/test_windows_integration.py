"""Use real Windows key protection and pipes, with synthetic data only."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.fernet import Fernet

from timeshow.photos import PhotosError
from timeshow.security import DPAPIProtector, Vault


@unittest.skipUnless(sys.platform == "win32", "Requires native Windows APIs")
class WindowsIntegrationTests(unittest.TestCase):
    def test_dpapi_vault_reopens_in_an_unattended_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = Vault.open(root / "config", DPAPIProtector(), root / "cache")
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
                [sys.executable, "-c", script, str(root / "config"), str(root / "cache")],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, "Child could not unlock its DPAPI vault")
            key_record = json.loads((root / "config/key.json").read_text())
            self.assertNotEqual(base64.b64decode(key_record["wrapped"]), vault.session_key())

    def test_dpapi_rejects_damaged_protected_data(self):
        protector = DPAPIProtector()
        record = protector.protect(Fernet.generate_key())
        wrapped = bytearray(base64.b64decode(record["wrapped"]))
        wrapped[-1] ^= 1
        with self.assertRaises(PhotosError):
            protector.unlock({"wrapped": base64.b64encode(wrapped).decode()})

    def test_windowed_worker_can_read_and_report_through_pipes(self):
        executable = Path(sys.executable).with_name("pythonw.exe")
        self.assertTrue(executable.is_file(), "The Windows Python installation needs pythonw.exe")
        message = "synthetic worker pipe message"
        script = (
            "import sys; from timeshow.worker_io import read_session_key, report; "
            "sys.stdin = None; sys.stdout = None; "
            "report(read_session_key().decode('utf-8'))"
        )
        result = subprocess.run(
            [str(executable), "-c", script], input=message.encode(),
            capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(result.stdout.decode().strip(), message)
