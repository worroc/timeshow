"""Desktop behavior uses synthetic photos and never changes real wallpaper."""

from copy import deepcopy
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

from timeshow.photos import DownloadedImage, HttpStatusError, ImageCandidate, PhotosError
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
        self.http_status = {}

    def list_images(self, url):
        if self.fail_listing:
            raise PhotosError("Synthetic listing failure.")
        return self.images

    def pull_image(self, image):
        self.downloads.append(image.media_id)
        if image.media_id in self.http_status:
            raise HttpStatusError(self.http_status[image.media_id])
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

    def local_photo(self, relative: str, captured: str | None = None) -> Path:
        path = self.root / "local photos" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        exif = Image.Exif()
        if captured:
            exif[34665] = {36867: captured}
        Image.new("RGB", (32, 24), (90, 130, 70)).save(path, exif=exif)
        return path

    def test_local_folders_mix_with_albums_and_keep_history_after_restart(self):
        first = self.local_photo("first.jpg")
        second = self.local_photo("nested/second.PNG")
        originals = {path: path.read_bytes() for path in (first, second)}
        self.player.add_folder("Local", first.parent)
        self.assertEqual(self.player.refresh(), 5)
        shown = {self.player.next().media_id for _ in range(5)}
        self.assertEqual(len(shown), 5)
        self.assertEqual(len(self.source.downloads), 3)
        reopened = Player(Vault.open(self.vault.directory, PasswordProtector(PASSWORD)),
                          self.desktop, self.root / "runtime", self.source)
        self.assertEqual(reopened.refresh(), 5)
        self.assertEqual(reopened.remaining(), 0)
        self.assertNotEqual(reopened.next().media_id, self.player.current.media_id)
        for path, body in originals.items():
            self.assertEqual(path.read_bytes(), body)

    def test_overlapping_folders_deduplicate_and_duplicate_folder_is_rejected(self):
        photo = self.local_photo("nested/first.jpg")
        self.player.add_folder("Parent", photo.parent.parent)
        self.player.add_folder("Child", photo.parent)
        with self.assertRaisesRegex(PhotosError, "already configured"):
            self.player.add_folder("Again", photo.parent / ".")
        self.player.add_album("Another album", ALBUM_URL + "-other")
        self.assertEqual(self.player.refresh(), 4)
        local = [item for item in self.player.state["images"].values() if item.get("source") == "folder"]
        self.assertEqual(len(local), 1)
        self.assertEqual(len(local[0]["album_ids"]), 2)
        self.player.enable_album(self.player.state["albums"][1]["id"], False)
        self.player.remove_album(self.player.state["albums"][2]["id"])
        self.assertEqual(self.player.refresh(), 3)
        self.assertTrue(photo.exists())

    def test_local_capture_dates_and_paths_stay_private(self):
        dated = self.local_photo("dated.jpg", "2025:02:15 12:00:00")
        self.local_photo("undated.jpg")
        self.local_photo("bad-date.jpg", "not a capture date")
        self.player.add_folder("Local", dated.parent)
        self.player.enable_album(self.player.state["albums"][0]["id"], False)
        self.assertEqual(self.player.refresh(), 3)
        self.player.configure(60, "fill", "2025-02-15", "2025-02-15", 1)
        self.assertEqual(len(self.player.eligible()), 1)
        self.assertEqual(self.player.next().body, dated.read_bytes())
        self.player.open_current_album()
        self.assertEqual(self.desktop.opened, [dated.parent.resolve()])
        for name in ("state.enc", "settings.json"):
            self.assertNotIn(str(dated.parent.resolve()).encode(), (self.vault.directory / name).read_bytes())

    def test_bad_local_listing_never_publishes_a_partial_refresh(self):
        photo = self.local_photo("first.jpg")
        self.player.add_folder("Local", photo.parent)
        self.player.refresh()
        original = self.vault.load_state()
        original_memory = deepcopy(self.player.state)
        corrupt = photo.parent / "broken.jpg"
        corrupt.write_bytes(b"synthetic corrupt photo")
        with self.assertRaises(PhotosError) as caught:
            self.player.refresh()
        self.assertNotIn(str(photo.parent), str(caught.exception))
        self.assertEqual(self.vault.load_state(), original)
        self.assertEqual(self.player.state, original_memory)
        corrupt.unlink()
        photo.unlink()
        photo.parent.rmdir()
        with self.assertRaises(PhotosError):
            self.player.refresh()
        self.assertEqual(self.vault.load_state(), original)

    def test_missing_local_file_keeps_wallpaper_and_originals_are_never_cleaned(self):
        first = self.local_photo("first.jpg")
        second = self.local_photo("second.jpg")
        self.player.add_folder("Local", first.parent)
        self.player.enable_album(self.player.state["albums"][0]["id"], False)
        self.player.refresh()
        keys = self.player.eligible()
        self.player.state["show_order"] = keys
        self.player.save()
        old = self.player.next()
        state = self.vault.load_state()
        Path(self.player.state["images"][keys[1]]["url"]).unlink()
        with self.assertRaises(PhotosError):
            self.player.next()
        self.assertTrue(old.path.exists())
        self.assertEqual(self.vault.load_state(), state)
        self.assertEqual(self.vault.get_image(old.media_id), old.body)
        self.player.exclude_current()
        self.assertTrue(Path(self.player.state["images"][old.media_id]["url"]).exists())
        self.assertIsNone(self.vault.get_image(old.media_id))

    def test_local_previous_reads_original_after_cache_cleanup(self):
        first = self.local_photo("first.jpg")
        self.local_photo("second.webp")
        self.player.add_folder("Local", first.parent)
        self.player.enable_album(self.player.state["albums"][0]["id"], False)
        self.player.refresh()
        old = self.player.next()
        self.player.next()
        self.assertIsNone(self.vault.get_image(old.media_id))
        self.assertEqual(self.player.previous().media_id, old.media_id)
        self.assertEqual(self.source.downloads, [])

    def test_local_folder_ignores_nonphotos_and_does_not_follow_symlinks(self):
        photo = self.local_photo("first.gif")
        (photo.parent / "notes.txt").write_text("synthetic notes")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "not-a-photo.jpg").write_bytes(b"synthetic corrupt photo")
        try:
            (photo.parent / "linked-directory").symlink_to(outside, target_is_directory=True)
            (photo.parent / "linked.jpg").symlink_to(outside / "not-a-photo.jpg")
        except OSError:
            pass  # Windows may require extra privileges to create symlinks.
        self.player.add_folder("Local", photo.parent)
        self.assertEqual(self.player.refresh(), 4)

    def test_unreadable_subfolder_fails_without_losing_listing(self):
        photo = self.local_photo("first.jpg")
        self.player.add_folder("Local", photo.parent)
        self.player.refresh()
        original = self.vault.load_state()
        def denied(root, *, onerror, followlinks):
            onerror(PermissionError("synthetic private folder details"))
        with patch("timeshow._local.os.walk", side_effect=denied):
            with self.assertRaises(PhotosError):
                self.player.refresh()
        self.assertEqual(self.vault.load_state(), original)

    def test_no_repeats_across_restart_and_cycle_rollover(self):
        first = self.player.next().media_id
        reopened = Vault.open(self.root / "vault", PasswordProtector(PASSWORD))
        player = Player(reopened, self.desktop, self.root / "runtime", self.source)
        player.screen_size = (400, 300)
        second = player.next().media_id
        third = player.next().media_id
        self.assertEqual(len({first, second, third}), 3)
        self.assertNotEqual(player.next().media_id, third)

    def test_previous_then_forward_does_not_consume_new_photo(self):
        first = self.player.next().media_id
        second = self.player.next().media_id
        downloads = len(self.source.downloads)
        self.assertEqual(self.player.previous().media_id, first)
        self.assertEqual(self.player.next().media_id, second)
        self.assertEqual(self.player.remaining(), 1)
        self.assertEqual(len(self.source.downloads), downloads + 2)

    def test_wallpaper_failure_does_not_advance_cursor(self):
        self.desktop.fail_wallpaper = True
        with self.assertRaises(PhotosError):
            self.player.next()
        self.assertEqual(self.player.state["cursor"], -1)
        self.assertEqual(self.vault.load_state()["cursor"], -1)
        self.assertEqual(list((self.root / "runtime").glob("wallpaper-*")), [])

    def test_only_current_download_retained_without_losing_history(self):
        self.player.configure(30, "fit", "", "", 1)
        for _ in range(3):
            self.player.next()
        self.assertEqual(len(list((self.root / "vault/cache").glob("*.image"))), 1)
        self.assertEqual(self.player.state["cursor"], 2)
        old = self.player.current.media_id
        self.assertNotEqual(self.player.next().media_id, old)

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

    def fixed_order(self) -> list[str]:
        keys = sorted(self.player.eligible())
        self.player.state["show_order"] = keys
        self.player.state["cursor"] = -1
        self.player.save()
        return keys

    def test_gone_photo_is_excluded_and_next_photo_is_shown(self):
        first, second, third = self.fixed_order()
        self.player.next()
        self.source.http_status[second] = 403
        shown = self.player.next()
        self.assertEqual(shown.media_id, third)
        state = self.vault.load_state()
        self.assertEqual(state["excluded"], [second])
        self.assertEqual(state["show_order"], [first, third])
        self.assertEqual(state["cursor"], 1)
        self.assertEqual(state["current"]["media_id"], third)

    def test_previous_skips_gone_photo_and_excludes_it(self):
        first, second, third = self.fixed_order()
        for _ in range(3):
            self.player.next()
        self.source.http_status[second] = 410
        self.assertEqual(self.player.previous().media_id, first)
        state = self.vault.load_state()
        self.assertEqual(state["excluded"], [second])
        self.assertEqual(state["show_order"], [first, third])
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(self.player.next().media_id, third)

    def test_previous_with_only_gone_photos_behind_excludes_nothing(self):
        self.fixed_order()
        self.player.next()
        self.player.next()
        state = self.vault.load_state()
        self.source.http_status[state["show_order"][0]] = 404
        with self.assertRaises(PhotosError):
            self.player.previous()
        self.assertEqual(self.vault.load_state(), state)

    def test_temporary_download_error_excludes_nothing(self):
        self.fixed_order()
        self.player.next()
        state = self.vault.load_state()
        for status in [429, 500, 503]:
            self.source.http_status = {key: status for key in self.player.eligible()}
            with self.assertRaises(HttpStatusError):
                self.player.next()
            self.assertEqual(self.vault.load_state(), state)

    def test_when_every_photo_is_gone_nothing_is_excluded(self):
        self.fixed_order()
        state = self.vault.load_state()
        self.source.http_status = {key: 403 for key in self.player.eligible()}
        with self.assertRaises(PhotosError) as raised:
            self.player.next()
        self.assertNotIsInstance(raised.exception, CollectionExhausted)
        self.assertEqual(self.vault.load_state(), state)

    def test_gone_skips_are_limited_per_switch(self):
        self.source.images = [ImageCandidate(f"synthetic-many-{number}",
                              f"https://lh3.googleusercontent.com/synthetic-many-{number}", 320, 200, None)
                              for number in range(10)]
        self.player.refresh()
        keys = self.fixed_order()
        state = self.vault.load_state()
        self.source.http_status = {key: 404 for key in keys[:6]}
        with self.assertRaises(HttpStatusError):
            self.player.next()
        self.assertEqual(self.vault.load_state(), state)

    def test_exclusion_renumbers_order_and_keeps_pointer_on_last_shown(self):
        first, second, third = self.fixed_order()
        self.player.next()
        self.player.next()
        self.assertEqual(self.player.state["current"]["media_id"], second)
        self.player._exclude([first])
        self.assertEqual(self.player.state["show_order"], [second, third])
        self.assertEqual(self.player.state["cursor"], 0)
        self.player._exclude([third])
        self.assertEqual(self.player.state["show_order"], [second])
        self.assertEqual(self.player.state["cursor"], 0)
        self.assertEqual(self.vault.load_state()["show_order"], [second])

    def test_excluding_current_moves_pointer_to_photo_before_it(self):
        first, second, third = self.fixed_order()
        self.player.next()
        self.player.next()
        self.player.exclude_current()
        self.assertEqual(self.player.state["show_order"], [first, third])
        self.assertEqual(self.player.state["cursor"], 0)
        self.assertEqual(self.player.next().media_id, third)

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
        self.assertIn(old.media_id, self.vault.load_state()["show_order"])

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

    def test_login_changes_only_when_enabled_and_running(self):
        for running, change in [(False, False), (False, True), (True, False)]:
            with self.subTest(running=running, change=change):
                self.player.state.update(running=running, change_on_login=change)
                self.assertFalse(perform(self.player, "login", FakeScheduler()))
                self.assertEqual(self.desktop.paths, [])
        self.player.state.pop("change_on_login")
        self.assertFalse(perform(self.player, "login", FakeScheduler()))

    def test_login_changes_before_interval_and_restarts_interval(self):
        old = self.player.next()
        self.player.state.update(running=True, change_on_login=True, interval=7200)
        scheduler = FakeScheduler()
        self.assertTrue(perform(self.player, "login", scheduler))
        self.assertNotEqual(self.player.current.media_id, old.media_id)
        self.assertEqual(len(self.desktop.paths), 2)
        self.assertEqual(scheduler.interval, 7200)
        self.assertFalse(perform(self.player, "tick", scheduler))
        self.assertEqual(len(self.desktop.paths), 2)

    def test_failed_login_switch_keeps_current_wallpaper_and_history(self):
        old = self.player.next()
        self.player.state.update(running=True, change_on_login=True)
        self.player.save()
        before = self.vault.load_state()
        self.desktop.fail_wallpaper = True
        with self.assertRaises(PhotosError):
            perform(self.player, "login", FakeScheduler())
        self.assertEqual(self.vault.load_state(), before)
        self.assertTrue(old.path.exists())
        self.assertIs(self.player.current, old)

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
        self.assertEqual(vault.load_state()["cursor"], 0)
        self.assertEqual(len(list((runtime_root / "timeshow").glob("wallpaper-*"))), 1)

    def test_real_child_worker_reads_local_original_without_network(self):
        photo = self.local_photo("first.jpg")
        original = photo.read_bytes()
        self.player.remove_album(self.player.state["albums"][0]["id"])
        self.player.add_folder("Local", photo.parent)
        self.player.refresh()
        script = (
            "from pathlib import Path; import sys; from timeshow import worker; "
            "worker.config_directory = lambda: Path(sys.argv[1]); "
            "worker.app_directory = lambda: Path(sys.argv[2]); "
            "worker.runtime_directory = lambda: Path(sys.argv[3]); "
            "worker.Desktop = type('FakeDesktop', (), {'set_wallpaper': lambda self, path: None}); "
            "raise SystemExit(worker.main(['--action', 'next', '--session-key']))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.vault.directory), str(self.root / "data"),
             str(self.root / "child-runtime")], input=self.vault.session_key(),
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout.decode())
        self.assertEqual(self.vault.load_state()["cursor"], 0)
        self.assertEqual(photo.read_bytes(), original)


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

    def test_add_folder_through_picker_alongside_album(self):
        folder = self.root / "local photos"
        folder.mkdir()
        photo = folder / "first.jpg"
        photo.write_bytes(image_bytes())
        button = next(button for button in self.window.findChildren(QPushButton)
                      if button.text() == "Add folder…")
        with patch("timeshow.gui.window.QFileDialog.getExistingDirectory", return_value=str(folder)):
            button.click()
        self.finish_job()
        self.assertEqual(self.window.albums.count(), 2)
        self.assertEqual(self.player.state["albums"][1]["path"], str(folder.resolve()))
        self.window.refresh_photos()
        self.finish_job()
        self.assertEqual(len(self.player.eligible()), 4)
        with patch("timeshow.gui.window.QFileDialog.getExistingDirectory", return_value=""):
            button.click()
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.albums.count(), 2)

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
        self.assertEqual(self.player.state["cursor"], 0)
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

    def test_change_on_login_checkbox_is_saved_without_starting_rotation(self):
        self.assertFalse(self.window.change_on_login.isChecked())
        self.window.change_on_login.setChecked(True)
        with patch.object(Vault, "mode", return_value="keyring"):
            self.window.save_settings()
            self.finish_job()
        self.player.reload()
        self.assertTrue(self.player.state["change_on_login"])
        self.window.change_on_login.setChecked(False)
        self.window._load_settings()
        self.assertTrue(self.window.change_on_login.isChecked())
        self.assertFalse(self.player.state.get("running", False))
        self.assertEqual(self.player.desktop.paths, [])
        self.window.change_on_login.setChecked(False)
        self.window.save_settings()
        self.finish_job()
        self.assertFalse(self.player.vault.load_state()["change_on_login"])

    def test_password_storage_cannot_enable_login_changes(self):
        self.window.change_on_login.setChecked(True)
        self.window.save_settings()
        self.finish_job()
        self.assertIn("account login needs system account protection", self.window.status.text())
        self.assertFalse(self.player.vault.load_state().get("change_on_login", False))

    def test_settings_have_no_history_limit(self):
        self.assertFalse(hasattr(self.window, "history_limit"))
        self.window.save_settings()
        self.finish_job()
        self.player.reload()
        self.assertNotIn("history_limit", self.player.state)
        settings = json.loads((self.player.vault.directory / "settings.json").read_text())
        self.assertNotIn("history_limit", settings)

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
        self.assertIn("Photo displayed", self.window.status.text())

    def test_start_failure_shows_error_and_keeps_running(self):
        self.player.desktop.fail_wallpaper = True
        with patch.object(Vault, "mode", return_value="keyring"):
            self.window.toggle()
            self.finish_job()
        self.assertTrue(self.window.running)
        self.assertIn("wallpaper failure", self.window.status.text())

    def test_start_with_no_eligible_photos_pauses_rotation(self):
        self.player.source.images = []
        self.player.refresh()
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
