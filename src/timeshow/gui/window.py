"""Qt interface and tray actions; the player owns application behavior."""

from datetime import datetime
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QDate, QLockFile, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStyle,
    QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from ..desktop import Desktop, app_directory, config_directory, runtime_directory
from .._version import APP_VERSION
from .._setup import _initialize_storage
from ..photos import PhotosError
from ..photos._image import image_extension
from ..player import CollectionExhausted, DisplayedPhoto, Player
from ..security import DPAPIProtector, KeyringProtector, PasswordProtector, TPMProtector, Vault
from ..storage import private_directory
from ..processes import operation_lock, run_worker, spawn
from ..scheduling import Scheduler, publish_settings
from ..ui_icon import app_icon
from ..worker import open_vault, perform


class UnlockDialog(QDialog):
    def __init__(self, directory: Path, cache_directory: Path | None = None):
        super().__init__()
        self.directory = directory
        self.cache_directory = cache_directory if cache_directory is not None else app_directory() / "cache"
        self.vault: Vault | None = None
        self.existing_mode = Vault.mode(directory)
        title = "Unlock Timeshow" if self.existing_mode else "Welcome to Timeshow"
        self.setWindowTitle(f"{title} {APP_VERSION}")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        title = QLabel("Enter your Timeshow password" if self.existing_mode else "Protect your photo data")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        text = QLabel("Album links and viewing history are encrypted.\nChoose how to protect the encryption key.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.mode = QComboBox()
        self.mode.addItem("Password — ask on each launch", "password")
        self.mode.addItem("System credential store", "keyring")
        if sys.platform == "win32":
            self.mode.addItem("Windows account protection (DPAPI)", "dpapi")
        if sys.platform.startswith("linux"):
            self.mode.addItem("Linux TPM2 (experimental; may be unsupported)", "tpm2")
        if self.existing_mode:
            index = self.mode.findData(self.existing_mode)
            if index < 0:
                raise PhotosError("This vault uses a protection method unavailable on this OS.")
            self.mode.setCurrentIndex(index)
            self.mode.setEnabled(False)
        else:
            self.mode.setCurrentIndex(self.mode.findData("dpapi" if sys.platform == "win32" else "keyring"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("At least 12 characters for a new vault")
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setPlaceholderText("Repeat password")
        layout.addWidget(self.mode)
        layout.addWidget(self.password)
        layout.addWidget(self.confirm)
        note = QLabel("Background rotation needs system credentials, DPAPI, or TPM2. Password vaults support manual changes while this window is open. Keep originals in Google Photos.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c44d45")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.unlock)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode_changed()
        if self.existing_mode == "password":
            self.mode.hide()
            self.password.setPlaceholderText("Timeshow password")
            text.setText("Enter the password you previously chose for Timeshow.")
            note.setText("Keep your original photos in Google Photos.")

    def mode_changed(self) -> None:
        password = self.mode.currentData() == "password"
        self.password.setVisible(password)
        self.confirm.setVisible(password and not self.existing_mode)

    def unlock(self) -> None:
        try:
            mode = self.mode.currentData()
            if mode == "password":
                if not self.existing_mode and self.password.text() != self.confirm.text():
                    raise PhotosError("The passwords do not match.")
                protector = PasswordProtector(self.password.text())
            else:
                protector = {"keyring": KeyringProtector, "dpapi": DPAPIProtector, "tpm2": TPMProtector}[mode]()
            self.vault = Vault.open(self.directory, protector, self.cache_directory)
        except (PhotosError, OSError) as error:
            self.error.setText(str(error) if isinstance(error, PhotosError) else "Could not access the vault directory.")
            return
        self.password.clear()
        self.confirm.clear()
        self.accept()


class Job(QThread):
    done = Signal(object, object)

    def __init__(self, operation: Callable):
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit(self.operation(), None)
        except Exception as error:
            # Do not expose network URLs, account data, or backend exception text.
            message = str(error) if isinstance(error, PhotosError) else "The operation failed. Check network, storage, and desktop access."
            self.done.emit(None, message)


class Window(QMainWindow):
    def __init__(self, player: Player, scheduler: Scheduler | None = None, isolated: bool = True):
        super().__init__()
        self.player = player
        self.busy = False
        self.scheduler = scheduler if scheduler is not None else Scheduler(player.vault.directory)
        self.isolated = isolated
        self.running = player.state.get("running", False)
        self.quitting = False
        self._thread: QThread | None = None
        self._outcome = (None, None)
        self._success: Callable | None = None
        self._pixmap = QPixmap()
        self.setWindowTitle(f"Timeshow {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1120, 760)
        self.setMinimumSize(480, 520)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.external_update)
        self._build()
        self._tray()
        self._load_settings()
        self.refresh_albums()
        restored = self.player.restore_current()
        if restored:
            self._display(restored)
        self._update_controls()
        self._state_stamp = self._stamp()
        self.timer.start(5000)
        if QApplication.primaryScreen():
            size = QApplication.primaryScreen().size()
            self.player.screen_size = (size.width(), size.height())

    def _button(self, text: str, action: Callable, layout: QHBoxLayout) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def _build(self) -> None:
        about = QAction("About Timeshow", self)
        about.triggered.connect(self.show_about)
        self.menuBar().addMenu("Help").addAction(about)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 16)
        header = QHBoxLayout()
        name = QLabel("Timeshow")
        name.setStyleSheet("font-size: 27px; font-weight: 700; color: #257d69;")
        header.addWidget(name)
        header.addStretch()
        self.mode_label = QLabel("Paused")
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.mode_label)
        layout.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.splitterMoved.connect(lambda *_: self._resize_preview())
        layout.addWidget(splitter, 1)
        display = QWidget()
        pane = QVBoxLayout(display)
        pane.setContentsMargins(0, 0, 16, 0)
        self.preview = QLabel("Add an album, refresh photos, then press Start.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(160, 100)
        self.preview.setWordWrap(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setStyleSheet("background: #18212a; color: #d8e2e8; border-radius: 12px; padding: 16px;")
        pane.addWidget(self.preview, 1)
        self.info = QLabel("No photo displayed")
        self.info.setWordWrap(True)
        pane.addWidget(self.info)
        controls = QHBoxLayout()
        self.previous_button = self._button("Previous", self.previous_photo, controls)
        self.start_button = self._button("Start", self.toggle, controls)
        self.next_button = self._button("Next", self.next_photo, controls)
        pane.addLayout(controls)
        actions = QHBoxLayout()
        self.web_button = self._button("Open album in browser", self.open_web, actions)
        self.export_button = self._button("Save image…", self.export, actions)
        self.locate_button = self._button("Show local file", self.reveal, actions)
        pane.addLayout(actions)
        self.exclude_button = QPushButton("Remove this photo from rotation")
        self.exclude_button.clicked.connect(self.exclude)
        pane.addWidget(self.exclude_button)
        splitter.addWidget(display)
        self.tabs = QTabWidget()
        self.tabs.setMinimumSize(280, 160)
        splitter.addWidget(self.tabs)
        self._album_tab()
        self._settings_tab()
        self._filters_tab()
        splitter.setSizes([740, 340])
        self.status = QLabel("Ready. Rotation starts only when you ask.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setStyleSheet(self.styleSheet() + "QPushButton { padding: 8px; } QLineEdit, QSpinBox, QComboBox { padding: 6px; } QTabWidget::pane { border: 1px solid #b9c8ce; }")

    def _album_tab(self) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        intro = QLabel("Choose which albums to include. Their links are stored securely on this computer.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.albums = QListWidget()
        self.albums.itemChanged.connect(self.album_changed)
        layout.addWidget(self.albums, 1)
        self.album_name = QLineEdit()
        self.album_name.setPlaceholderText("Album name")
        self.album_url = QLineEdit()
        self.album_url.setPlaceholderText("Google Photos shared album link")
        self.album_url.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.album_name)
        layout.addWidget(self.album_url)
        row = QHBoxLayout()
        self._button("Add album", self.add_album, row)
        self._button("Remove selected", self.remove_album, row)
        layout.addLayout(row)
        refresh = QPushButton("Refresh photo list")
        refresh.clicked.connect(self.refresh_photos)
        layout.addWidget(refresh)
        self.counts = QLabel()
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)
        note = QLabel("Anyone who obtains a shared link can access its album. Disable link sharing in Google Photos to revoke it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._add_tab(panel, "Albums")

    def _add_tab(self, panel: QWidget, title: str) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(panel)
        self.tabs.addTab(scroll, title)

    def _settings_tab(self) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        form = QFormLayout()
        self.interval = QSpinBox()
        self.interval.setRange(1, 1439)
        self.interval.setSuffix(" min")
        form.addRow("Change every", self.interval)
        self.fit = QComboBox()
        self.fit.addItem("Fill screen (crop)", "fill")
        self.fit.addItem("Fit whole photo", "fit")
        form.addRow("Framing", self.fit)
        layout.addLayout(form)
        apply = QPushButton("Save settings")
        apply.clicked.connect(self.save_settings)
        layout.addWidget(apply)
        self.protection = QLabel()
        self.protection.setWordWrap(True)
        layout.addWidget(self.protection)
        privacy = QLabel("Links and history are encrypted. Settings and the current image are readable. A successful switch deletes the previous download and wallpaper file. The OS may keep its own copy.")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        note = QLabel("Photos do not repeat automatically, even after restarting. Previous revisits history. Rotation pauses when all eligible photos have appeared.")
        note.setWordWrap(True)
        layout.addWidget(note)
        reset = QPushButton("Reset viewing history…")
        reset.clicked.connect(self.reset_history)
        history_row = QHBoxLayout()
        history_row.addWidget(reset)
        self._button("Open Config", self.open_config, history_row)
        layout.addLayout(history_row)
        restore = QPushButton("Restore excluded photos…")
        restore.clicked.connect(self.restore_excluded)
        layout.addWidget(restore)
        layout.addStretch()
        footer = QLabel(f"Timeshow {APP_VERSION} · MIT license · Provided as is")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self._add_tab(panel, "Settings")

    def _filters_tab(self) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        intro = QLabel("Only photos taken between these dates. Both days are included. Dates use your local time zone.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.after = self._date_field()
        self.before = self._date_field()
        for title, field in [("From", self.after), ("To", self.before)]:
            row = QHBoxLayout()
            row.addWidget(field, 1)
            self._button("Clear", lambda checked=False, editor=field: editor.setDate(editor.minimumDate()), row)
            form.addRow(title, row)
        layout.addLayout(form)
        for text in (
            "From includes that date and all later dates. To includes that date and all earlier dates. Use the calendar to choose a date.",
            "Dates use year-month-day: 2024-03-15 means March 15, 2024.",
            "No limit allows any date on that side. Use Clear to remove a limit. Photos without a known capture date are skipped while a limit is set.",
            "Filters apply to enabled albums. Previously shown and excluded photos stay out of automatic rotation.",
        ):
            note = QLabel(text)
            note.setWordWrap(True)
            layout.addWidget(note)
        apply = QPushButton("Save filters")
        apply.clicked.connect(self.save_settings)
        layout.addWidget(apply)
        self.filter_counts = QLabel()
        self.filter_counts.setWordWrap(True)
        layout.addWidget(self.filter_counts)
        layout.addStretch()
        self._add_tab(panel, "Filters")

    def _date_field(self) -> QDateEdit:
        field = QDateEdit()
        field.setCalendarPopup(True)
        field.setDisplayFormat("yyyy-MM-dd")
        field.setMinimumDate(QDate(100, 1, 1))
        field.setSpecialValueText("No limit")
        field.setDate(field.minimumDate())
        def show_current_month(value: QDate) -> None:
            if value == field.minimumDate():
                today = QDate.currentDate()
                field.calendarWidget().setCurrentPage(today.year(), today.month())
        field.dateChanged.connect(show_current_month)
        show_current_month(field.date())
        return field

    def _tray(self) -> None:
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(f"Timeshow {APP_VERSION} — paused")
        menu = QMenu(self)
        self.tray_actions = {}
        for name, text, callback in [
            ("next", "Next", self.next_photo),
            ("previous", "Previous", self.previous_photo),
            ("toggle", "Start", self.toggle),
            ("web", "Open album in browser", self.open_web),
            ("settings", "Settings", self.show_settings),
            ("quit", "Quit", self.quit),
        ]:
            action = QAction(text, self)
            action.triggered.connect(callback)
            menu.addAction(action)
            self.tray_actions[name] = action
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        # The resident tray lives in a separate process. Closing this window
        # releases Qt previews, encrypted state, and the unlocked vault key.

    def _load_settings(self) -> None:
        state = self.player.state
        self.interval.setValue(max(1, state["interval"] // 60))
        self.fit.setCurrentIndex(self.fit.findData(state["fit"]))
        for field, name in [(self.after, "after"), (self.before, "before")]:
            value = state.get(name, "")
            field.setDate(QDate.fromString(value, "yyyy-MM-dd") if value else field.minimumDate())
        mode = Vault.mode(self.player.vault.directory)
        protection = {"password": "Password", "tpm2": "TPM2 (experimental)"}.get(mode, "Your system account")
        self.protection.setText(f"Photo data protection: {protection}.\nPrivate data: {self.player.vault.directory}")

    def refresh_albums(self) -> None:
        self.albums.blockSignals(True)
        self.albums.clear()
        for album in self.player.state["albums"]:
            item = QListWidgetItem(album["label"])
            item.setData(Qt.ItemDataRole.UserRole, album["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if album["enabled"] else Qt.CheckState.Unchecked)
            self.albums.addItem(item)
        self.albums.blockSignals(False)
        self._counts()

    def _counts(self) -> None:
        state = self.player.state
        self.counts.setText(f"{len(self.player.eligible())} eligible · {self.player.remaining()} unseen\n"
                            f"{len(state['seen'])} shown · {len(state['excluded'])} excluded")
        enabled = {album["id"] for album in state["albums"] if album["enabled"]}
        excluded = set(state["excluded"])
        photos = [photo for key, photo in state["images"].items()
                  if key not in excluded and enabled.intersection(photo["album_ids"])]
        undated = sum(photo["capture_time_ms"] is None for photo in photos)
        self.filter_counts.setText(
            f"{len(self.player.eligible())} of {len(photos)} photos match ({undated} have no date). "
            "Counts use saved filters and enabled albums, excluding removed photos."
        )

    def _update_controls(self) -> None:
        current = self.player.current is not None
        self.tabs.setEnabled(not self.busy)
        for button in [self.previous_button, self.next_button, self.start_button]:
            button.setEnabled(not self.busy)
        for button in [self.web_button, self.export_button, self.locate_button, self.exclude_button]:
            button.setEnabled(current and not self.busy)
        self.start_button.setText("Pause" if self.running else "Start")
        self.mode_label.setText("Running" if self.running else "Paused")
        background = "#247a45" if self.running else "#626970"
        self.mode_label.setStyleSheet(
            f"background-color: {background}; color: white; "
            "font-weight: 600; padding: 6px 12px; border-radius: 8px;"
        )
        self.tray.setToolTip(f"Timeshow {APP_VERSION} — " + ("running" if self.running else "paused"))
        for name in ["next", "previous", "toggle", "web"]:
            self.tray_actions[name].setEnabled(not self.busy and (current or name != "web"))
        self.tray_actions["toggle"].setText("Pause" if self.running else "Start")

    def _submit(self, label: str, operation: Callable, success: Callable | None = None,
                external: bool = False) -> None:
        if self.busy or self.quitting:
            return
        self.busy = True
        self.timer.stop()
        self.status.setText(label)
        self._success = success
        self._outcome = (None, None)
        def guarded():
            if external:
                return operation()
            with operation_lock(self.player.vault.directory):
                self.player.reload()
                result = operation()
                publish_settings(self.player.state, self.player.vault.directory)
                return result
        self._thread = Job(guarded)
        self._thread.done.connect(self._capture)
        self._thread.finished.connect(self._finished)
        self._update_controls()
        self._thread.start()

    @Slot(object, object)
    def _capture(self, result, error) -> None:
        self._outcome = (result, error)

    @Slot()
    def _finished(self) -> None:
        thread = self._thread
        self._thread = None
        self.busy = False
        result, error = self._outcome
        if error:
            self.status.setText(error)
        else:
            self.status.setText("Done.")
            if self._success:
                self._success(result)
        if thread:
            thread.deleteLater()
        self.running = self.player.state.get("running", False)
        self._state_stamp = self._stamp()
        self._counts()
        self._update_controls()
        if self.quitting:
            QApplication.quit()
        else:
            self.timer.start(5000)

    def _stamp(self) -> int:
        path = self.player.vault.directory / "state.enc"
        return path.stat().st_mtime_ns if path.exists() else 0

    def external_update(self) -> None:
        if self.busy or self._stamp() == self._state_stamp:
            return
        self.player.reload()
        photo = self.player.restore_current()
        if photo:
            self._display(photo)
        self.running = self.player.state.get("running", False)
        self._state_stamp = self._stamp()
        self._counts()
        self._update_controls()

    def _switch(self, action: str):
        if self.isolated:
            try:
                run_worker(action, self.player.vault.session_key())
            finally:
                self.player.reload()
            return self.player.restore_current()
        return self.player.previous() if action == "previous" else self.player.next()

    def _display(self, photo: DisplayedPhoto) -> None:
        if photo is None:
            return
        self._pixmap = QPixmap.fromImage(QImage.fromData(photo.body))
        self._resize_preview()
        day = "Unknown date"
        if photo.capture_time_ms is not None:
            day = datetime.fromtimestamp(photo.capture_time_ms / 1000).strftime("%Y-%m-%d")
        self.info.setText(f"{photo.album or 'Photo'} · {photo.width} × {photo.height} · {day}")
        self.status.setText(f"Photo displayed. {self.player.remaining()} unseen photos remain.")

    def _resize_preview(self) -> None:
        if not self._pixmap.isNull():
            self.preview.setPixmap(self._pixmap.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "splitter"):
            # Leave enough room for the controls and a vertical scrollbar.
            minimum = max(self.tabs.widget(index).widget().minimumSizeHint().width()
                          for index in range(self.tabs.count()))
            scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
            self.tabs.setMinimumWidth(max(280, minimum + scrollbar + 2))
            narrow = self.width() < 900
            orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
            if self.splitter.orientation() != orientation:
                self.splitter.setOrientation(orientation)
                self.splitter.setSizes([300, 360] if narrow else [740, 340])
        self._resize_preview()

    def next_photo(self) -> None:
        self._submit("Selecting the next photo…", lambda: self._switch("next"), self._display,
                     external=self.isolated)

    def previous_photo(self) -> None:
        self._submit("Opening the previous photo…", lambda: self._switch("previous"), self._display,
                     external=self.isolated)

    def toggle(self) -> None:
        if self.busy:
            return
        def change():
            action = "pause" if self.player.state.get("running", False) else "resume"
            if self.isolated:
                try:
                    run_worker(action, self.player.vault.session_key())
                finally:
                    self.player.reload()
                return self.player.restore_current() if action == "resume" else None
            try:
                perform(self.player, action, self.scheduler)
            except CollectionExhausted:
                self.scheduler.disable()
                self.player.state["running"] = False
                self.player.save()
                raise
            return self.player.current if action == "resume" else None
        self._submit("Updating the user schedule…", change, self._display, external=self.isolated)

    def add_album(self) -> None:
        label, url = self.album_name.text(), self.album_url.text().strip()
        def saved(_):
            self.album_name.clear()
            self.album_url.clear()
            self.refresh_albums()
            self.status.setText("Album added. Refresh the photo list to load it.")
        self._submit("Saving album…", lambda: self.player.add_album(label, url), saved)

    def remove_album(self) -> None:
        item = self.albums.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            self._submit("Removing album…", lambda: self.player.remove_album(key), lambda _: self.refresh_albums())

    def album_changed(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        self._submit("Saving album selection…", lambda: self.player.enable_album(key, enabled), lambda _: self.refresh_albums())

    def refresh_photos(self) -> None:
        self._submit("Reading complete album lists…", self.player.refresh,
                     lambda count: self.status.setText(f"Photo list updated: {count} eligible images."))

    def save_settings(self) -> None:
        dates = [field.date().toString("yyyy-MM-dd") if field.date() != field.minimumDate() else ""
                 for field in (self.after, self.before)]
        if dates[0] and dates[1] and dates[0] > dates[1]:
            self.status.setText("From must be on or before To.")
            return
        values = (self.interval.value() * 60, self.fit.currentData(), *dates, 1)
        def configure():
            if self.player.state.get("running", False):
                self.scheduler.enable(values[0])
            self.player.state["screen_size"] = list(self.player.screen_size)
            self.player.configure(*values)
        self._submit("Saving settings…", configure)

    def open_config(self) -> None:
        directory = self.player.vault.directory
        def open_folder():
            private_directory(directory)
            self.player.desktop.open_folder(directory)
        self._submit("Opening the config folder…", open_folder)

    def open_web(self) -> None:
        self._submit("Opening the source album…", self.player.open_current_album)

    def reveal(self) -> None:
        if self.player.current:
            path = self.player.current.path
            self._submit("Opening the local folder…", lambda: self.player.desktop.reveal(path))

    def export(self) -> None:
        if not self.player.current:
            return
        extension = image_extension(self.player.current.body)
        name, _ = QFileDialog.getSaveFileName(self, "Save a readable copy", "photo" + extension,
                                             f"Image (*{extension})")
        if name:
            self._submit("Saving an unencrypted image copy…", lambda: self.player.export_current(Path(name)))

    def exclude(self) -> None:
        def operation():
            self.player.exclude_current()
            return self.player.next()
        self._submit("Excluding this photo and selecting another…", operation, self._display)

    def reset_history(self) -> None:
        answer = QMessageBox.question(self, "Reset history", "Allow previously shown photos to appear again?")
        if answer == QMessageBox.StandardButton.Yes:
            self._submit("Resetting history…", self.player.reset_history)

    def restore_excluded(self) -> None:
        answer = QMessageBox.question(self, "Restore photos", "Allow excluded photos back into the rotation?")
        if answer == QMessageBox.StandardButton.Yes:
            self._submit("Restoring excluded photos…", self.player.clear_exclusions)

    def show_settings(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentIndex(1)

    def show_about(self) -> None:
        QMessageBox.about(self, f"About Timeshow {APP_VERSION}",
                          f"Timeshow {APP_VERSION}\n\n"
                          "Rotate desktop wallpaper from your photo albums.\n"
                          "MIT license · Provided as is.")

    def tray_activated(self, reason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def quit(self) -> None:
        self.running = False
        self.timer.stop()
        self.quitting = True
        if self.busy:
            self.status.setText("Finishing the current operation before quitting…")
        else:
            QApplication.quit()

    def closeEvent(self, event) -> None:
        if self.quitting:
            event.accept()
        elif self.busy:
            self.quit()
            event.ignore()
        else:
            event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Timeshow")
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName("timeshow")
    app.setOrganizationName("Timeshow")
    app.setWindowIcon(app_icon())
    try:
        directory = config_directory()
        private_directory(directory)
        lock = QLockFile(str(directory / "gui.lock"))
        if not lock.tryLock(100):
            raise PhotosError("Timeshow is already running. Open it from the tray.")
        cache = app_directory() / "cache"
        vault = _initialize_storage(directory, cache)
        if vault is None:
            if Vault.mode(directory) == "password":
                dialog = UnlockDialog(directory, cache)
                if dialog.exec() != QDialog.DialogCode.Accepted or dialog.vault is None:
                    return 0
                vault = dialog.vault
            else:
                with operation_lock(directory):
                    vault = open_vault(directory, cache)
        window = Window(Player(vault, Desktop(), runtime_directory()))
        app.setQuitOnLastWindowClosed(True)
        spawn("tray")
        window.show()
        return app.exec()
    except (PhotosError, OSError) as error:
        QMessageBox.critical(None, "Timeshow", str(error) if isinstance(error, PhotosError) else "Could not access private app storage.")
        return 1
