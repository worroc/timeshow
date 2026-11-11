# Desktop GUI

PySide6 provides one Qt interface for Windows and Linux. `Window` calls the
platform-independent `Player`. All network, encryption, and desktop operations
run on a worker thread. GUI widgets are updated only on the Qt GUI thread.

The interface manages multiple albums, date filters, intervals, framing,
playback history, exports, exclusions, and local-file location. The tray
menu provides Next, Previous, Pause/Resume, Open album in browser, Settings, and
Quit tray. The tray lives in `timeshow.tray`, a separate process. Closing the
GUI exits it, releasing preview buffers and the unlocked vault key.

Startup asks the user to create or unlock an encrypted vault outside the checkout.
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
