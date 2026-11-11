"""One operation per process. Exiting releases photo buffers and all imports."""

import argparse
from pathlib import Path
import sys
import time

from .desktop import Desktop, app_directory, config_directory, runtime_directory
from .photos import PhotosError
from .player import CollectionExhausted, Player
from .processes import operation_lock
from .scheduling import Scheduler, publish_settings
from .security import DPAPIProtector, KeyringProtector, TPMProtector, Vault
from .worker_io import read_session_key, report


def open_vault(directory: Path, cache: Path, session_key: bytes | None = None) -> Vault:
    if session_key is not None:
        vault = Vault(directory, session_key, cache)
        vault.load_state()
        return vault
    mode = Vault.mode(directory)
    if mode is None:
        raise PhotosError("Open Timeshow settings to configure a photo vault first.")
    if mode == "password":
        raise PhotosError("Password vaults need the GUI for manual changes. Background rotation requires system credentials, DPAPI, or TPM2.")
    protector = {"dpapi": DPAPIProtector, "keyring": KeyringProtector, "tpm2": TPMProtector}.get(mode)
    if protector is None:
        raise PhotosError("Unknown vault protection method.")
    return Vault.open(directory, protector(), cache)


def perform(player: Player, action: str, scheduler: Scheduler) -> bool:
    if action == "tick":
        if not player.state.get("running", False):
            return False
        if time.time() - player.state.get("last_switch", 0) < player.state["interval"] - 2:
            return False
        if not player.state["images"]:
            player.refresh()
        player.next()
    elif action == "next":
        player.next()
    elif action == "previous":
        player.previous()
    elif action == "refresh":
        player.refresh()
    elif action == "exclude":
        player.restore_current()
        player.exclude_current()
        player.next()
    elif action == "web":
        player.restore_current()
        player.open_current_album()
    elif action == "pause":
        scheduler.disable()
        player.state["running"] = False
        player.save()
    elif action == "resume":
        if Vault.mode(player.vault.directory) == "password":
            raise PhotosError("Automatic rotation needs system credentials, DPAPI, or TPM2 protection.")
        scheduler.enable(player.state["interval"])
        player.state["running"] = True
        player.save()
    return True


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Perform one wallpaper operation and exit.")
    parser.add_argument("--action", default="tick", choices=["tick", "next", "previous", "refresh", "exclude", "web", "pause", "resume"])
    parser.add_argument("--session-key", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    directory = config_directory()
    try:
        key = read_session_key() if args.session_key else None
        with operation_lock(directory):
            vault = open_vault(directory, app_directory() / "cache", key)
            player = Player(vault, Desktop(), runtime_directory())
            player.screen_size = tuple(player.state.get("screen_size", [1920, 1080]))
            scheduler = Scheduler(directory)
            try:
                perform(player, args.action, scheduler)
            except CollectionExhausted:
                was_running = player.state.get("running", False)
                player.state["running"] = False
                player.save()
                publish_settings(player.state, directory)
                if was_running:
                    scheduler.disable()
                raise
            publish_settings(player.state, directory)
        return 0
    except PhotosError as error:
        report(str(error))
        return 1
    except Exception:
        report("The wallpaper operation failed. Check the network, vault, and desktop session.")
        return 1
