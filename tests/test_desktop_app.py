"""Desktop behavior uses synthetic photos and never changes real wallpaper."""

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

try:
    from PIL import Image
    from timeshow.player import CollectionExhausted, Player
    from timeshow.security import KeyringProtector, PasswordProtector, Vault
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

    def open_folder(self, path):
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

    def test_resume_switches_immediately_and_pause_does_not_switch(self):
        scheduler = FakeScheduler()
        self.player.state["images"] = {}
        with patch.object(Vault, "mode", return_value="keyring"):
            perform(self.player, "resume", scheduler)
        self.assertEqual(scheduler.interval, 300)
        self.assertTrue(self.player.state["running"])
        self.assertGreater(self.player.state["last_switch"], 0)
        self.assertEqual(len(self.desktop.paths), 1)
        perform(self.player, "pause", scheduler)
        self.assertIsNone(scheduler.interval)
        self.assertEqual(len(self.desktop.paths), 1)

    def test_resume_failure_keeps_schedule_enabled(self):
        scheduler = FakeScheduler()
        self.desktop.fail_wallpaper = True
        with patch.object(Vault, "mode", return_value="keyring"):
            with self.assertRaises(PhotosError):
                perform(self.player, "resume", scheduler)
        self.assertTrue(self.vault.load_state()["running"])
        self.assertEqual(scheduler.interval, 300)

    @unittest.skipUnless(hasattr(time, "tzset"), "Requires POSIX time zones")
    def test_filters_use_local_dates_and_include_both_bounds(self):
        try:
            with patch.dict(os.environ, {"TZ": "EST5"}):
                time.tzset()
                self.player.state["images"]["synthetic-1"]["capture_time_ms"] = int(
                    datetime(2025, 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
                self.player.state["images"]["synthetic-2"]["capture_time_ms"] = None
                self.player.configure(60, "fill", "2024-12-31", "2024-12-31", 1)
                self.assertEqual(self.player.eligible(), ["synthetic-1"])
                self.player.configure(60, "fill", "", "", 1)
                self.assertEqual(len(self.player.eligible()), 3)
        finally:
            time.tzset()

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
    from PySide6.QtCore import QDate
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from timeshow.gui.window import UnlockDialog, Window, main as gui_main
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
        deadline = time.monotonic() + 5
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            # qWait holds the Python GIL. Sleep releases it so the job can run.
            time.sleep(0.01)
        self.assertFalse(self.window.busy, "GUI background operation did not finish")

    def test_window_and_tray_actions(self):
        self.assertEqual(self.window.albums.count(), 1)
        self.assertEqual(set(self.window.tray_actions), {"next", "previous", "toggle", "web", "settings", "quit"})
        self.assertFalse(self.window.running)
        self.assertFalse(self.window.web_button.isEnabled())
        self.window.tray_actions["settings"].trigger()
        self.assertEqual(self.window.tabs.currentIndex(), 1)

    def test_background_playback_updates_preview(self):
        original_interval = sys.getswitchinterval()
        try:
            # The wait must let the worker run even without interpreter time slices.
            sys.setswitchinterval(10)
            self.window.next_photo()
            self.finish_job()
        finally:
            sys.setswitchinterval(original_interval)
        self.assertIsNotNone(self.player.current)
        self.assertFalse(self.window._pixmap.isNull())
        self.assertEqual(len(self.player.state["seen"]), 1)
        self.assertTrue(self.window.web_button.isEnabled())

    def test_filters_tab_saves_date_range(self):
        index = next(index for index in range(self.window.tabs.count())
                     if self.window.tabs.tabText(index) == "Filters")
        self.window.tabs.setCurrentIndex(index)
        self.window.after.setDate(QDate(2025, 2, 1))
        self.window.before.setDate(QDate(2025, 2, 28))
        self.window.save_settings()
        self.finish_job()
        self.assertEqual(self.player.eligible(), ["synthetic-2"])
        self.player.reload()
        self.assertEqual(self.player.state["after"], "2025-02-01")
        self.assertEqual(self.player.state["before"], "2025-02-28")
        self.assertIn("1 of 3 photos match", self.window.filter_counts.text())

    def test_filters_can_be_cleared_and_reject_reversed_range(self):
        self.window.after.setDate(QDate(2025, 3, 1))
        self.window.before.setDate(QDate(2025, 2, 1))
        self.window.save_settings()
        self.assertFalse(self.window.busy)
        self.assertIn("From must be on or before To", self.window.status.text())
        for field in (self.window.after, self.window.before):
            field.setDate(field.minimumDate())
        self.window.save_settings()
        self.finish_job()
        self.assertEqual(self.player.state["after"], "")
        self.assertEqual(self.player.state["before"], "")

    def test_open_config_opens_the_config_folder(self):
        button = next(button for button in self.window.findChildren(QPushButton)
                      if button.text() == "Open Config")
        button.click()
        self.finish_job()
        self.assertEqual(self.player.desktop.opened, [self.player.vault.directory])

    def test_packaged_icon_renders(self):
        self.assertFalse(self.window.windowIcon().pixmap(64, 64).isNull())

    def test_version_is_shown_in_title_and_about(self):
        project = Path(__file__).resolve().parents[1]
        expected = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
        self.assertEqual(self.window.windowTitle(), f"Timeshow {expected}")
        self.assertIn("Timeshow", {label.text() for label in self.window.findChildren(QLabel)})
        self.assertIn(expected, self.window.tray.toolTip())
        with patch("timeshow.gui.window.QMessageBox.about") as about:
            help_menu = self.window.menuBar().actions()[0].menu()
            help_menu.actions()[0].trigger()
            self.assertEqual(about.call_args.args[1], f"About Timeshow {expected}")
            self.assertIn(f"Timeshow {expected}", about.call_args.args[2])

    def test_window_fits_half_screen_with_photo_and_each_tab(self):
        self.window.next_photo()
        self.finish_job()
        for font_size in (9, 10, 11):
            font = self.window.font()
            font.setPointSize(font_size)
            self.window.setFont(font)
            for width, height in [(683, 700), (960, 540)]:
                self.window.resize(width, height)
                for index in range(self.window.tabs.count()):
                    self.window.tabs.setCurrentIndex(index)
                    self.app.processEvents()
                    self.assertEqual(self.window.width(), width)
                    self.assertEqual(self.window.height(), height)
                    scroll = self.window.tabs.currentWidget()
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0,
                                     (font_size, self.window.tabs.tabText(index)))
        self.window.resize(1120, 760)
        self.app.processEvents()
        self.assertGreater(self.window.tabs.x(), self.window.preview.x())

    def test_start_pause_and_exhaustion(self):
        with patch.object(Vault, "mode", return_value="keyring"):
            self.window.toggle()
            self.finish_job()
        self.assertTrue(self.window.running)
        self.assertEqual(len(self.player.desktop.paths), 1)
        self.assertTrue(self.window.timer.isActive())
        self.assertEqual(self.window.scheduler.interval, 300)
        self.window.toggle()
        self.finish_job()
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.scheduler.interval)
        self.assertEqual(len(self.player.desktop.paths), 1)
        for _ in range(4):
            self.window.next_photo()
            self.finish_job()
        self.assertIn("Every eligible photo", self.window.status.text())

    def test_start_failure_shows_error_and_keeps_running(self):
        self.player.desktop.fail_wallpaper = True
        with patch.object(Vault, "mode", return_value="keyring"):
            self.window.toggle()
            self.finish_job()
        self.assertTrue(self.window.running)
        self.assertIn("wallpaper failure", self.window.status.text())

    def test_start_exhaustion_pauses_rotation(self):
        self.player.state["seen"] = list(self.player.state["images"])
        self.player.save()
        with patch.object(Vault, "mode", return_value="keyring"):
            self.window.toggle()
            self.finish_job()
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.scheduler.interval)

    def test_existing_password_storage_still_unlocks(self):
        dialog = UnlockDialog(self.root / "vault", self.root / "vault/cache")
        self.assertTrue(dialog.mode.isHidden())
        self.assertTrue(dialog.confirm.isHidden())
        dialog.password.setText("wrong synthetic password")
        dialog.unlock()
        self.assertIsNone(dialog.vault)
        dialog.password.setText(PASSWORD)
        dialog.unlock()
        self.assertIsNotNone(dialog.vault)

    def test_normal_startup_opens_window_without_setup_dialog(self):
        directory = self.root / "automatic-config"
        wrapper = PasswordProtector(PASSWORD)
        with patch("timeshow._setup.sys") as system, patch.object(
            KeyringProtector, "protect", side_effect=wrapper.protect
        ) as protect, patch.object(KeyringProtector, "unlock", side_effect=wrapper.unlock), patch(
            "timeshow.gui.window.config_directory", return_value=directory
        ), patch("timeshow.gui.window.app_directory", return_value=self.root / "data"), patch(
            "timeshow.gui.window.runtime_directory", return_value=self.root / "runtime"
        ), patch("timeshow.gui.window.QApplication") as application, patch(
            "timeshow.gui.window.Window"
        ) as window, patch("timeshow.gui.window.UnlockDialog") as dialog, patch(
            "timeshow.gui.window.spawn"
        ), patch("timeshow.gui.window.QLockFile"):
            system.platform = "linux"
            application.return_value.exec.return_value = 0
            self.assertEqual(gui_main(), 0)
            self.assertEqual(gui_main(), 0)
            self.assertEqual(window.return_value.show.call_count, 2)
            expected = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]["version"]
            application.return_value.setApplicationVersion.assert_called_with(expected)
            dialog.assert_not_called()
            protect.assert_called_once()
