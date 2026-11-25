# Timeshow library

The library lists photos in a Google Photos link-shared album and downloads one
random photo. It needs no Google account credentials or API keys.

- `photos/` is the enclosed retrieval library. Its public `PhotosClient` interface
  lists photo candidates and pulls one image. See `photos/README.md` for usage.
- `storage.py` writes private files atomically.
- `_version.py` reads the app version from project metadata or the frozen build's
  version file. The title, About dialog, and Debian package use the same version.
- `_uninstall.py` removes Linux user integration and optionally deletes user data
  and the saved credential key. `uninstall.sh` runs it before removing the venv.
- `_windows_uninstall.py` is the Windows installer's one-operation cleanup helper.
  It refuses cleanup while the GUI, tray, or worker is active, removes this user's
  scheduled task, and marks public settings paused. It never unlocks the vault
  or removes private data. The installer removes its own files after cleanup.
- `app.py` coordinates listing, random selection, and exactly one download.
- `cli.py` reads local configuration, runs the app, and prints non-private status.
- `player.py` manages GUI rotation, date filters, and current-image retention.
- `_rotation.py` builds a saved shuffled display order and cursor, replaces the
  old seen/history lists, preserves the valid prefix on refresh, and appends new
  shuffled cycles to the same list. Previous follows earlier entries without a
  depth limit. A cycle never starts with the last shown image unless only one
  eligible image exists.
- `_local.py` reads local photo folders and subfolders into the existing candidate
  records. It uses Pillow for dimensions and EXIF capture dates. File identities
  use a hash of the full path. Listing fails if an image or directory is unreadable.
  It never modifies source files. `Player.add_folder(label, path)` adds a folder
  to the same encrypted configuration, selection, and history as Google albums.
- `settings.py` stores ordinary preferences as plaintext, excluding links and photo identities.
- `security/` encrypts private GUI data and provides key-protection adapters.
- `_setup.py` initializes secure storage during installation or first launch.
  It uses DPAPI on Windows and the desktop credential store on Linux. Existing
  storage is preserved. Setup fails if secure storage is unavailable.
- `desktop/` provides OS-specific wallpaper, browser, and file-manager calls.
- `gui/` provides the Qt window and system tray, with background workers.
- `worker.py` performs one operation and exits; it never imports Qt.
- `tray.py` provides only the resident tray; it never imports Pillow or the vault.
  Its login launcher can request one worker when Change on startup is enabled.
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
