# Timeshow

A personal wallpaper changer for Windows and Linux. Add Google Photos shared
album links, select which albums to use, and rotate photos randomly at an interval.
The project is MIT licensed and provided **as is**, without warranty.
The window title, **Help → About Timeshow**, and tray tooltip show the app
version. Close the app and quit its tray after upgrading, then reopen it to load
the new version.

## Install on Ubuntu from a release

The **0.1.1** release package is for **Ubuntu 26.04, amd64** (64-bit Intel or AMD).
Python is included in the app bundle. Python and uv do not need to be installed.
The package requires glibc 2.43. It does not support Ubuntu 22.04 or 24.04.

1. Open [GitHub Releases](https://github.com/worroc/timeshow/releases/latest).
2. Expand **Assets**. Download `timeshow_0.1.1_amd64.deb` and `SHA256SUMS`.
3. If Timeshow is open, pause rotation, close its window, and choose **Quit tray**.
4. Open a terminal in the download folder and run:

   ```sh
   cd ~/Downloads
   sha256sum --check SHA256SUMS
   sudo apt install ./timeshow_0.1.1_amd64.deb
   ```

   The checksum should report **OK**. Stop if it reports a mismatch. `apt` installs
   the package and its required system libraries. Package installation needs
   administrator access; running Timeshow does not.

5. Open **Timeshow** from the application menu, or run `timeshow` in a terminal.
   The window title and **Help → About Timeshow** should show **0.1.1**.
6. Add albums, refresh the photo list, then press **Start**.

Download from **Releases → Assets** to install the app. The **Source code** archives
contain the project sources, not an installable package. The **Actions** page also
has build artifacts, but a release download does not require opening an Actions run.

To upgrade, download the newer `.deb`, close the window and tray, and install it
with `sudo apt install ./<downloaded-file>.deb`. Settings, albums, and history are
kept. Reopen the app after upgrading. To reinstall the same version, add
`--reinstall` to the `apt install` command.

To remove the app:

```sh
sudo apt remove timeshow
```

`sudo apt purge timeshow` also removes package-owned system configuration.
Both commands keep your private user data and credential-store key. See
[Private storage](#private-storage) for the user folders. The package manager
does not delete those folders or the key.

If you previously installed from a checkout, first run `./uninstall.sh --keep-data`
in that checkout to remove its old launchers and user service. Then install the
release package. Existing user data is preserved.

## Install on Windows from a release

The Windows test installer is **Timeshow-0.1.2-Setup.exe**, for 64-bit Windows 10
(version 1809 or newer) and Windows 11.

1. Open [release v0.1.2](https://github.com/worroc/timeshow/releases/tag/v0.1.2).
2. Under **Assets**, download `Timeshow-0.1.2-Setup.exe` and `SHA256SUMS-windows`.
3. In PowerShell, run `Get-FileHash .\Timeshow-0.1.2-Setup.exe -Algorithm SHA256`
   in the download folder. Compare the hash with `SHA256SUMS-windows`.
4. Close any older Timeshow window and choose **Quit tray**, then run the installer.
5. Follow the wizard. A desktop shortcut is optional. Open **Timeshow** from Start.

Python is included, and uv is not needed on the target machine. The installer
uses `%LOCALAPPDATA%\Programs\Timeshow` for the current user. Administrator access
is not needed. Start-menu and tray login shortcuts are included. The app does not
start wallpaper rotation until you press **Start**. The title and About dialog
show **0.1.2**. The installer is not code-signed.

To upgrade, pause rotation, close the window and tray, and run the newer installer.
To uninstall, use **Settings → Apps → Installed apps → Timeshow → Uninstall**.
The uninstaller removes the scheduled task, app files, and shortcuts. It keeps
settings, encrypted albums/history, the protected key, and downloaded images.
Rotation is marked paused without unlocking the vault. If a wallpaper change is
still active, let it finish and retry uninstall.

## Install from a checkout

Clone this repository and run the installer for your OS. It installs
[uv](https://docs.astral.sh/uv/getting-started/installation/) from the official
installer if needed, then downloads Python and dependencies into an isolated
environment. Linux needs curl for this bootstrap step.

Linux (Ubuntu/GNOME or KDE Plasma):

```sh
./install.sh
```

Windows, from PowerShell in the checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The scripts create an application-menu or Start-menu shortcut. They do not need
administrator access. Keep the checkout in place: the shortcuts use its `.venv`.
Qt needs the normal desktop graphics libraries. On Ubuntu, install
`libegl1 libopengl0 libxcb-cursor0` if the platform plugin reports missing libraries.
KDE needs `qdbus6` or `qdbus` for wallpaper changes. Other Linux desktops are not
implemented. Both Wayland and X11 use the desktop's own wallpaper API.

Launch manually with:

```sh
uv run --extra gui timeshow-gui
```

## Use

1. Open Timeshow. Secure local storage is set up automatically for your account.
2. Add one or more link-shared albums on the Albums tab. The link field is hidden.
3. Press **Refresh photo list**. All pages must load before the new list is saved.
4. Set the interval and framing in Settings. Choose an optional date range in Filters.
5. Press **Start** to change the wallpaper immediately and begin rotation, or **Next** for one change.

The Filters tab has calendar pickers and explanations. Both end dates are included.
Clear a date for no limit. Photos without a capture date are skipped while a limit
is set. The match count uses saved filters and enabled albums, excluding removed
photos. Capture dates and photo information now use your local time zone instead
of UTC. Photos near midnight may therefore match a different day than before.
In Settings, **Open Config** opens your config folder beside **Reset viewing history**.

Next chooses an unseen image. History survives restarts and image deletion.
Previous explicitly revisits history; Next moves forward through it before choosing
another unseen image. When every eligible image has appeared, rotation pauses.
Use Reset viewing history only when you want to allow repeats.

After a successful switch, the previous download and rendered wallpaper file are
deleted directly, without using the trash. Only the current image is retained.
Previous downloads the earlier photo again. A failed switch keeps the old image.
Deletion does not guarantee forensic erasure on SSDs or remove OS-cached copies.
Manually exported images and the separate CLI PoC outputs are not removed.

Controls include image information, saving an unencrypted copy, showing the local
wallpaper file, opening its source album in a browser, and excluding the current
photo. Exclusion removes the local download and prevents future rotation;
it never deletes anything from Google Photos. Photo-specific browser links,
location filters, and people filters are not available from this integration.

The tray icon offers Next, Previous, Start/Pause, Open album in browser, Settings,
and Quit tray. The tray is a separate process. Closing the GUI exits it and frees
its image buffers and vault key; the tray stays available. Quitting the tray does
not cancel a schedule. Use Pause to stop scheduled switching.

Automatic rotation uses a systemd **user timer** on Linux and Task Scheduler
with an **interactive, limited user** task on Windows. Each task launches one
worker, which changes the wallpaper and exits. No image-processing or GUI process
stays resident between switches. Intervals use whole minutes (1–1439).

The installer adds only the tray to your per-user login startup. It does not enable
wallpaper rotation until you press Start. Opening settings does not start a second
rotation loop. The worker and GUI use a cross-process lock to protect history.

## Private storage

All GUI and worker configuration stays in user space, outside the repository:

- Linux config: `$XDG_CONFIG_HOME/timeshow` or `~/.config/timeshow/`.
- Windows config: `%APPDATA%\Timeshow\` (normally `AppData\Roaming\Timeshow`).
- Linux image cache: `$XDG_DATA_HOME/timeshow/cache` or
  `~/.local/share/timeshow/cache/`.
- Windows image cache: `%LOCALAPPDATA%\Timeshow\cache\`.

`settings.json` contains ordinary preferences: scheduling, interval, framing,
date filters, and screen size. `key.json` holds
the wrapped key metadata. `state.enc` holds private album configuration, image
metadata and history. Album links and photo identities never enter settings.json.
The older GUI vault path is not automatically moved or overwritten.

Album links, candidate metadata, and viewing history use authenticated encryption.
Settings and downloaded images are plaintext. New installations protect the
encryption key automatically with Windows account protection (DPAPI) or the
Linux desktop's secure credential store. Users do not need to create a vault or
choose a protection method. The checkout installers set this up before creating
shortcuts. Packaged applications do it on first launch. Linux needs an installed,
unlocked secure desktop password store; setup fails clearly if it is unavailable.
There is no fallback to plaintext storage.

Existing encrypted storage keeps its original protection method:

- **Password:** portable; entered when the GUI opens; at least 12 characters.
  Manual Next/Previous can pass the unlocked key to a child worker over stdin.
  Scheduled tasks cannot unlock a password vault, so background Start refuses this
  mode. The password or unlocked key is never saved to enable unattended work.
- **System credential store:** requires an available, unlocked secure backend.
- **Windows DPAPI:** bound to the Windows user. This is not a promise of TPM backing.
- **Linux TPM2 (experimental):** requests `systemd-creds --user --with-key=tpm2`.
  Systemd 259 rejects this combination before checking hardware. TPM protection
  is not validated, even on a machine with a TPM. Use the system credential store
  or a password until a working hardware path is verified. Failures never silently
  change to software protection.

There is no key-recovery feature. Keep original photos in Google Photos.
The protection method is fixed when the vault is created. System credential or
hardware protection is needed for unattended switching.

Normal installation, login startup, GUI use, scheduling, and wallpaper changes
require **no root or administrator privileges**. Installing missing Linux system
libraries may require an administrator once. TPM device permissions or older
systemd configurations can also require machine setup; TPM mode is optional.

The current wallpaper must be readable by the desktop. On Linux the app uses
`$XDG_RUNTIME_DIR/timeshow` when available; otherwise it uses its private runtime
directory. Windows can keep its own wallpaper cache. These copies and manually
exported photos are plaintext. Encryption does not protect an unlocked desktop,
screenshots, malware, or a compromised operating system.

Shared links are access secrets: anyone obtaining one can view its album. Local
encryption does not change Google's sharing rules. Disable link sharing in Google
Photos to revoke a link. Do not put album links or personal data into source,
issues, screenshots, or logs. No telemetry is implemented.

## Uninstall on Linux

Run `./uninstall.sh` from the checkout as your normal user. It stops this checkout's
GUI and tray, disables rotation, removes user launchers, the icon, scheduler files,
and the checkout's `.venv`. It asks before deleting settings, albums, history,
downloaded images, rendered wallpapers, and the saved credential-store key.
The default answer keeps user data. No administrator access is needed.

Use `./uninstall.sh --keep-data` without a prompt, or `./uninstall.sh --yes` to
also delete user data. A credential-store failure keeps data for a retry.
The checkout, exported images, and `.private/` PoC files are kept. Select another
wallpaper in desktop Settings if needed. This helper removes checkout installs.
For a `.deb` install, use the package-manager commands below.

## Download PoC

The original dependency-free CLI remains available:

```sh
python3 src/main.py
python3 src/main.py --help
```

It reads `.private/album-url.txt`, lists candidates, downloads exactly one random
image into `.private/output/`, and exits. Unlike the GUI, its outputs are plaintext.
The GUI does not automatically import or delete these old PoC files.

## Build distributable applications

Build on each target OS. PyInstaller bundles Python and dependencies, so users of
the resulting app do not need Python or uv:

```sh
uv sync --extra gui --group build
uv run python src/build_bundle.py
```

The output is `dist/Timeshow/`. Distribute the whole directory with the license
files. Run `Timeshow.exe` on Windows or `Timeshow` on Linux. The application uses
dynamic Qt libraries; bundled third-party components retain their own licenses.
Build Linux packages on the oldest supported distribution, not a newer system.

### Debian and Ubuntu package

Build on Debian or Ubuntu with `dpkg-deb` installed:

```sh
uv run --extra gui --group build python src/build_deb.py
```

This reuses the bundle builder and creates `dist/timeshow_0.1.2_amd64.deb`
on an amd64 machine. Both the package version and filename come from
`pyproject.toml`; the architecture comes from the build machine. Build on each
target architecture. To package a fresh bundle that was already built:

```sh
uv run --extra gui --group build python src/build_deb.py --bundle dist/Timeshow
```

The build checks that the bundled UI version matches `pyproject.toml`. Rebuild
the desktop bundle after changing the version.

The package includes Python, dependencies, license notices, desktop icons,
application launchers, tray login startup, and a systemd **user** service.
Only the timer and user settings are written in the user's home folder.
It requires the build machine's glibc version or newer, so build on the oldest
Ubuntu/Debian release you want to support. CI builds on Ubuntu 22.04.

Building needs no administrator access. System-wide package installation and
removal use the normal package manager and require administrator access:

```sh
sudo apt install ./dist/timeshow_0.1.2_amd64.deb
sudo apt remove timeshow
# To also remove package-owned system configuration:
sudo apt purge timeshow
```

Run `timeshow` or open Timeshow from the application menu. Python and uv are not
needed on the target machine. Wallpaper changes and scheduling run as the logged-in
user. Installing does not enable wallpaper rotation.

Before moving from a checkout install, run `./uninstall.sh --keep-data` there to
remove its old launchers and user service. The package uses the same user data
locations. Pause rotation and close Timeshow before removing or upgrading it.
Remove/purge keep each user's settings, encrypted albums/history, image cache,
and credential-store key. Package scripts do not inspect or delete home folders.
The existing checkout installer remains available for installation without sudo.

### Windows installer build

On Windows, install [Inno Setup](https://jrsoftware.org/inno-setup) and run:

```powershell
uv run --extra gui --group build python src/build_windows_installer.py
```

To reuse a fresh bundle, add `--bundle dist/Timeshow`. The builder reads the version
from `pyproject.toml`, rejects bundles with a different version, and creates
`dist/Timeshow-0.1.2-Setup.exe` plus `dist/SHA256SUMS-windows`. It packages only the
bundle and dependency notices. `src/windows_installer.iss` defines the per-user
installation, shortcuts, and removal behavior. Inno Setup is used under its
[license](https://github.com/jrsoftware/issrc/blob/main/license.txt).

The Windows GitHub Actions job compiles the installer and tests a silent install,
reinstall, paused worker, schedule removal, and uninstall with synthetic data.
It uploads **Timeshow-Windows-installer** as a build artifact. This build runs on
GitHub's Windows runner, so development can stay on Linux.

The GitHub Actions workflow runs checks and builds separate Windows and Linux
artifacts. It does not publish a release or upload local data. Release binaries
are not code-signed by this project. The repository is hosted at
[worroc/timeshow](https://github.com/worroc/timeshow). Open tasks are tracked in
[GitHub Issues](https://github.com/worroc/timeshow/issues), including validation
on real Windows and Ubuntu desktops and optional Linux TPM2 protection.

## Structure and tests

- `src/timeshow/photos/`: enclosed `list_images` and `pull_image` library.
- `src/timeshow/player.py`: random selection, history, filters, and cache policy.
- `src/timeshow/security/`: encrypted vault and key-protection adapters.
- `src/timeshow/desktop/`: Windows and Linux desktop adapters.
- `src/timeshow/gui/`: Qt window, background workers, and tray actions.
- `src/timeshow/worker.py`: one operation per process, without Qt imports.
- `src/timeshow/tray.py`: independent tray, without the image engine or vault key.
- `src/timeshow/scheduling.py`: per-user scheduler registration.
- `src/timeshow/app.py`: original one-image CLI workflow.

Each library has its own README. Tests use synthetic data and fake desktop
adapters, never personal albums or real wallpaper changes.

```sh
uv run --extra gui python -m unittest discover -s tests -v
```

For headless GUI tests on Linux, set `QT_QPA_PLATFORM=offscreen`.

CI also checks native Windows DPAPI protection, windowed worker pipes, and both
packaged workers. Linux checks use a temporary GNOME settings store. The optional
Linux service tests verify generated systemd units and unlock a vault through a
private GNOME keyring from a child process:

```sh
TIMESHOW_TEST_SYSTEMD_VERIFY=1 TIMESHOW_TEST_SECRET_SERVICE=1 \
  dbus-run-session -- uv run --extra gui python -m unittest discover \
  -s tests -p test_linux_integration.py -v
```

These service tests need `systemd-analyze`, `dbus-run-session`,
`gnome-keyring-daemon`, `gsettings`, and the GNOME desktop schemas. Restricted
sandboxes may prevent private services from starting. Tests do not change your
desktop or use your saved credentials. Login startup, visible tray behavior, and
actual scheduled wallpaper changes still need checks in a real desktop session.

After building, select the packaged worker for a smoke test:

```sh
TIMESHOW_TEST_BUNDLE="$PWD/dist/Timeshow/Timeshow" \
  uv run --extra gui python -m unittest discover -s tests -p test_bundle_integration.py -v
```

On Windows, set `TIMESHOW_TEST_BUNDLE` to `dist\Timeshow\Timeshow.exe`.
The smoke test checks a paused worker and a wrong key without changing wallpaper.

## Measure the footprint

```sh
uv run --extra gui python src/measure_footprint.py
```

The measurement uses synthetic data: 1,103 candidates and one 4000×3000 image,
rendered to a 1920×1080 wallpaper. It never downloads personal images or changes
your desktop. It runs fresh processes for the tray, GUI, and switch worker.

Linux source-process measurement (Python 3.14.4, Qt offscreen):

| Process | Resident memory | Peak memory |
| --- | ---: | ---: |
| Tray | 63.6 MiB | 63.6 MiB |
| GUI with preview | 139.5 MiB | 139.5 MiB |
| Switch worker | 49.8 MiB at completion | 178.2 MiB |

The synthetic switch took about 0.36 seconds, excluding network time. Over a
two-second idle sample, the tray consumed about 0.0008 CPU seconds. Closed GUI and
finished worker processes consume no process memory. RSS includes shared library
pages, so adding these figures can overstate total physical memory use. These are
Linux headless measurements, not Windows, packaged-build, or real-desktop results.

Photo retrieval uses an undocumented Google shared-page format and continuation
RPC; Google can change it. Video detection is best-effort. Display images are
not guaranteed archival originals. The protocol reference is
[google-photos-album-image-url-fetch](https://github.com/vikas5914/google-photos-album-image-url-fetch).
