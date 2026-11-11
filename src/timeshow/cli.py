"""Thin command-line interface. Private values never enter status output."""

import argparse
from pathlib import Path
import sys

from .app import download_one
from .http import TimeshowError


def main() -> int:
    parser = argparse.ArgumentParser(description="List album photos, download one random image, and exit.")
    parser.add_argument("--album-file", type=Path, default=Path(".private/album-url.txt"))
    parser.add_argument("--output", type=Path, default=Path(".private/output"))
    args = parser.parse_args()
    try:
        album_url = args.album_file.read_text().strip()
        if not album_url or "\n" in album_url:
            raise TimeshowError("Album file must contain exactly one shared album URL.")
        print("Listing album images...", flush=True)
        result = download_one(album_url, args.output)
    except TimeshowError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("Error: Could not read input, receive data, or write private output files.", file=sys.stderr)
        return 1
    print(f"Listed {result.candidate_count} images.")
    print(f"Downloaded one image: {result.image_path}")
    print("Stopped.")
    return 0
