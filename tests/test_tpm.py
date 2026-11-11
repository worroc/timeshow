"""TPM failure handling is always tested; real hardware validation is opt-in."""

import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from timeshow.photos import PhotosError
from timeshow.security import TPMProtector, Vault


class TPMAdapterTests(unittest.TestCase):
    def test_encrypt_requests_tpm_only_and_decrypt_refuses_null(self):
        with patch("sys.platform", "linux"), patch(
            "timeshow.security.keys.subprocess.run", return_value=SimpleNamespace(stdout=b"synthetic sealed data")
        ) as run:
            protector = TPMProtector()
            record = protector.protect(b"synthetic key")
            self.assertEqual(record, {"wrapped": base64.b64encode(b"synthetic sealed data").decode()})
            encrypt = run.call_args.args[0]
            self.assertIn("--with-key=tpm2", encrypt)
            self.assertIn("--user", encrypt)
            self.assertEqual(run.call_args.kwargs["input"], b"synthetic key")
            protector.unlock(record)
            decrypt = run.call_args.args[0]
            self.assertIn("decrypt", decrypt)
            self.assertIn("--refuse-null", decrypt)
            self.assertNotIn("--allow-null", decrypt)
            self.assertEqual(run.call_count, 2)

    def test_failure_never_retries_with_a_software_or_null_key(self):
        failures = [
            FileNotFoundError("synthetic private backend detail"),
            subprocess.TimeoutExpired("systemd-creds", 30),
            subprocess.CalledProcessError(1, "systemd-creds", stderr=b"synthetic private backend detail"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch("sys.platform", "linux"), patch(
                "timeshow.security.keys.subprocess.run", side_effect=failure
            ) as run:
                with self.assertRaises(PhotosError) as caught:
                    TPMProtector().protect(Fernet.generate_key())
                self.assertNotIn("synthetic private backend detail", str(caught.exception))
                self.assertEqual(run.call_count, 1)

    def test_user_scope_incompatibility_has_a_specific_error(self):
        failure = subprocess.CalledProcessError(
            1, "systemd-creds", stderr=b"Selected key not available in --uid= scoped mode, refusing."
        )
        with patch("sys.platform", "linux"), patch(
            "timeshow.security.keys.subprocess.run", side_effect=failure
        ) as run:
            with self.assertRaisesRegex(PhotosError, "per-user credentials"):
                TPMProtector().protect(Fernet.generate_key())
            self.assertEqual(run.call_count, 1)

    def test_failed_setup_never_saves_a_key_record(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "linux"), patch(
            "timeshow.security.keys.subprocess.run", side_effect=FileNotFoundError()
        ):
            directory = Path(temporary) / "vault"
            with self.assertRaises(PhotosError):
                Vault.open(directory, TPMProtector())
            self.assertFalse((directory / "key.json").exists())

    def test_empty_tool_output_never_becomes_a_saved_key(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "linux"), patch(
            "timeshow.security.keys.subprocess.run", return_value=SimpleNamespace(stdout=b"\n")
        ):
            directory = Path(temporary) / "vault"
            with self.assertRaisesRegex(PhotosError, "no credential data"):
                Vault.open(directory, TPMProtector())
            self.assertFalse((directory / "key.json").exists())

    def test_failed_unlock_does_not_replace_the_key_or_state(self):
        with tempfile.TemporaryDirectory() as temporary, patch("sys.platform", "linux"):
            directory = Path(temporary) / "vault"
            with patch.object(TPMProtector, "protect", return_value={"wrapped": "c3ludGhldGlj"}):
                vault = Vault.open(directory, TPMProtector())
            vault.save_state(vault.load_state())
            original_key = (directory / "key.json").read_bytes()
            original_state = (directory / "state.enc").read_bytes()
            with patch("timeshow.security.keys.subprocess.run", side_effect=FileNotFoundError()):
                with self.assertRaises(PhotosError):
                    Vault.open(directory, TPMProtector())
            self.assertEqual((directory / "key.json").read_bytes(), original_key)
            self.assertEqual((directory / "state.enc").read_bytes(), original_state)

    def test_other_platforms_never_launch_systemd(self):
        with patch("sys.platform", "win32"), patch("timeshow.security.keys.subprocess.run") as run:
            with self.assertRaises(PhotosError):
                TPMProtector().protect(Fernet.generate_key())
            run.assert_not_called()


@unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("TIMESHOW_TEST_TPM2") == "1",
                     "Opt in on a Linux machine with TPM2 hardware")
class TPMHardwareTests(unittest.TestCase):
    def test_vault_reopens_in_an_unattended_child(self):
        self.assertTrue(Path("/dev/tpmrm0").exists() or Path("/dev/tpm0").exists(),
                        "Real TPM2 device access is required")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            vault = Vault.open(directory / "vault", TPMProtector(), directory / "cache")
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
                [sys.executable, "-c", script, str(directory / "vault"), str(directory / "cache")],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=45,
            )
            self.assertEqual(result.returncode, 0, "Unattended TPM vault reopening failed")
