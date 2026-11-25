"""Saved display orders use synthetic sources and a fake desktop."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeshow.photos import ImageCandidate, PhotosError
from timeshow.player import CollectionExhausted, Player
from timeshow.security import PasswordProtector, Vault

from test_desktop_app import ALBUM_URL, PASSWORD, FakeDesktop, PhotoSource


class RotationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vault = Vault.open(self.root / "config", PasswordProtector(PASSWORD), self.root / "cache")
        self.source = PhotoSource()
        self.source.images = [ImageCandidate(f"synthetic-{i:02}",
                              f"https://lh3.googleusercontent.com/synthetic-{i:02}", 32, 24, None)
                              for i in range(8)]
        self.desktop = FakeDesktop()
        self.player = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        self.player.screen_size = (40, 30)
        self.player.add_album("Synthetic", ALBUM_URL)
        self.player.refresh()

    def show(self, count):
        return [self.player.next().media_id for _ in range(count)]

    def test_enumeration_is_saved_and_navigation_does_not_shuffle(self):
        order = self.player.state["show_order"].copy()
        with patch("timeshow._rotation.secrets.SystemRandom") as random:
            self.assertEqual(self.show(3), order[:3])
            self.assertEqual(self.player.previous().media_id, order[1])
            self.assertEqual(self.player.next().media_id, order[2])
            random.assert_not_called()
        self.assertEqual(self.player.state["show_order"], order)
        self.assertEqual(self.player.state["cursor"], 2)
        reopened = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        self.assertEqual(reopened.state["show_order"], order)
        self.assertEqual(reopened.next().media_id, order[3])
        self.assertNotIn("seen", self.vault.load_state())
        self.assertNotIn("history", self.vault.load_state())

    def test_cycle_appends_to_the_existing_list_and_starts_after_it(self):
        shown = self.show(8)
        next_image = self.player.next().media_id
        order = self.player.state["show_order"]
        self.assertEqual(order[:8], shown)
        self.assertEqual(set(order[8:]), set(shown))
        self.assertEqual(len(order), 16)
        self.assertEqual(next_image, order[8])
        self.assertNotEqual(next_image, shown[-1])
        self.assertEqual(self.player.state["cursor"], 8)
        self.assertEqual(self.player.remaining(), 7)
        self.assertEqual(self.player.previous().media_id, shown[-1])
        self.assertEqual(self.player.next().media_id, next_image)

    def test_previous_is_unlimited_across_cycles(self):
        shown = self.show(25)
        before = self.player.state["show_order"].copy()
        for expected in reversed(shown[:-1]):
            self.assertEqual(self.player.previous().media_id, expected)
        with self.assertRaises(PhotosError):
            self.player.previous()
        self.assertEqual(self.player.state["show_order"], before)
        self.assertEqual(self.show(24), shown[1:])

    def test_restart_keeps_all_entries_through_current_position(self):
        shown = self.show(12)
        self.player.previous()
        current = self.player.current.media_id
        self.player.reset_history()
        self.assertEqual(self.player.state["show_order"][:11], shown[:11])
        self.assertEqual(self.player.state["cursor"], 10)
        self.assertEqual(len(self.player.state["show_order"]), 19)
        self.assertNotEqual(self.player.next().media_id, current)

    def test_repeated_cycles_never_show_the_same_image_twice_in_a_row(self):
        shown = self.show(48)
        self.assertTrue(all(left != right for left, right in zip(shown, shown[1:])))
        expected = {image.media_id for image in self.source.images}
        for index in range(0, len(shown), 8):
            self.assertEqual(set(shown[index:index + 8]), expected)
        self.assertEqual(len(self.player.state["show_order"]), 48)

    def test_single_image_can_repeat_without_growing_the_order(self):
        self.source.images = self.source.images[:1]
        self.player.refresh()
        expected = self.source.images[0].media_id
        self.assertEqual(self.show(4), [expected] * 4)
        self.assertEqual(self.player.state["show_order"], [expected])
        self.assertEqual(self.player.state["cursor"], 0)
        with self.assertRaises(PhotosError):
            self.player.previous()

    def test_two_images_alternate_across_cycles(self):
        self.source.images = self.source.images[:2]
        self.player.refresh()
        shown = self.show(12)
        self.assertTrue(all(left != right for left, right in zip(shown, shown[1:])))
        self.assertEqual(len(self.player.state["show_order"]), 12)

    def test_refresh_after_multiple_cycles_preserves_prefix_and_removes_all_missing_occurrences(self):
        shown = self.show(19)
        current = self.player.current.media_id
        removed = next(key for key in shown if key != current)
        self.source.images = [image for image in self.source.images if image.media_id != removed]
        self.source.images.append(ImageCandidate("synthetic-new", "https://lh3.googleusercontent.com/synthetic-new", 32, 24, None))
        self.player.refresh()
        prefix = [key for key in shown if key != removed]
        order = self.player.state["show_order"]
        self.assertEqual(order[:len(prefix)], prefix)
        self.assertEqual(self.player.state["cursor"], len(prefix) - 1)
        self.assertEqual(order[len(prefix):], ["synthetic-new"])
        self.assertNotIn(removed, order)
        self.assertEqual(self.player.next().media_id, "synthetic-new")

    def test_refresh_keeps_prefix_rebuilds_tail_and_removes_missing(self):
        old_order = self.player.state["show_order"].copy()
        self.show(4)
        self.player.previous()
        current = self.player.current
        removed = {old_order[0], old_order[-1]}
        self.source.images = [image for image in self.source.images if image.media_id not in removed]
        new = ImageCandidate("synthetic-new", "https://lh3.googleusercontent.com/synthetic-new", 32, 24, None)
        self.source.images.append(new)
        self.player.refresh()
        order = self.player.state["show_order"]
        prefix = old_order[1:3]
        self.assertEqual(order[:2], prefix)
        self.assertEqual(self.player.state["cursor"], 1)
        self.assertEqual(order[1], current.media_id)
        self.assertEqual(set(order[2:]), {image.media_id for image in self.source.images} - set(prefix))
        self.assertTrue(removed.isdisjoint(self.player.state["images"]))
        self.assertTrue(removed.isdisjoint(order))
        self.assertIs(self.player.current, current)
        self.assertEqual(len(order), len(set(order)))

    def test_refresh_removed_current_keeps_wallpaper_and_advances_to_tail(self):
        self.show(3)
        current = self.player.current
        prefix = self.player.state["show_order"][:2]
        self.source.images = [image for image in self.source.images if image.media_id != current.media_id]
        self.player.refresh()
        self.assertTrue(current.path.exists())
        reopened = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        restored = reopened.restore_current()
        self.assertEqual(restored.media_id, current.media_id)
        self.assertEqual(restored.body, current.body)
        order = reopened.state["show_order"]
        self.assertEqual(order[:2], prefix)
        self.assertEqual(reopened.state["cursor"], 1)
        self.assertEqual(reopened.next().media_id, order[2])
        self.assertFalse(current.path.exists())

    def test_refresh_removed_first_current_leaves_cursor_before_remaining_images(self):
        self.player.next()
        current = self.player.current
        self.source.images = [image for image in self.source.images if image.media_id != current.media_id]
        self.player.refresh()
        self.assertEqual(self.player.state["cursor"], -1)
        first = self.player.state["show_order"][0]
        with self.assertRaises(PhotosError):
            self.player.previous()
        self.assertTrue(current.path.exists())
        self.assertEqual(self.player.next().media_id, first)

    def test_previous_after_current_is_removed_returns_nearest_survivor(self):
        self.show(3)
        old_order = self.player.state["show_order"].copy()
        self.source.images = [image for image in self.source.images if image.media_id != old_order[2]]
        self.player.refresh()
        self.assertEqual(self.player.previous().media_id, old_order[1])

    def test_refresh_can_remove_every_image_while_retaining_wallpaper(self):
        self.player.next()
        current = self.player.current
        self.source.images = []
        self.assertEqual(self.player.refresh(), 0)
        self.assertEqual(self.player.state["show_order"], [])
        self.assertEqual(self.player.state["cursor"], -1)
        self.assertEqual(self.player.restore_current().media_id, current.media_id)
        with self.assertRaises(CollectionExhausted):
            self.player.next()
        self.assertTrue(current.path.exists())
        self.source.images = [ImageCandidate("synthetic-new", "https://lh3.googleusercontent.com/synthetic-new", 32, 24, None)]
        self.player.refresh()
        self.assertEqual(self.player.next().media_id, "synthetic-new")

    def test_failure_during_rollover_keeps_saved_order_cursor_and_wallpaper(self):
        self.show(8)
        before = self.vault.load_state()
        current = self.player.current
        self.desktop.fail_wallpaper = True
        with self.assertRaises(PhotosError):
            self.player.next()
        self.assertEqual(self.vault.load_state(), before)
        self.assertEqual(self.player.state["show_order"], before["show_order"])
        self.assertEqual(self.player.state["cursor"], before["cursor"])
        self.assertIs(self.player.current, current)
        self.assertTrue(current.path.exists())

    def test_failed_source_or_failed_refresh_save_preserves_order(self):
        self.show(2)
        self.player.add_album("Second synthetic", ALBUM_URL + "-second")
        before = self.vault.load_state()
        with patch.object(self.source, "list_images", side_effect=[self.source.images[:1], PhotosError("Synthetic listing failure")]):
            with self.assertRaises(PhotosError):
                self.player.refresh()
        self.assertEqual(self.vault.load_state(), before)
        self.source.images = self.source.images[:1]
        with patch.object(self.vault, "save_state", side_effect=OSError("Synthetic storage failure")):
            with self.assertRaises(OSError):
                self.player.refresh()
        self.assertEqual(self.player.state["show_order"], before["show_order"])
        self.assertEqual(self.vault.load_state(), before)

    def test_excluded_images_never_return_on_refresh_or_rollover(self):
        self.player.next()
        excluded = self.player.current.media_id
        self.player.exclude_current()
        self.player.refresh()
        self.assertNotIn(excluded, self.player.state["show_order"])
        self.assertNotIn(excluded, self.show(20))
        self.player.clear_exclusions()
        self.assertIn(excluded, self.player.state["show_order"])

    def test_legacy_seen_and_history_migrate_with_forward_navigation(self):
        self.show(3)
        old_order = self.player.state["show_order"].copy()
        self.player.previous()
        legacy = deepcopy(self.player.state)
        legacy.pop("show_order")
        legacy["history"] = old_order[:3]
        legacy["seen"] = old_order[:3]
        self.vault.save_state(legacy)
        key_before = (self.vault.directory / "key.json").read_bytes()
        reopened = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        self.assertEqual(reopened.state["show_order"][:3], old_order[:3])
        self.assertEqual(reopened.state["cursor"], 1)
        self.assertEqual(reopened.next().media_id, old_order[2])
        self.assertNotIn("seen", self.vault.load_state())
        self.assertNotIn("history", self.vault.load_state())
        self.assertEqual((self.vault.directory / "key.json").read_bytes(), key_before)

    def test_old_history_limit_is_removed_on_migration(self):
        state = deepcopy(self.player.state)
        state["history_limit"] = 5
        self.vault.save_state(state)
        reopened = Player(self.vault, self.desktop, self.root / "runtime", self.source)
        reopened.save()
        self.assertNotIn("history_limit", reopened.state)
        self.assertNotIn("history_limit", self.vault.load_state())
        self.assertNotIn("history_limit", (self.vault.directory / "settings.json").read_text())

    def test_cycle_boundary_skips_last_shown_even_if_shuffle_puts_it_first(self):
        self.player.state["show_order"] = sorted(self.player.state["show_order"], reverse=True)
        old = self.show(8)[-1]
        with patch("timeshow._rotation._shuffled", side_effect=lambda keys: sorted(keys)):
            selected = self.player.next().media_id
        self.assertNotEqual(selected, old)
        self.assertEqual(set(self.player.state["show_order"][8:]), set(self.player.eligible()))

    def test_next_skips_duplicate_entries_after_an_image_is_excluded(self):
        first, second, third = self.player.state["show_order"][:3]
        self.player.state["show_order"] = [first, second, first, third]
        self.player.next()
        self.player.state["excluded"] = [second]
        self.player.save()
        self.assertEqual(self.player.next().media_id, third)
