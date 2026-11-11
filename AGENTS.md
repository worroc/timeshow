# Working rules

- Read existing code before making changes. Keep sources under `src/`.
- Keep the app structured as a library with a thin command-line entry point.
- Give each new library a README describing its purpose and operation.
- Ask before changing APIs. Answer questions without changing files.
- Never commit album links, access keys, photos, media identifiers, personal
  metadata, account information, live response fixtures, or private logs.
- Store PoC inputs and outputs in `.private/`, which is git-ignored. GUI/worker
  config belongs in XDG_CONFIG_HOME/timeshow or APPDATA/Timeshow. Cache belongs in
  XDG_DATA_HOME/timeshow or LOCALAPPDATA/Timeshow. Use
  synthetic data in tests and examples. Never print private links or metadata.
- Keep private files owner-readable/writable and private directories owner-only
  on Linux. File permissions are not encryption. TPM protection is optional.
- Encrypt album links, image identities, and viewing history. Ordinary preferences
  and downloaded images are plaintext. After a successful wallpaper switch,
  delete old downloads and rendered wallpaper files directly, without the trash.
  Keep the old image if switching fails. Keep history to prevent random repeats.
- Never send private album links to web search or other unrelated services.
- Fail clearly if listing or pagination fails. Never silently sample an
  incomplete album or fall back to unrelated images.
- GUI scope: configure albums, rotate desktop wallpaper, keep persistent no-repeat
  history, encrypt private data, and provide tray controls on Windows and Linux.
  Keep OS calls behind desktop and key-protection adapters. Never write to Google.
- Keep the GUI, tray, and switch worker in separate processes. The worker exits
  after one operation. Only the tray stays resident between scheduled switches.
- Use user-level scheduling only. Never require elevation for normal installation
  or execution. Never store a password-vault key to enable unattended switching.
- Preserve the one-image CLI PoC. It is separate from the GUI and writes plaintext
  only to its explicitly documented private output directory.
- The project is MIT licensed and provided as is. Keep dependency license notices
  in distributable bundles. Do not package private inputs, images, or local state.
- Add `NO-COMMIT` comments to temporary debugging code and remove it before committing.
- Run relevant tests. Do not put live album data into tests.
- Use GitHub Issues for open tasks and GitHub Projects for Kanban when a repository
  is connected. Issues and project cards must contain no private information.
- Before committing, ask how many commits are wanted and obtain approval for
  the proposed messages. Do not commit or publish without authorization.
- Use simple language and short sentences in documentation and responses.
