#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from timeshow.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
