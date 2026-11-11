"""Key protection adapters. No silent fallback between protection modes."""

import base64
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

try:
    import keyring
except ImportError:
    keyring = None

from ..photos import PhotosError


class KeyProtector(Protocol):
    mode: str

    def protect(self, key: bytes) -> dict: ...
    def unlock(self, record: dict) -> bytes: ...


class PasswordProtector:
    mode = "password"

    def __init__(self, password: str):
        self.password = password.encode("utf-8")

    def _fernet(self, salt: bytes) -> Fernet:
        derived = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(self.password)
        return Fernet(base64.urlsafe_b64encode(derived))

    def protect(self, key: bytes) -> dict:
        if len(self.password) < 12:
            raise PhotosError("Use a vault password of at least 12 characters.")
        salt = os.urandom(16)
        return {"salt": base64.b64encode(salt).decode(), "wrapped": self._fernet(salt).encrypt(key).decode()}

    def unlock(self, record: dict) -> bytes:
        try:
            return self._fernet(base64.b64decode(record["salt"])).decrypt(record["wrapped"].encode())
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise PhotosError("Incorrect vault password or damaged key file.") from None


class KeyringProtector:
    mode = "keyring"

    def _backend(self):
        if keyring is None:
            raise PhotosError("System credential support is not installed.")
        backend = keyring.get_keyring()
        module = type(backend).__module__.lower()
        if backend.priority <= 0 or "plaintext" in module or "keyrings.alt" in module:
            raise PhotosError("A secure system credential store is unavailable.")
        return backend

    def protect(self, key: bytes) -> dict:
        account = os.urandom(16).hex()
        try:
            self._backend().set_password("Timeshow", account, key.decode())
        except PhotosError:
            raise
        except Exception:
            raise PhotosError("Could not save the vault key in the system credential store.") from None
        return {"account": account}

    def unlock(self, record: dict) -> bytes:
        try:
            value = self._backend().get_password("Timeshow", record["account"])
        except PhotosError:
            raise
        except Exception:
            raise PhotosError("Could not read the system credential store.") from None
        if not value:
            raise PhotosError("The vault key is missing from the system credential store.")
        return value.encode()


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class DPAPIProtector:
    mode = "dpapi"

    def _transform(self, data: bytes, *, decrypt: bool) -> bytes:
        if sys.platform != "win32":
            raise PhotosError("Windows key protection is only available on Windows.")
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source = DataBlob(len(data), buffer)
        target = DataBlob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        if decrypt:
            result = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
        else:
            result = crypt.CryptProtectData(ctypes.byref(source), "Timeshow", None, None, None, 1, ctypes.byref(target))
        if not result:
            raise PhotosError("Windows could not unlock or protect the vault key.")
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            kernel.LocalFree(target.data)

    def protect(self, key: bytes) -> dict:
        return {"wrapped": base64.b64encode(self._transform(key, decrypt=False)).decode()}

    def unlock(self, record: dict) -> bytes:
        return self._transform(base64.b64decode(record["wrapped"]), decrypt=True)


class TPMProtector:
    mode = "tpm2"

    def _run(self, operation: str, data: bytes) -> bytes:
        if not sys.platform.startswith("linux"):
            raise PhotosError("This TPM adapter requires Linux and systemd-creds.")
        command = ["systemd-creds", operation, "--user", "--name=timeshow", "-", "-"]
        if operation == "encrypt":
            command.insert(2, "--with-key=tpm2")
        else:
            command.insert(2, "--refuse-null")
        try:
            return subprocess.run(command, input=data, capture_output=True, check=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            raise PhotosError("TPM key protection failed. Check TPM2 hardware, permissions, and systemd support.") from None

    def protect(self, key: bytes) -> dict:
        return {"wrapped": base64.b64encode(self._run("encrypt", key)).decode()}

    def unlock(self, record: dict) -> bytes:
        return self._run("decrypt", base64.b64decode(record["wrapped"]))
