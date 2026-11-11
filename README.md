# Timeshow

A personal wallpaper changer for Windows and Linux. Add Google Photos shared
album links, select which albums to use, and rotate photos randomly at an interval.
The project is MIT licensed and provided **as is**, without warranty.

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

1. Create an encrypted local vault. Choose a password, system credential store,
   Windows account protection, or Linux TPM2 protection.
2. Add one or more link-shared albums on the Albums tab. The link field is hidden.
3. Press **Refresh photo list**. All pages must load before the new list is saved.
4. Set the interval, framing, and optional capture-date range.
5. Press **Start**, or **Next** for a single wallpaper change.

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
Settings and downloaded images are plaintext. The vault key is protected by the
selected method:

- **Password:** portable; entered when the GUI opens; at least 12 characters.
  Manual Next/Previous can pass the unlocked key to a child worker over stdin.
  Scheduled tasks cannot unlock a password vault, so background Start refuses this
  mode. The password or unlocked key is never saved to enable unattended work.
- **System credential store:** requires an available, unlocked secure backend.
- **Windows DPAPI:** bound to the Windows user. This is not a promise of TPM backing.
- **Linux TPM2:** uses `systemd-creds --user --with-key=tpm2`; requires a compatible
  systemd version, TPM hardware, and access permissions. It fails if unavailable;
  it never silently changes to software protection. Hardware validation remains
  necessary before relying on this mode.

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

The GitHub Actions workflow runs checks and builds separate Windows and Linux
artifacts. It does not publish a release or upload local data. Release binaries
are not code-signed by this project. The repository has no configured GitHub
remote yet; Issues and a Kanban project can be connected when it has one.

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
