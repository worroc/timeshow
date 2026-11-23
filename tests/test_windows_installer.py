"""Check installer construction and an opt-in native Windows install/remove cycle."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

if sys.platform == "win32":
    import winreg

from build_windows_installer import main

try:
    from timeshow.security import PasswordProtector, Vault
except ModuleNotFoundError:
    raise unittest.SkipTest("Install the gui extra for Windows installer checks")


def project_version():
    project = Path(__file__).resolve().parents[1]
    return tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]


class WindowsInstallerBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.version_file = self.bundle / "_internal/timeshow/_version.txt"
        self.version_file.parent.mkdir(parents=True)
        self.version_file.write_text(project_version())
        executable = self.bundle / "Timeshow.exe"
        executable.write_bytes(b"synthetic executable")
        executable.chmod(0o755)
        (self.bundle / "LICENSE").write_text("synthetic license")
        (self.bundle / "dependency-licenses").mkdir()

    def test_build_uses_project_version_and_writes_checksum(self):
        output_dir = self.root / "output"
        output = output_dir / f"Timeshow-{project_version()}-Setup.exe"
        with patch("build_windows_installer.sys") as system, patch(
            "build_windows_installer.subprocess.run",
            side_effect=lambda *args, **kwargs: output.write_bytes(b"synthetic installer"),
        ) as compile_installer:
            system.platform = "win32"
            self.assertEqual(main(["--bundle", str(self.bundle), "--output-dir", str(output_dir),
                                   "--iscc", str(self.root / "ISCC.exe")]), 0)
        command = compile_installer.call_args.args[0]
        self.assertIn(f"/DAppVersion={project_version()}", command)
        self.assertIn(f"/DBundleDir={self.bundle.resolve()}", command)
        expected = hashlib.sha256(b"synthetic installer").hexdigest()
        self.assertEqual((output_dir / "SHA256SUMS-windows").read_text(),
                         f"{expected}  {output.name}\n")

    def test_stale_bundle_is_rejected_before_compilation(self):
        self.version_file.write_text("0.0.0")
        with patch("build_windows_installer.sys") as system, patch(
            "build_windows_installer.subprocess.run"
        ) as compile_installer:
            system.platform = "win32"
            with self.assertRaisesRegex(ValueError, "Rebuild"):
                main(["--bundle", str(self.bundle), "--iscc", str(self.root / "ISCC.exe")])
        compile_installer.assert_not_called()


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("TIMESHOW_TEST_INSTALLER"),
                     "Select an installer on a clean Windows test profile")
class WindowsInstallerIntegrationTests(unittest.TestCase):
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Timeshow_is1"

    def _task_exists(self):
        result = subprocess.run(["schtasks.exe", "/Query", "/TN", "Timeshow"],
                                capture_output=True, timeout=30)
        return result.returncode == 0

    def _shortcuts(self):
        script = (
            "@{Programs=[Environment]::GetFolderPath('Programs');"
            "Startup=[Environment]::GetFolderPath('Startup');"
            "Desktop=[Environment]::GetFolderPath('DesktopDirectory')} | ConvertTo-Json -Compress"
        )
        result = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", script],
                                         text=True, timeout=30)
        folders = json.loads(result)
        return [Path(folders["Programs"]) / "Timeshow.lnk",
                Path(folders["Startup"]) / "Timeshow tray.lnk",
                Path(folders["Desktop"]) / "Timeshow.lnk"]

    def _run_installer(self, installer, directory, environment):
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/SP-", f"/DIR={directory}", "/TASKS=desktopicon"],
                       env=environment, check=True, capture_output=True, timeout=180)

    def _run_uninstaller(self, directory, environment):
        subprocess.run([str(directory / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART"], env=environment, check=True, capture_output=True, timeout=90)

    def test_install_reinstall_and_remove_preserve_private_data(self):
        if self._task_exists():
            self.skipTest("An existing Timeshow task must not be changed; use a clean profile")
        shortcuts = self._shortcuts()
        if any(path.exists() for path in shortcuts):
            self.skipTest("Existing Timeshow shortcuts must not be changed; use a clean profile")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.uninstall_key):
                self.skipTest("An existing Timeshow install must not be changed; use a clean profile")
        except FileNotFoundError:
            pass
        with tempfile.TemporaryDirectory() as temporary:
            self._check_installation(Path(temporary), shortcuts)

    def _check_installation(self, root, shortcuts):
        from_environment = dict(os.environ, APPDATA=str(root / "roaming"),
                                LOCALAPPDATA=str(root / "local"))
        directory = root / "installed app"
        installer = Path(os.environ["TIMESHOW_TEST_INSTALLER"]).resolve()
        created_task = False
        try:
            self._run_installer(installer, directory, from_environment)
            self.assertTrue((directory / "Timeshow.exe").is_file())
            self.assertTrue((directory / "dependency-licenses").is_dir())
            self.assertTrue(all(path.is_file() for path in shortcuts))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.uninstall_key) as key:
                self.assertEqual(winreg.QueryValueEx(key, "DisplayVersion")[0], project_version())
            self._check_worker_and_data(root, directory, from_environment)
            self._run_installer(installer, directory, from_environment)
            # Disabled synthetic scheduling must be removed without unlocking the vault.
            subprocess.run(["schtasks.exe", "/Create", "/TN", "Timeshow", "/SC", "MINUTE",
                            "/MO", "1439", "/TR", subprocess.list2cmdline(
                                [str(directory / "Timeshow.exe"), "--mode", "worker"]),
                            "/IT", "/RL", "LIMITED", "/F"],
                           check=True, capture_output=True, timeout=30)
            created_task = True
            subprocess.run(["schtasks.exe", "/Change", "/TN", "Timeshow", "/DISABLE"],
                           check=True, capture_output=True, timeout=30)
            config = root / "roaming/Timeshow"
            settings = config / "settings.json"
            value = json.loads(settings.read_text())
            value["running"] = True
            settings.write_text(json.dumps(value))
            encrypted = (config / "state.enc").read_bytes()
            key_record = (config / "key.json").read_bytes()
            self._run_uninstaller(directory, from_environment)
            self.assertFalse((directory / "Timeshow.exe").exists())
            self.assertFalse(self._task_exists())
            self.assertFalse(any(path.exists() for path in shortcuts))
            self.assertEqual((config / "state.enc").read_bytes(), encrypted)
            self.assertEqual((config / "key.json").read_bytes(), key_record)
            self.assertFalse(json.loads(settings.read_text())["running"])
            with self.assertRaises(FileNotFoundError):
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.uninstall_key)
        finally:
            if created_task and self._task_exists():
                subprocess.run(["schtasks.exe", "/Delete", "/TN", "Timeshow", "/F"],
                               capture_output=True, timeout=30)
            if (directory / "Timeshow.exe").exists() and (directory / "unins000.exe").exists():
                self._run_uninstaller(directory, from_environment)

    def _check_worker_and_data(self, root, directory, environment):
        config = root / "roaming/Timeshow"
        vault = Vault.open(config, PasswordProtector("synthetic installer test password"), root / "cache")
        vault.save_state(vault.load_state())
        result = subprocess.run([str(directory / "Timeshow.exe"), "--mode", "worker",
                                 "--action", "tick", "--session-key"], input=vault.session_key(),
                                env=environment, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
