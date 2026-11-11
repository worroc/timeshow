#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["PySide6-Essentials>=6.8,<7", "cryptography>=44,<50", "keyring>=25,<26", "Pillow>=11,<13"]
# ///
from timeshow.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
