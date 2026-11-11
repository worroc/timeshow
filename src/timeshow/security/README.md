# Encrypted application storage

`Vault` encrypts album URLs, image metadata, and viewing history
with Fernet authenticated encryption from the cryptography library. A random
vault key is protected separately by one chosen `KeyProtector`:

- `PasswordProtector`: scrypt derives a wrapping key from a password. The password
  is entered on each launch and never saved. This works on both operating systems.
- `KeyringProtector`: saves the vault key in the desktop's system credential store.
  It refuses backends that do not advertise a positive security priority.
- `DPAPIProtector`: Windows user-bound encryption. This does not promise TPM backing.
- `TPMProtector` is experimental. It requests a TPM2 key using systemd-creds and
  never falls back to a software key. Systemd 259 rejects the current combination
  of `--user` and `--with-key=tpm2`, even before accessing hardware. This produces
  a specific setup error. Do not rely on TPM protection until a working hardware
  path is verified. The system credential store and password modes remain usable.

Failure to unlock raises an error. It never creates a replacement key for an
existing vault. If a password, system credential, or TPM key is lost, encrypted
data cannot be recovered. Keep originals in Google Photos.

Ordinary preferences are stored in plaintext `settings.json`, using an explicit
list of allowed fields. Downloads are readable files with hashed names. Only the
current download is retained after a successful wallpaper switch. Earlier files
are unlinked directly, together with their rendered wallpaper copies. A failed
desktop switch preserves the old files. Previous downloads the image again.
Legacy encrypted downloads remain readable until the next successful switch
removes them. Deletion does not guarantee forensic erasure or clear OS caches.

The app writes a readable copy of the current wallpaper to its runtime directory
because the OS must read it. Export is also intentionally plaintext. Windows may
keep its own wallpaper cache. This library does not protect an unlocked session,
screenshots, or a compromised operating system. Hardware tests are required before
depending on a TPM configuration.

The configuration and cache can live in separate user directories. Password
protection is interactive: only a GUI that has unlocked the vault can pass a key
through stdin for a manual worker. Scheduled workers require a system-protected
key, and never persist a password or unlocked key to enable automatic switching.

TPM tests always check explicit TPM selection, refusal of null-key credentials,
failure handling, and preservation of an existing vault after unlock failure.
The real hardware test is opt-in and currently exposes the systemd compatibility
problem described above:

```sh
TIMESHOW_TEST_TPM2=1 uv run --extra gui python -m unittest discover \
  -s tests -p test_tpm.py -v
```

Run it only on a Linux machine with an accessible TPM2 device. It creates a
temporary vault with synthetic history and checks reopening from a child process.
It does not modify an existing vault. A passing mocked test does not validate
hardware support. TPM1 is not supported by this adapter.

Systemd's [credential documentation](https://www.freedesktop.org/software/systemd/man/259/systemd-creds.html)
describes the encryption modes. The supported user-scoped key combinations are
checked in its [command-line implementation](https://github.com/systemd/systemd/blob/v259/src/creds/creds.c).
