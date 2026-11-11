#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'Use install.ps1 on Windows. This installer targets Linux.' >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    command -v curl >/dev/null 2>&1 || {
        printf '%s\n' 'Install curl, then run this installer again.' >&2
        exit 1
    }
    uv_installer=$(mktemp)
    trap 'rm -f "$uv_installer"' EXIT HUP INT TERM
    curl --proto '=https' --tlsv1.2 -fsSL https://astral.sh/uv/install.sh -o "$uv_installer"
    UV_UNMANAGED_INSTALL="$HOME/.local/bin" sh "$uv_installer"
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

cd "$project_dir"
uv sync --python 3.12 --extra gui
launcher_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$launcher_dir"
# A quoted Exec value handles checkout paths containing spaces. Reject desktop
# control characters rather than generating an invalid launcher.
case "$project_dir" in
    *'"'*|*'`'*|*'$'*|*'\'*|*'%'*)
        printf '%s\n' 'Installed. Launch with: uv run --extra gui timeshow-gui' >&2
        exit 0 ;;
esac
cat > "$launcher_dir/timeshow.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Timeshow
Comment=Rotate photos from your selected albums
Exec="$project_dir/.venv/bin/timeshow-gui"
Path=$project_dir
Terminal=false
Categories=Utility;Graphics;
StartupNotify=true
EOF
chmod 644 "$launcher_dir/timeshow.desktop"
autostart_dir="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$autostart_dir"
cat > "$autostart_dir/timeshow-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Timeshow tray
Exec="$project_dir/.venv/bin/timeshow-tray"
Terminal=false
EOF
printf '%s\n' 'Installed. Open Timeshow from your application menu.'
