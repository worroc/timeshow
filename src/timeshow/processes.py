"""Lightweight process launching and cross-process locking. No GUI imports."""

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from .photos import PhotosError
from .storage import private_directory


def command(mode: str, *arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mode", mode, *arguments]
    executable = Path(sys.executable)
    if sys.platform == "win32" and executable.with_name("pythonw.exe").exists():
        executable = executable.with_name("pythonw.exe")
    entry = Path(__file__).resolve().parents[1] / "desktop_main.py"
    return [str(executable), str(entry), "--mode", mode, *arguments]


def spawn(mode: str, *arguments: str) -> subprocess.Popen:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    return subprocess.Popen(command(mode, *arguments), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)


def run_worker(action: str, key: bytes) -> None:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    result = subprocess.run(command("worker", "--action", action, "--session-key"),
                            input=key, capture_output=True, timeout=300, **options)
    if result.returncode:
        message = result.stdout.decode("utf-8", errors="replace").strip()
        raise PhotosError(message or "The switch worker could not finish.")


@contextmanager
def operation_lock(directory: Path):
    private_directory(directory)
    descriptor = os.open(directory / "operation.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if sys.platform == "win32":
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise PhotosError("Another Timeshow operation is running. Try again shortly.") from None
        yield
    finally:
        os.close(descriptor)
