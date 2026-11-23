"""Validate Debian metadata and payload with a small synthetic bundle."""

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest

from PIL import Image

from build_deb import _check_bundle, main


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("dpkg-deb"), "Requires Debian build tools")
class DebianPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        executable = self.bundle / "Timeshow"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (self.bundle / "_internal").mkdir()
        version = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]["version"]
        version_file = self.bundle / "_internal/timeshow/_version.txt"
        version_file.parent.mkdir()
        version_file.write_text(version + "\n")
        (self.bundle / "_internal/synthetic-library").write_text("synthetic")
        (self.bundle / "LICENSE").write_text("Synthetic license")
        (self.bundle / "dependency-licenses").mkdir()
        (self.bundle / "dependency-licenses/synthetic-license").write_text("synthetic license")

    def test_package_version_payload_ownership_and_scripts(self):
        project = Path(__file__).resolve().parents[1]
        version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
        architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
        self.assertEqual(main(["--bundle", str(self.bundle), "--output-dir", str(self.root / "output")]), 0)
        package = self.root / "output" / f"timeshow_{version}_{architecture}.deb"
        for field, expected in [("Version", version), ("Architecture", architecture), ("Package", "timeshow")]:
            self.assertEqual(subprocess.check_output(["dpkg-deb", "--field", str(package), field], text=True).strip(), expected)
        stream = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
        with tarfile.open(fileobj=BytesIO(stream)) as archive:
            members = archive.getmembers()
            self.assertTrue(all(member.uid == 0 and member.gid == 0 for member in members))
            names = {member.name for member in members}
            for name in (
                "opt/timeshow/Timeshow", "opt/timeshow/dependency-licenses/synthetic-license",
                "opt/timeshow/_internal/timeshow/_version.txt",
                "usr/bin/timeshow", "usr/bin/timeshow-tray", "usr/bin/timeshow-worker",
                "usr/share/applications/timeshow.desktop", "usr/lib/systemd/user/timeshow.service",
                "usr/share/icons/hicolor/scalable/apps/timeshow.svg",
                "usr/share/icons/hicolor/256x256/apps/timeshow.png",
                "usr/share/pixmaps/timeshow.png",
                "etc/xdg/autostart/timeshow-tray.desktop", "usr/share/doc/timeshow/copyright",
            ):
                self.assertIn("./" + name, names)
            self.assertFalse(any(name.startswith(("./home/", "./root/")) for name in names))
            for launcher in ("usr/share/applications/timeshow.desktop", "etc/xdg/autostart/timeshow-tray.desktop"):
                text = archive.extractfile("./" + launcher).read().decode()
                icon_path = next(line.removeprefix("Icon=") for line in text.splitlines()
                                 if line.startswith("Icon="))
                self.assertEqual(icon_path, "/usr/share/pixmaps/timeshow.png")
                member = archive.getmember("." + icon_path)
                self.assertEqual(member.mode & 0o777, 0o644)
                with Image.open(BytesIO(archive.extractfile(member).read())) as icon:
                    self.assertEqual(icon.format, "PNG")
                    self.assertEqual(icon.size, (256, 256))
                    self.assertIsNotNone(icon.getchannel("A").getbbox())
        control = self.root / "control"
        subprocess.run(["dpkg-deb", "--control", str(package), str(control)], check=True)
        for script in ("postinst", "postrm"):
            subprocess.run(["sh", "-n", str(control / script)], check=True)
            text = (control / script).read_text()
            self.assertNotIn("systemctl", text)
            self.assertNotIn("HOME", text)

    def test_bundle_rejects_private_state(self):
        (self.bundle / "_internal/key.json").write_text("synthetic")
        with self.assertRaisesRegex(ValueError, "private"):
            _check_bundle(self.bundle)

    def test_stale_bundle_version_is_rejected(self):
        (self.bundle / "_internal/timeshow/_version.txt").write_text("0.0.0\n")
        with self.assertRaisesRegex(ValueError, "Rebuild"):
            main(["--bundle", str(self.bundle), "--output-dir", str(self.root / "output")])

    def test_bundle_rejects_external_symbolic_links(self):
        outside = self.root / "outside"
        outside.write_text("unrelated")
        (self.bundle / "_internal/link").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            _check_bundle(self.bundle)
