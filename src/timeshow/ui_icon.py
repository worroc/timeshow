"""Shared packaged icon for the window, tray, and desktop launchers."""

from pathlib import Path

from PySide6.QtGui import QIcon


def app_icon() -> QIcon:
    return QIcon(str(Path(__file__).with_name("assets") / "timeshow.svg"))
