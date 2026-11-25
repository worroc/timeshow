# Desktop GUI

PySide6 provides one Qt interface for Windows and Linux. `Window` calls the
platform-independent `Player`. All network, encryption, and desktop operations
run on a worker thread. GUI widgets are updated only on the Qt GUI thread.

The interface manages multiple albums and local folders, date filters, intervals, framing,
playback history, exports, exclusions, and local-file location. The tray
menu provides Next, Previous, Pause/Resume, Open source, Settings, and
Quit tray. The tray lives in `timeshow.tray`, a separate process. Closing the
GUI exits it, releasing preview buffers and the unlocked vault key.

Sources offers Add album and Add folder. The folder picker adds a directory and
its subfolders to the same rotation. Checkboxes enable either kind of source.
Refresh photo list scans every enabled source before publishing changes.
Open source opens the Google album in a browser or the local folder in the file
manager. Local originals remain unchanged when copies are cleaned up or excluded.

Filters has optional From and To calendar pickers, Clear buttons, explanations,
and a count of matching photos. Bounds include both days in the local time zone;
this replaces UTC date matching. Undated photos are skipped only while a limit
is set. Settings has Open Config beside Reset viewing history. It opens the
config folder without exporting or decrypting data. Start switches immediately
before the schedule continues. A failed switch leaves the schedule enabled for
retry; exhausting the available photos pauses rotation.

Startup creates secure storage automatically if the installer has not done so.
Windows uses DPAPI; Linux uses the secure desktop credential store. Users do not
choose a protection method. Existing storage is preserved and unlocked with its
original method. Only existing password protection asks for a Timeshow password.
Passwords are never saved. No old PoC album or plaintext data is imported silently.
Start registers a per-user OS schedule. The scheduler launches `timeshow.worker`
for one change, then the worker exits. Manual Next/Previous also run in a child
process. A password vault passes its key through stdin for manual operations only.
It cannot enable unattended scheduling. The GUI has no rotation timer; its timer
only updates visible status while the window is open.
Location and people filters are not exposed because shared-album access does not
provide a reliable implementation of those features.

Run after installing the `gui` extra: `timeshow-gui` or `python -m timeshow.gui`.
Tests can construct `Window` with a temporary vault, fake photo source, and fake
desktop adapter. Use Qt's offscreen platform for headless GUI checks.
