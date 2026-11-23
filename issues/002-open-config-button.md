# 002: Add an "Open Config" button next to "Reset viewing history…"

## Status: Resolved

Implemented. Open Config is beside Reset viewing history in Settings. It opens
the active vault/config folder through Desktop.open_folder. Automated checks
cover the button and Linux/Windows command arguments. Released in
[v0.1.1](https://github.com/worroc/timeshow/releases/tag/v0.1.1).
Native desktop validation remains tracked in the
[Ubuntu validation issue](https://github.com/worroc/timeshow/issues/3).

## Request

On the Settings tab, add a button **Open Config** next to
**Reset viewing history…**. It opens the Timeshow config folder in the
system file manager.

## Where

- Button: `src/timeshow/gui/window.py`, Settings tab in `_build()`. Today
  `reset` ("Reset viewing history…") and `restore` are each added to the
  vertical `layout` on their own.
- Folder: `config_directory()` in `src/timeshow/desktop/platform.py`
  (`$XDG_CONFIG_HOME/timeshow` or `~/.config/timeshow` on Linux,
  `%APPDATA%\Timeshow` on Windows).
- Existing pattern to reuse: `reveal()` in `window.py` ("Show local file")
  calls `self.player.desktop.reveal(path)` through `self._submit(...)`.

## Proposed change

1. Put `reset` and the new button in one `QHBoxLayout`, so they sit side by
   side:

   ```python
   history_row = QHBoxLayout()
   history_row.addWidget(reset)
   self._button("Open Config", self.open_config, history_row)
   layout.addLayout(history_row)
   ```

2. Add `open_folder(path)` to the desktop class in `platform.py`. Do not
   reuse `reveal(path)`: it opens the *parent* of the path on Linux and
   selects the item on Windows.
   - Linux: `run_command(["xdg-open", str(path)])`
   - Windows: `run_command(["explorer.exe", str(path)])`
     (or `os.startfile`)

3. Add `MainWindow.open_config()`:
   - `directory = config_directory()`
   - make sure it exists with `private_directory(directory)`, the same
     helper `main()` uses, so permissions stay private;
   - `self._submit("Opening the config folder…", lambda: self.player.desktop.open_folder(directory))`.

4. Errors: if the file manager fails, show the same error the other desktop
   actions show (`PhotosError` through `_submit`). Nothing in app state
   changes, so no rollback is needed.

## Notes

- The config folder holds the encrypted vault and the readable settings.
  The button only opens the folder. It does not decrypt or export anything.
- Update the Settings section in `README.md` and `src/timeshow/gui/README.md`.

## Tests

- `tests/test_desktop_app.py`: the Settings tab has an "Open Config" button
  in the same row as "Reset viewing history…"; clicking it calls
  `desktop.open_folder` with `config_directory()` (mock the desktop).
- Platform test: `open_folder` runs `xdg-open <dir>` on Linux and
  `explorer.exe <dir>` on Windows (mock `run_command`).

## Check

Open Settings. **Open Config** is to the right of **Reset viewing history…**.
Click it. The file manager opens `~/.config/timeshow` (Linux) or
`%APPDATA%\Timeshow` (Windows).
