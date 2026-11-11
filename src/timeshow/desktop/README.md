# Desktop adapters

The main application calls `Desktop` for wallpaper changes, showing files,
and opening a source album in a browser. The adapter chooses Windows, GNOME,
or KDE behavior. Unsupported Linux desktops produce a clear error.

Windows uses the system wallpaper API. GNOME uses GSettings. KDE uses the
Plasma scripting interface through qdbus. No shell evaluates file paths.

`app_directory()` stores private application data outside the checkout.
`config_directory()` uses XDG_CONFIG_HOME on Linux and APPDATA on Windows.
The readable current-image cache uses XDG_DATA_HOME or LOCALAPPDATA separately.
`runtime_directory()` chooses a per-user directory for the readable wallpaper
file needed by the desktop. On Linux it prefers XDG_RUNTIME_DIR, which is
normally backed by memory. Windows may keep its own wallpaper cache on disk.
Encryption at rest cannot protect pixels displayed by an unlocked desktop.

Scheduling uses standard-user privileges through a systemd user timer or an
interactive Windows scheduled task. It never requests root, SYSTEM, or an elevated
run level. Desktop or TPM system dependencies may need separate administrator setup.
