"""Desktop behavior uses synthetic photos and never changes real wallpaper."""

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from PIL import Image
    from timeshow.player import CollectionExhausted, Player
    from timeshow.security import PasswordProtector, Vault
except ModuleNotFoundError:
    raise unittest.SkipTest("Install the gui extra to test encrypted desktop playback.")

from timeshow.photos import DownloadedImage, ImageCandidate, PhotosError
from timeshow.worker import perform

ALBUM_URL = "https://photos.google.com/share/synthetic?key=synthetic"
PASSWORD = "synthetic test password"


def image_bytes() -> bytes:
    stream = BytesIO()
    image = Image.new("RGB", (320, 200), (64, 130, 110))
    image.save(stream, format="JPEG")
    return stream.getvalue()


class PhotoSource:
    def __init__(self):
        self.images = [ImageCandidate(f"synthetic-{number}",
                       f"https://lh3.googleusercontent.com/synthetic-{number}", 320, 200,
                       int(datetime(2025, number, 1, tzinfo=timezone.utc).timestamp() * 1000))
                       for number in [1, 2, 3]]
        self.downloads = []
        self.fail_listing = False

    def list_images(self, url):
        if self.fail_listing:
            raise PhotosError("Synthetic listing failure.")
        return self.images

    def pull_image(self, image):
        self.downloads.append(image.media_id)
        return DownloadedImage(image_bytes(), ".jpg")


class FakeDesktop:
    def __init__(self):
        self.paths = []
        self.opened = []
        self.fail_wallpaper = False

    def set_wallpaper(self, path):
        if self.fail_wallpaper:
            raise PhotosError("Synthetic wallpaper failure.")
        self.paths.append(path)

    def open_album(self, url):
        self.opened.append(url)

    def reveal(self, path):
        self.opened.append(path)


class FakeScheduler:
    def __init__(self):
        self.interval = None

    def enable(self, interval):
        self.interval = interval

    def disable(self):
        self.interval = None


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = Vault.open(self.root / "vault", PasswordProtector(PASSWORD))
        self.source = PhotoSource()
        self.desktop = FakeDesktop()
        self.player = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        self.player.screen_size = (400, 300)
        self.player.add_album("Synthetic album", ALBUM_URL)
        self.player.refresh()

    def tearDown(self):
        self.temp.cleanup()

    def test_no_repeats_across_restart_and_exhaustion(self):
        first = self.player.next().media_id
        reopened = Vault.open(self.root / "vault", PasswordProtector(PASSWORD))
        player = Player(reopened, self.desktop, self.root / "runtime", self.source)
        player.screen_size = (400, 300)
        second = player.next().media_id
        third = player.next().media_id
        self.assertEqual(len({first, second, third}), 3)
        with self.assertRaises(CollectionExhausted):
            player.next()

    def test_previous_then_forward_does_not_consume_new_photo(self):
        first = self.player.next().media_id
        second = self.player.next().media_id
        downloads = len(self.source.downloads)
        self.assertEqual(self.player.previous().media_id, first)
        self.assertEqual(self.player.next().media_id, second)
        self.assertEqual(self.player.remaining(), 1)
        self.assertEqual(len(self.source.downloads), downloads + 2)

    def test_wallpaper_failure_does_not_mark_seen(self):
        self.desktop.fail_wallpaper = True
        with self.assertRaises(PhotosError):
            self.player.next()
        self.assertEqual(self.player.state["seen"], [])
        self.assertEqual(self.vault.load_state()["seen"], [])
        self.assertEqual(list((self.root / "runtime").glob("wallpaper-*")), [])

    def test_only_current_download_retained_without_losing_history(self):
        self.player.configure(30, "fit", "", "", 1)
        for _ in range(3):
            self.player.next()
        self.assertEqual(len(list((self.root / "vault/cache").glob("*.image"))), 1)
        self.assertEqual(len(self.player.state["seen"]), 3)
        with self.assertRaises(CollectionExhausted):
            self.player.next()

    def test_settings_filter_and_disabled_album(self):
        self.player.configure(30, "fill", "2025-02-01", "2025-02-28", 20)
        self.assertEqual(self.player.eligible(), ["synthetic-2"])
        self.player.enable_album(self.player.state["albums"][0]["id"], False)
        self.assertEqual(self.player.eligible(), [])

    def test_failed_refresh_preserves_earlier_complete_listing(self):
        original = self.vault.load_state()
        self.source.fail_listing = True
        with self.assertRaises(PhotosError):
            self.player.refresh()
        self.assertEqual(self.vault.load_state(), original)

    def test_overlapping_albums_are_deduplicated(self):
        self.player.add_album("Other", ALBUM_URL + "-other")
        self.assertEqual(self.player.refresh(), 3)
        self.assertEqual(len(self.player.state["images"]["synthetic-1"]["album_ids"]), 2)

    def test_exclude_deletes_cache_and_prevents_selection(self):
        photo = self.player.next()
        self.player.exclude_current()
        self.assertIsNone(self.vault.get_image(photo.media_id))
        self.assertNotIn(photo.media_id, self.player.eligible())

    def test_open_album_and_export(self):
        photo = self.player.next()
        self.player.open_current_album()
        self.assertEqual(self.desktop.opened, [ALBUM_URL])
        destination = self.root / "export.jpg"
        self.player.export_current(destination)
        self.assertEqual(destination.read_bytes(), photo.body)

    def test_encryption_and_wrong_password(self):
        self.player.next()
        state_bytes = (self.root / "vault/state.enc").read_bytes()
        self.assertNotIn(b"synthetic", state_bytes)
        self.assertNotIn(ALBUM_URL.encode(), state_bytes)
        cache_bytes = next((self.root / "vault/cache").glob("*.image")).read_bytes()
        self.assertEqual(cache_bytes, image_bytes())
        settings = (self.root / "vault/settings.json").read_text()
        self.assertNotIn("synthetic", settings)
        self.assertEqual(json.loads(settings)["fit"], "fill")
        private = json.loads(self.vault._cipher.decrypt(state_bytes))
        self.assertNotIn("fit", private)
        self.assertNotIn("interval", private)
        with self.assertRaises(PhotosError):
            Vault.open(self.root / "vault", PasswordProtector("wrong password"))

    def test_successful_switch_deletes_old_download_and_wallpaper(self):
        old = self.player.next()
        current = self.player.next()
        self.assertFalse(old.path.exists())
        self.assertIsNone(self.vault.get_image(old.media_id))
        self.assertTrue(current.path.exists())
        self.assertEqual(self.vault.get_image(current.media_id), current.body)
        self.assertIn(old.media_id, self.vault.load_state()["seen"])

    def test_failed_switch_keeps_old_image_and_history(self):
        old = self.player.next()
        state = self.vault.load_state()
        self.desktop.fail_wallpaper = True
        with self.assertRaises(PhotosError):
            self.player.next()
        self.assertIs(self.player.current, old)
        self.assertTrue(old.path.exists())
        self.assertEqual(self.vault.get_image(old.media_id), old.body)
        self.assertEqual(self.vault.load_state(), state)
        self.assertEqual(len(list(self.vault.cache_directory.iterdir())), 1)
        self.assertEqual(list(self.player.runtime.iterdir()), [old.path])

    def test_legacy_encrypted_cache_read_and_cleanup(self):
        legacy = self.vault.cache_path("synthetic-1").with_suffix(".enc")
        legacy.write_bytes(self.vault._cipher.encrypt(image_bytes()))
        self.assertEqual(self.vault.get_image("synthetic-1"), image_bytes())
        self.player.next()
        self.assertFalse(legacy.exists())
        self.assertEqual(len(list(self.vault.cache_directory.iterdir())), 1)

    def test_plain_preferences_override_saved_preferences(self):
        settings_path = self.root / "vault/settings.json"
        settings = json.loads(settings_path.read_text())
        settings.update(interval=600, fit="fit")
        settings_path.write_text(json.dumps(settings))
        self.player.reload()
        self.assertEqual(self.player.state["interval"], 600)
        self.assertEqual(self.player.state["fit"], "fit")

    def test_missing_key_never_creates_replacement(self):
        (self.root / "vault/key.json").unlink()
        with self.assertRaisesRegex(PhotosError, "Refusing"):
            Vault.open(self.root / "vault", PasswordProtector(PASSWORD))
        self.assertFalse((self.root / "vault/key.json").exists())

    def test_tampered_state_is_not_silently_reset(self):
        (self.root / "vault/state.enc").write_bytes(b"damaged")
        with self.assertRaises(PhotosError):
            Vault.open(self.root / "vault", PasswordProtector(PASSWORD))

    def test_paused_scheduled_worker_does_nothing(self):
        self.assertFalse(perform(self.player, "tick", FakeScheduler()))
        self.assertEqual(self.desktop.paths, [])

    def test_scheduled_worker_checks_interval_and_exits_after_one_switch(self):
        self.player.state["running"] = True
        self.player.save()
        self.assertTrue(perform(self.player, "tick", FakeScheduler()))
        self.assertEqual(len(self.desktop.paths), 1)
        self.assertFalse(perform(self.player, "tick", FakeScheduler()))
        self.assertEqual(len(self.desktop.paths), 1)

    def test_real_child_worker_uses_stdin_key_and_exits(self):
        config_root = self.root / "child-config"
        data_root = self.root / "child-data"
        runtime_root = self.root / "child-runtime"
        config = config_root / "timeshow"
        cache = data_root / "timeshow/cache"
        vault = Vault.open(config, PasswordProtector(PASSWORD), cache)
        player = Player(vault, FakeDesktop(), runtime_root / "timeshow", self.source)
        player.add_album("Synthetic album", ALBUM_URL)
        player.refresh()
        for candidate in self.source.images:
            vault.put_image(candidate.media_id, image_bytes())
        environment = dict(os.environ)
        environment.update(XDG_CONFIG_HOME=str(config_root), XDG_DATA_HOME=str(data_root),
                           XDG_RUNTIME_DIR=str(runtime_root))
        if sys.platform == "win32":
            self.skipTest("Windows process integration is covered by target-OS validation")
        script = (
            "from timeshow import worker; "
            "worker.Desktop = type('FakeDesktop', (), {'set_wallpaper': lambda self, path: None}); "
            "raise SystemExit(worker.main(['--action', 'next', '--session-key']))"
        )
        result = subprocess.run([sys.executable, "-c", script], input=vault.session_key(),
                                env=environment, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode())
        self.assertEqual(len(vault.load_state()["seen"]), 1)
        self.assertEqual(len(list((runtime_root / "timeshow").glob("wallpaper-*"))), 1)


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from timeshow.gui.window import UnlockDialog, Window
    HAS_QT = True
except ModuleNotFoundError:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "Install PySide6-Essentials for GUI checks")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        vault = Vault.open(self.root / "vault", PasswordProtector(PASSWORD))
        self.player = Player(vault, FakeDesktop(), self.root / "runtime", PhotoSource())
        self.player.add_album("Synthetic album", ALBUM_URL)
        self.player.refresh()
        self.window = Window(self.player, scheduler=FakeScheduler(), isolated=False)
        self.window.show()
        QTest.qWait(20)

    def tearDown(self):
        self.finish_job()
        self.window.quitting = True
        self.window.close()
        self.temp.cleanup()

    def finish_job(self):
        for _ in range(500):
            if not self.window.busy:
                return
            QTest.qWait(10)
        self.fail("GUI background operation did not finish")

    def test_window_and_tray_actions(self):
        self.assertEqual(self.window.albums.count(), 1)
        self.assertEqual(set(self.window.tray_actions), {"next", "previous", "toggle", "web", "settings", "quit"})
        self.assertFalse(self.window.running)
        self.assertFalse(self.window.web_button.isEnabled())
        self.window.tray_actions["settings"].trigger()
        self.assertEqual(self.window.tabs.currentIndex(), 1)

    def test_background_playback_updates_preview(self):
        self.window.next_photo()
        self.finish_job()
        self.assertIsNotNone(self.player.current)
        self.assertFalse(self.window._pixmap.isNull())
        self.assertEqual(len(self.player.state["seen"]), 1)
        self.assertTrue(self.window.web_button.isEnabled())

    def test_start_pause_and_exhaustion(self):
        self.window.toggle()
        self.finish_job()
        self.assertTrue(self.window.running)
        self.assertTrue(self.window.timer.isActive())
        self.assertEqual(self.window.scheduler.interval, 300)
        self.window.toggle()
        self.finish_job()
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.scheduler.interval)
        for _ in range(4):
            self.window.next_photo()
            self.finish_job()
        self.assertIn("Every eligible photo", self.window.status.text())

    def test_unlock_dialog_password_setup(self):
        dialog = UnlockDialog(self.root / "new-vault", self.root / "new-cache")
        dialog.mode.setCurrentIndex(dialog.mode.findData("password"))
        dialog.password.setText(PASSWORD)
        dialog.confirm.setText(PASSWORD)
        dialog.unlock()
        self.assertIsNotNone(dialog.vault)
