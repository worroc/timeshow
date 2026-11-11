"""Platform boundary for wallpaper, browser, file manager, and app paths."""

from .platform import Desktop, app_directory, config_directory, runtime_directory

__all__ = ["Desktop", "app_directory", "config_directory", "runtime_directory"]
