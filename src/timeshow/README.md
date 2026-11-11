# Timeshow library

The library lists photos in a Google Photos link-shared album and downloads one
random photo. It needs no Google account credentials or API keys.

- `photos/` is the enclosed retrieval library. Its public `PhotosClient` interface
  lists photo candidates and pulls one image. See `photos/README.md` for usage.
- `storage.py` writes private files atomically.
- `app.py` coordinates listing, random selection, and exactly one download.
- `cli.py` reads local configuration, runs the app, and prints non-private status.
- `player.py` manages GUI rotation, date filters, current-image retention, and no-repeat history.
- `settings.py` stores ordinary preferences as plaintext, excluding links and photo identities.
- `security/` encrypts private GUI data and provides key-protection adapters.
- `desktop/` provides OS-specific wallpaper, browser, and file-manager calls.
- `gui/` provides the Qt window and system tray, with background workers.
- `worker.py` performs one operation and exits; it never imports Qt.
- `tray.py` provides only the resident tray; it never imports Pillow or the vault.
- `scheduling.py` registers per-user OS schedules.
- `processes.py` launches roles and locks concurrent state changes. An unlocked
  password key can travel only through a child process's stdin pipe.

The CLI catches expected errors and exits nonzero. The library raises errors:
the caller must not mistake an incomplete list or a failed download for success.
Album and image requests share the same HTTP client. Tests can inject a client
with synthetic responses without accessing an account.

Application code uses `PhotosClient` rather than handling Google responses.
The original `album.py` and `http.py` import paths remain as compatibility
modules for existing callers.

The data layout and `snAcKc` pagination request follow the public protocol
reference at https://github.com/vikas5914/google-photos-album-image-url-fetch.
This is an unofficial integration, so validate parsing and pagination when
Google changes its shared-album pages.
