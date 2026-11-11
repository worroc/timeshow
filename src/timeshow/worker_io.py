"""Pipe I/O also works in a windowed Windows bundle without Python stdio objects."""

import ctypes
from ctypes import wintypes
import sys


def read_session_key() -> bytes:
    if sys.stdin is not None:
        return sys.stdin.buffer.read(128)
    if sys.platform != "win32":
        raise RuntimeError("The worker input pipe is unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.ReadFile.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(128)
    count = wintypes.DWORD()
    handle = kernel.GetStdHandle(wintypes.DWORD(-10))
    if not kernel.ReadFile(handle, buffer, 128, ctypes.byref(count), None):
        raise RuntimeError("Could not read the worker input pipe")
    return buffer.raw[:count.value]


def report(message: str) -> None:
    if sys.stdout is not None:
        print(message)
        return
    if sys.platform != "win32":
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteFile.restype = wintypes.BOOL
    body = (message + "\n").encode("utf-8")
    count = wintypes.DWORD()
    kernel.WriteFile(kernel.GetStdHandle(wintypes.DWORD(-11)), body, len(body), ctypes.byref(count), None)
