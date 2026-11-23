#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(uname -s)" != Linux ] || [ "$(id -u)" = 0 ]; then
    printf '%s\n' 'Run uninstall as your normal Linux desktop user, without sudo.' >&2
    exit 1
fi
if [ ! -x "$project_dir/.venv/bin/python" ]; then
    printf '%s\n' 'The checkout environment is missing. Restore it with install.sh, then retry uninstall.' >&2
    exit 1
fi
"$project_dir/.venv/bin/python" -m timeshow._uninstall "$@"
rm -rf -- "$project_dir/.venv"
