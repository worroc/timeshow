# 005: Install as a .deb; simple uninstall with uninstall.sh

## Status: Open — partially resolved

Completed work is published in
[v0.1.1](https://github.com/worroc/timeshow/releases/tag/v0.1.1): the Ubuntu 26.04
.deb, checksum, release installation guide, and checkout uninstall helper.

Remaining work:

- Make install.sh/uninstall.sh wrap apt for package installs, as requested below.
- Validate package installation, upgrade, removal, and purge in a clean Ubuntu
  session. Broader desktop checks remain tracked in
  [GitHub issue #3](https://github.com/worroc/timeshow/issues/3).
- Fix the half-screen layout test failure on the GitHub runners so CI can
  produce packages. The published package was built and checked locally.

## Implementation details

Partly implemented. uninstall.sh removes this checkout's user integration and
venv. It asks before deleting private data and the saved credential key; default
is keep. It supports --keep-data and --yes. Automated checks use temporary
directories and a fake credential store, including deletion failures.

The user subsequently requested .deb packaging explicitly. src/build_deb.py now
builds a native package using the version from pyproject.toml and the existing
bundle builder. It includes launchers, icons, notices, tray autostart, and a user
service. Packaged scheduling only writes a user timer. CI is configured to build
and upload the package, but its latest checked run is blocked by a layout test.
Package removal keeps user data. The checkout installers remain user-only;
install.sh/uninstall.sh do not invoke apt or sudo. Native package installation,
upgrade, removal, and desktop behavior still need testing in a clean Ubuntu session.

Local checks: the real .deb builds with version 0.1.1. Its extracted worker passes
the paused-state and wrong-key smoke tests. Automated tests check metadata,
root-owned payload paths, license files, private-data rejection, and user scheduling.
The bundle version must match pyproject.toml; that same version appears in the
window title and Help / About Timeshow. The local build requires glibc 2.43;
the CI build targets Ubuntu 22.04 instead.

## Problem

There is no way to uninstall Timeshow. `install.sh` spreads files over the
home folder, and the user must find and delete them by hand:

| What                     | Where                                              | Created by          |
|--------------------------|----------------------------------------------------|---------------------|
| Code + venv              | the checkout (`.venv`)                             | `install.sh`        |
| Menu entry               | `~/.local/share/applications/timeshow.desktop`     | `install.sh`        |
| Tray autostart           | `~/.config/autostart/timeshow-tray.desktop`        | `install.sh`        |
| Timer + service          | `~/.config/systemd/user/timeshow.{timer,service}`  | `Scheduler.enable()`|
| Settings + vault         | `~/.config/timeshow/`                              | app                 |
| Download cache           | `~/.local/share/timeshow/`                         | app                 |
| Current wallpaper        | `$XDG_RUNTIME_DIR/timeshow/`                       | app                 |
| Vault key                | keyring, service `Timeshow`                        | `KeyringProtector`  |

Also the checkout must stay in place, because the launchers point into its
`.venv`.

## Goal

- Timeshow is installed as a normal Linux app from a **.deb** package.
- It is removed like a normal app: `sudo apt remove timeshow` /
  `sudo apt purge timeshow`.
- `install.sh` and `uninstall.sh` are only **helpers** around the package.
- `uninstall.sh` removes everything, and **asks** whether to remove user data.

## Proposed design

### 1. The .deb package

- Build a self-contained app. Reuse `Timeshow.spec` (PyInstaller), so the
  package does not depend on the system Python or on uv.
- Layout:
  - `/opt/timeshow/` — the app (GUI, tray, worker executables)
  - `/usr/bin/timeshow`, `/usr/bin/timeshow-tray` — symlinks or small wrappers
  - `/usr/share/applications/timeshow.desktop` — with `Icon=timeshow`
    (see issue 001)
  - `/usr/share/icons/hicolor/scalable/apps/timeshow.svg` (issue 001)
  - `/etc/xdg/autostart/timeshow-tray.desktop` — tray autostart for all users
  - `/usr/lib/systemd/user/timeshow.service` — shipped by the package,
    `ExecStart=/opt/timeshow/... worker`
- `Depends:` the Qt runtime libraries (`libegl1`, `libopengl0`,
  `libxcb-cursor0`) and the keyring stack the app needs.
- Version from `pyproject.toml` / `.bumpversion.cfg`.
- Build script, e.g. `packaging/build-deb.sh` → `dist/timeshow_<ver>_amd64.deb`.
  Use `dpkg-deb --build` (simple) or `debhelper`.

### 2. Scheduler change

`Scheduler.enable()` writes the service file into the user home today. With the
package, the service is in `/usr/lib/systemd/user/`. The app should only write
a small **timer** with the interval (or a drop-in
`~/.config/systemd/user/timeshow.timer.d/interval.conf`), and enable/disable it.
Then `apt remove` does not leave a service pointing at deleted code.

### 3. Package maintainer scripts

- `postinst`: `update-desktop-database`, `gtk-update-icon-cache` (if present).
- `prerm`: for each logged-in user session nothing is required, but the
  service must not crash if the code is gone. Keep it simple: no per-user
  actions.
- `postrm purge`: remove only package-owned system files. **Do not** touch home
  folders (Debian policy; also a .deb cannot reach the user keyring).

### 4. `install.sh` (helper)

1. Build the .deb if `dist/*.deb` is missing (or download a release).
2. `sudo apt install ./dist/timeshow_<ver>_amd64.deb`
3. Remove leftovers of the old checkout-based install, if found:
   `~/.local/share/applications/timeshow.desktop`,
   `~/.config/autostart/timeshow-tray.desktop`, old
   `~/.config/systemd/user/timeshow.service`.

### 5. `uninstall.sh` (helper) — new

Runs as the normal user (calls `sudo` only for apt):

1. Stop rotation: `systemctl --user disable --now timeshow.timer`; remove the
   user timer / drop-in; `systemctl --user daemon-reload`.
2. Stop running Timeshow processes (GUI, tray) for this user.
3. `sudo apt purge -y timeshow`.
4. Remove old checkout-install leftovers (same list as install.sh step 3).
5. Ask:
   `Remove your Timeshow data (settings, album links, history, cache, key)? [y/N]`
   - Default **No**.
   - On **Yes**: delete `~/.config/timeshow`, `~/.local/share/timeshow`,
     `$XDG_RUNTIME_DIR/timeshow`, and the keyring entry (service `Timeshow`).
   - Add `--yes` / `--keep-data` flags for non-interactive use.
6. Print a note: GNOME may still point at the deleted wallpaper file; choose a
   new wallpaper in Settings.

Better: put steps 1, 2 and 5 into the app itself as
`timeshow --remove-user-data` (it already knows all paths and the keyring
account), and let `uninstall.sh` call it before `apt purge`. Then paths are
defined in one place (`desktop/platform.py`, `security/keys.py`).

### 6. Windows

Out of scope here. `install.ps1` can get a matching `uninstall.ps1` later.

## Tests

- Build the .deb in CI; `dpkg-deb --contents` lists the expected files.
- Install / remove / purge in a clean Ubuntu container: no files left outside
  the home folder.
- `timeshow --remove-user-data` deletes exactly the listed paths and the
  keyring entry, and does nothing when they are missing.
- `uninstall.sh` with "No": package gone, user data kept. With "Yes": all gone.

## Docs

Update `README.md`: install with `install.sh` or `apt install ./timeshow*.deb`;
uninstall with `uninstall.sh` or `apt purge timeshow`; list which user folders
stay after `apt purge`.
