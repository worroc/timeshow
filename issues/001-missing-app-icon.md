# 001: Timeshow has no icon in the app menu, dock, and shortcuts

## Fix status

Implemented. The package has SVG and ICO assets. Linux launchers install the
icon and set Icon/StartupWMClass. GUI and tray set the desktop file name.
Windows shortcuts and bundle builds use the ICO. Automated checks cover Linux
launcher generation, icon sizes, and Qt rendering. Ubuntu dock/menu and native
Windows appearance still need retesting. Rerun install.sh to update launchers.

The Ubuntu tester later reported a missing desktop icon with the .deb install.
The original package was checked: its SVG asset and Icon=timeshow entries were
present. The installed shortcut was not available for inspection, so the exact
failure on the test machine is still unconfirmed.

The .deb launchers now point directly to /usr/share/pixmaps/timeshow.png.
The PNG is generated from the existing logo during packaging. A named PNG is
also installed in hicolor/256x256/apps for dock entries and existing shortcuts.
Package tests resolve each launcher's icon path inside the archive and check
that it is a readable, nonempty 256x256 PNG. The fix ships in patch version 0.1.1.
Install timeshow_0.1.1_amd64.deb to retest.

## Observed

Installed with `./install.sh` on Ubuntu, GNOME, Wayland.
The Timeshow entry in the application menu shows a generic icon.
The running window in the dock shows a generic icon too.

## Cause

The icon exists only as runtime drawing code: `app_icon()` in
`src/timeshow/ui_icon.py` paints a 64x64 QPixmap. The repo has no icon file.
So nothing outside the running Qt process can show it:

1. `install.sh` writes `timeshow.desktop` and `timeshow-tray.desktop` with no
   `Icon=` key. The launcher has no icon to show.
2. The app never calls `QGuiApplication.setDesktopFileName("timeshow")`.
   GNOME on Wayland ignores `setWindowIcon()`. It takes the icon from the
   `.desktop` file that matches the window's app id. With no match, the dock
   shows a generic icon even while the app runs.
3. `install.ps1` does not set `IconLocation` on the `.lnk` shortcuts.
   `Timeshow.spec` has no `icon=`. On Windows, Explorer and Start show the
   default exe icon.

`setWindowIcon(app_icon())` (window.py `main()`, `MainWindow`) and
`QSystemTrayIcon(app_icon())` (tray.py) still work. The tray icon and the X11
title bar are fine.

## Proposed fix

1. Add real icon files to the package, for example
   `src/timeshow/assets/timeshow.svg` (same design as `app_icon()`) and
   `timeshow.ico` for Windows. Include them in the package data.
2. Make `app_icon()` load the SVG file, so there is one source of truth.
   Or keep the drawing code and generate the files from it once.
3. `install.sh`:
   - copy the SVG to
     `${XDG_DATA_HOME:-~/.local/share}/icons/hicolor/scalable/apps/timeshow.svg`;
   - add `Icon=timeshow` and `StartupWMClass=timeshow` to `timeshow.desktop`;
     add `Icon=timeshow` to `timeshow-tray.desktop`;
   - run `gtk-update-icon-cache` / `update-desktop-database` if present
     (optional, ignore errors).
4. In GUI and tray `main()`: `app.setDesktopFileName("timeshow")` after
   creating `QApplication`.
5. `install.ps1`: set `$shortcut.IconLocation` (and the tray shortcut) to the
   `.ico` path. `Timeshow.spec`: `icon=` the same `.ico`.
6. Tests: the `.desktop` text has `Icon=`; the icon file exists in the package;
   `app_icon()` is not null.

## Check

- Run `./install.sh` again. Log out/in (or `killall -HUP gnome-shell` on X11).
- The menu entry shows the Timeshow icon.
- Start the GUI. The dock shows the same icon, not a generic one.
- Windows: the Start menu shortcut shows the icon.
