"""Choose a process role before importing its heavier dependencies."""

import argparse
import importlib


def main() -> int:
    parser = argparse.ArgumentParser(description="Timeshow desktop application")
    parser.add_argument("--mode", choices=["gui", "worker", "tray", "uninstall"], default="gui")
    args, remaining = parser.parse_known_args()
    # Dynamic imports keep Qt out of workers and crypto/Pillow out of the tray.
    name = "_windows_uninstall" if args.mode == "uninstall" else args.mode
    module = importlib.import_module("timeshow." + name)
    if args.mode == "worker":
        return module.main(remaining)
    return module.main()
