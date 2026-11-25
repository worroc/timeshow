"""Exercise launcher creation without installing dependencies or using a keyring."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


class IconTests(unittest.TestCase):
    def test_windows_icon_contains_multiple_sizes(self):
        icon = Path(__file__).resolve().parents[1] / "src/timeshow/assets/timeshow.ico"
        with Image.open(icon) as image:
            self.assertIn((16, 16), image.ico.sizes())
            self.assertIn((256, 256), image.ico.sizes())


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux installer")
class InstallerTests(unittest.TestCase):
    def test_installer_creates_icon_and_matching_launchers(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout with spaces"
            assets = checkout / "src/timeshow/assets"
            assets.mkdir(parents=True)
            shutil.copy2(project / "install.sh", checkout / "install.sh")
            shutil.copy2(project / "src/timeshow/assets/timeshow.svg", assets)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            python = checkout / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            for executable in [python, *(fake_bin / name for name in
                                ("uv", "gtk-update-icon-cache", "update-desktop-database"))]:
                executable.write_text("#!/bin/sh\nexit 0\n")
                executable.chmod(0o755)
            environment = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                               XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"))
            subprocess.run(["sh", str(checkout / "install.sh")], env=environment,
                           check=True, capture_output=True, timeout=15)
            desktop = (root / "data/applications/timeshow.desktop").read_text()
            tray = (root / "config/autostart/timeshow-tray.desktop").read_text()
            self.assertIn("Icon=timeshow\n", desktop)
            self.assertIn("StartupWMClass=timeshow\n", desktop)
            self.assertIn(f'Exec="{checkout}/.venv/bin/timeshow-gui"', desktop)
            self.assertIn("Icon=timeshow\n", tray)
            self.assertIn(f'Exec="{checkout}/.venv/bin/timeshow-tray" --login\n', tray)
            self.assertNotIn("--login", desktop)
            self.assertEqual((root / "data/icons/hicolor/scalable/apps/timeshow.svg").read_bytes(),
                             (assets / "timeshow.svg").read_bytes())
