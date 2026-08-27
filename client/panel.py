"""Le panneau de contrôle.

C'est la seule fenêtre avec laquelle on interagit : l'overlay, lui, est traversé par
les clics par construction. Le glisser-déposer vise donc le panneau, jamais l'overlay.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QTabWidget, QVBoxLayout, QWidget)

from . import fonts, platform, theme
from .settings import AUTHOR_POSITIONS, CORNERS

log = logging.getLogger(__name__)

GIGA = 1024 ** 3


def human(size: float) -> str:
    for unit in ("o", "Kio", "Mio", "Gio"):
        if size < 1024 or unit == "Gio":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} Gio"


def section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")
    return label


class Row(QWidget):
    """Une ligne « libellé — contrôle — valeur »."""

    def __init__(self, label: str, widget: QWidget, value: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        caption = QLabel(label)
        caption.setMinimumWidth(84)
        layout.addWidget(caption)
        layout.addWidget(widget, 1)
        self.value = QLabel(value)
        self.value.setObjectName("value")
        self.value.setMinimumWidth(46)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.value)


class DropZone(QWidget):
    """Zone de dépôt de fichier. Le bouton reste là pour ceux qui préfèrent parcourir."""

    file_chosen = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setProperty("hover", "false")
        self.setMinimumHeight(96)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("Glissez un fichier ici")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel("image ou vidéo")
        hint.setObjectName("value")
        hint.setAlignment(Qt.AlignCenter)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(browse, alignment=Qt.AlignCenter)

    def _repaint_state(self, hovering: bool) -> None:
        self.setProperty("hover", "true" if hovering else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._repaint_state(True)

    def dragLeaveEvent(self, event) -> None:
        self._repaint_state(False)

    def dropEvent(self, event) -> None:
        self._repaint_state(False)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.file_chosen.emit(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Envoyer un média", "",
            "Images et vidéos (*.png *.jpg *.jpeg *.gif *.webp *.mp4 *.webm *.mov *.mkv);;"
            "Tous les fichiers (*)",
        )
        if chosen:
            self.file_chosen.emit(Path(chosen))


class Panel(QWidget):
    settings_changed = Signal()
    login_requested = Signal()
    logout_requested = Signal()
    upload_requested = Signal(Path, str)
    upload_cancelled = Signal()
    admin_action = Signal(str, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._me: dict | None = None
        self._drag_from: QPoint | None = None

        self.setObjectName("panel")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(theme.PANEL_QSS)
        self.setFixedWidth(384)
        self.setWindowTitle("LiveChat")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)
        root.addLayout(self._build_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_connection_tab(), "Connexion")
        self._tabs.addTab(self._build_send_tab(), "Envoyer")
        self._tabs.addTab(self._build_display_tab(), "Affichage")
        self._tabs.addTab(self._build_text_tab(), "Texte")
        self._admin_tab = self._build_admin_tab()
        root.addWidget(self._tabs)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setObjectName("value")
        root.addWidget(self._message)

        self.set_connected(False)
        self.set_identity(None)

    # -- entête ---------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("LiveChat")
        title.setObjectName("title")
        self._subtitle = QLabel("Déconnecté")
        self._subtitle.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(self._subtitle)
        layout.addLayout(titles)
        layout.addStretch()

        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.setFixedSize(26, 26)
        close.clicked.connect(self.hide)
        layout.addWidget(close, alignment=Qt.AlignTop)
        return layout

    # -- connexion ------------------------------------------------------------

    def _build_connection_tab(self) -> QWidget:
        page, layout = _page()

        layout.addWidget(section("Serveur"))
        self._server_field = QLineEdit(self._settings["server_url"])
        self._server_field.setPlaceholderText("https://livechat.exemple.fr")
        self._server_field.editingFinished.connect(
            lambda: self._settings.set("server_url", self._server_field.text().strip())
        )
        layout.addWidget(self._server_field)

        hint = QLabel("L'adresse que vous a donnée l'hébergeur. C'est tout ce dont vous avez besoin.")
        hint.setObjectName("value")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._login_button = QPushButton("Se connecter avec Discord")
        self._login_button.setObjectName("primary")
        self._login_button.clicked.connect(self._on_login_clicked)
        layout.addWidget(self._login_button)

        self._logout_button = QPushButton("Se déconnecter")
        self._logout_button.clicked.connect(self.logout_requested.emit)
        layout.addWidget(self._logout_button)

        layout.addWidget(_separator())
        layout.addWidget(section("Système"))
        self._autostart = QCheckBox("Lancer au démarrage de la session")
        self._autostart.setChecked(platform.autostart_enabled())
        self._autostart.toggled.connect(self._on_autostart)
        layout.addWidget(self._autostart)

        layout.addStretch()
        return page

    def _on_login_clicked(self) -> None:
        self._settings.set("server_url", self._server_field.text().strip())
        self.login_requested.emit()

    def _on_autostart(self, enabled: bool) -> None:
        if not platform.set_autostart(enabled):
            self.notify("Impossible de modifier le démarrage automatique.", error=True)
            self._autostart.setChecked(not enabled)

    # -- envoi ----------------------------------------------------------------

    def _build_send_tab(self) -> QWidget:
        page, layout = _page()

        self._drop = DropZone()
        self._drop.file_chosen.connect(self._on_file_chosen)
        layout.addWidget(self._drop)

        self._caption_field = QLineEdit()
        self._caption_field.setPlaceholderText("Légende (facultative)")
        layout.addWidget(self._caption_field)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("value")
        self._progress_label.hide()
        layout.addWidget(self._progress_label)

        self._cancel_upload = QPushButton("Annuler l'envoi")
        self._cancel_upload.setObjectName("danger")
        self._cancel_upload.clicked.connect(self.upload_cancelled.emit)
        self._cancel_upload.hide()
        layout.addWidget(self._cancel_upload)

        self._limit_label = QLabel("")
        self._limit_label.setObjectName("value")
        self._limit_label.setWordWrap(True)
        layout.addWidget(self._limit_label)

        layout.addStretch()
        return page

    def _on_file_chosen(self, path: Path) -> None:
        self.upload_requested.emit(path, self._caption_field.text().strip())

    def upload_started(self, total: int) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._progress_label.setText(f"0 / {human(total)}")
        self._progress_label.show()
        self._cancel_upload.show()
        self._drop.setEnabled(False)

    def upload_progress(self, sent: int, total: int) -> None:
        if total <= 0:
            return
        self._progress.setValue(int(sent * 100 / total))
        self._progress_label.setText(f"{human(sent)} / {human(total)}")

    def upload_ended(self, message: str, error: bool = False) -> None:
        self._progress.hide()
        self._progress_label.hide()
        self._cancel_upload.hide()
        self._drop.setEnabled(True)
        self._caption_field.clear()
        self.notify(message, error=error)

    # -- affichage ------------------------------------------------------------

    def _build_display_tab(self) -> QWidget:
        page, layout = _page()

        layout.addWidget(section("Position"))
        self._screen_box = QComboBox()
        self._screen_box.currentIndexChanged.connect(self._on_screen_changed)
        layout.addWidget(Row("Écran", self._screen_box))
        self.refresh_screens()

        self._corner_box = QComboBox()
        for key, label in CORNERS.items():
            self._corner_box.addItem(label, key)
        self._corner_box.setCurrentIndex(
            max(0, list(CORNERS).index(self._settings["corner"]))
            if self._settings["corner"] in CORNERS else 0
        )
        self._corner_box.currentIndexChanged.connect(
            lambda: self._change("corner", self._corner_box.currentData())
        )
        layout.addWidget(Row("Coin", self._corner_box))

        self._margin = self._slider(0, 200, self._settings["margin"])
        margin_row = Row("Marge", self._margin, f"{self._settings['margin']} px")
        self._margin.valueChanged.connect(
            lambda v: (margin_row.value.setText(f"{v} px"), self._change("margin", v))
        )
        layout.addWidget(margin_row)

        layout.addWidget(_separator())
        layout.addWidget(section("Taille et opacité"))

        self._scale = self._slider(5, 100, self._settings.scale_percent)
        scale_row = Row("Taille", self._scale, f"{self._settings.scale_percent} %")
        self._scale.valueChanged.connect(
            lambda v: (scale_row.value.setText(f"{v} %"), self._change("scale_percent", v))
        )
        layout.addWidget(scale_row)

        self._opacity = self._slider(20, 100, self._settings["opacity_percent"])
        opacity_row = Row("Opacité", self._opacity, f"{self._settings['opacity_percent']} %")
        self._opacity.valueChanged.connect(
            lambda v: (opacity_row.value.setText(f"{v} %"),
                       self._change("opacity_percent", v))
        )
        layout.addWidget(opacity_row)

        self._duration = self._slider(1, 60, self._settings.image_duration)
        duration_row = Row("Durée", self._duration, f"{self._settings.image_duration} s")
        self._duration.valueChanged.connect(
            lambda v: (duration_row.value.setText(f"{v} s"),
                       self._change("image_duration_seconds", v))
        )
        layout.addWidget(duration_row)

        layout.addWidget(_separator())
        layout.addWidget(section("Son"))

        self._volume = self._slider(0, 100, self._settings["volume"])
        volume_row = Row("Volume", self._volume, f"{self._settings['volume']} %")
        self._volume.valueChanged.connect(
            lambda v: (volume_row.value.setText(f"{v} %"), self._change("volume", v))
        )
        layout.addWidget(volume_row)

        self._mute = QCheckBox("Couper le son")
        self._mute.setChecked(bool(self._settings["muted"]))
        self._mute.toggled.connect(lambda v: self._change("muted", v))
        layout.addWidget(self._mute)

        self._avoid = QCheckBox("Changer d'écran si un jeu est en plein écran")
        self._avoid.setChecked(bool(self._settings["avoid_fullscreen"]))
        self._avoid.toggled.connect(lambda v: self._change("avoid_fullscreen", v))
        layout.addWidget(self._avoid)

        layout.addStretch()
        return page

    def refresh_screens(self) -> None:
        current = self._settings["screen_name"]
        self._screen_box.blockSignals(True)
        self._screen_box.clear()
        self._screen_box.addItem("Écran principal", "")
        for screen in QApplication.instance().screens():
            geometry = screen.geometry()
            self._screen_box.addItem(
                f"{screen.name()} — {geometry.width()}×{geometry.height()}", screen.name()
            )
        index = self._screen_box.findData(current)
        self._screen_box.setCurrentIndex(index if index >= 0 else 0)
        self._screen_box.blockSignals(False)

    def _on_screen_changed(self) -> None:
        self._change("screen_name", self._screen_box.currentData())

    # -- texte ----------------------------------------------------------------

    def _build_text_tab(self) -> QWidget:
        page, layout = _page()

        layout.addWidget(section("Police"))
        self._font_box = QComboBox()
        self._font_box.addItem(f"Police embarquée ({fonts.embedded_family()})", "")
        for family in QFontDatabase.families():
            self._font_box.addItem(family, family)
        index = self._font_box.findData(self._settings["font_family"])
        self._font_box.setCurrentIndex(index if index >= 0 else 0)
        self._font_box.currentIndexChanged.connect(
            lambda: self._change("font_family", self._font_box.currentData())
        )
        layout.addWidget(self._font_box)

        hint = QLabel(
            "La police embarquée est identique chez tout le monde. Une police "
            "personnelle ne s'affichera correctement que sur votre machine."
        )
        hint.setObjectName("value")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(_separator())
        layout.addWidget(section("Tailles"))

        self._name_size = self._slider(12, 72, self._settings["name_size"])
        name_row = Row("Pseudo", self._name_size, f"{self._settings['name_size']} px")
        self._name_size.valueChanged.connect(
            lambda v: (name_row.value.setText(f"{v} px"), self._change("name_size", v))
        )
        layout.addWidget(name_row)

        self._caption_size = self._slider(10, 60, self._settings["caption_size"])
        caption_row = Row("Légende", self._caption_size, f"{self._settings['caption_size']} px")
        self._caption_size.valueChanged.connect(
            lambda v: (caption_row.value.setText(f"{v} px"),
                       self._change("caption_size", v))
        )
        layout.addWidget(caption_row)

        layout.addWidget(_separator())
        layout.addWidget(section("Auteur"))
        self._author_box = QComboBox()
        for key, label in AUTHOR_POSITIONS.items():
            self._author_box.addItem(label, key)
        index = self._author_box.findData(self._settings["author_position"])
        self._author_box.setCurrentIndex(index if index >= 0 else 0)
        self._author_box.currentIndexChanged.connect(
            lambda: self._change("author_position", self._author_box.currentData())
        )
        layout.addWidget(self._author_box)

        layout.addStretch()
        return page

    # -- administration -------------------------------------------------------

    def _build_admin_tab(self) -> QWidget:
        page, layout = _page()

        layout.addWidget(section("Modération"))
        clear = QPushButton("Retirer le média affiché")
        clear.setObjectName("danger")
        clear.clicked.connect(lambda: self.admin_action.emit("clear", None))
        layout.addWidget(clear)

        buttons = QHBoxLayout()
        mute_all = QPushButton("Couper le son")
        mute_all.clicked.connect(lambda: self.admin_action.emit("mute", None))
        unmute_all = QPushButton("Rétablir")
        unmute_all.clicked.connect(lambda: self.admin_action.emit("unmute", None))
        buttons.addWidget(mute_all)
        buttons.addWidget(unmute_all)
        layout.addLayout(buttons)

        layout.addWidget(_separator())
        layout.addWidget(section("Stockage"))
        self._disk_label = QLabel("—")
        self._disk_label.setObjectName("value")
        layout.addWidget(self._disk_label)

        self._quota = self._slider(1, 500, 30)
        quota_row = Row("Quota", self._quota, "30 Gio")
        self._quota.valueChanged.connect(lambda v: quota_row.value.setText(f"{v} Gio"))
        self._quota.sliderReleased.connect(
            lambda: self.admin_action.emit(
                "settings", {"disk_quota_bytes": self._quota.value() * GIGA}
            )
        )
        layout.addWidget(quota_row)

        self._max_file = self._slider(1, 20, 5)
        max_row = Row("Max/fichier", self._max_file, "5 Gio")
        self._max_file.valueChanged.connect(lambda v: max_row.value.setText(f"{v} Gio"))
        self._max_file.sliderReleased.connect(
            lambda: self.admin_action.emit(
                "settings", {"max_file_bytes": self._max_file.value() * GIGA}
            )
        )
        layout.addWidget(max_row)

        layout.addWidget(_separator())
        layout.addWidget(section("Salon Discord surveillé"))
        channel_row = QHBoxLayout()
        self._channel_field = QLineEdit()
        self._channel_field.setPlaceholderText("Identifiant du salon")
        apply_channel = QPushButton("Appliquer")
        apply_channel.clicked.connect(self._apply_channel)
        channel_row.addWidget(self._channel_field, 1)
        channel_row.addWidget(apply_channel)
        layout.addLayout(channel_row)

        layout.addWidget(_separator())
        layout.addWidget(section("Participants connectés"))
        self._clients_label = QLabel("—")
        self._clients_label.setObjectName("value")
        self._clients_label.setWordWrap(True)
        layout.addWidget(self._clients_label)

        layout.addStretch()
        return page

    def _apply_channel(self) -> None:
        raw = self._channel_field.text().strip()
        if not raw.isdigit():
            self.notify("L'identifiant du salon doit être numérique.", error=True)
            return
        self.admin_action.emit("settings", {"channel_id": int(raw)})

    def show_admin_settings(self, payload: dict) -> None:
        settings = payload.get("settings", {})
        disk = payload.get("disk", {})
        used, quota = disk.get("used_bytes", 0), disk.get("quota_bytes", 1)
        self._disk_label.setText(
            f"{human(used)} occupés sur {human(quota)}  ({used * 100 // max(quota, 1)} %)"
        )
        for slider, key in ((self._quota, "disk_quota_bytes"), (self._max_file, "max_file_bytes")):
            if key in settings:
                slider.blockSignals(True)
                slider.setValue(max(1, int(settings[key] / GIGA)))
                slider.blockSignals(False)
        if settings.get("channel_id"):
            self._channel_field.setText(str(settings["channel_id"]))

    def show_admin_clients(self, clients: list) -> None:
        if not clients:
            self._clients_label.setText("Personne pour l'instant.")
            return
        # Des pseudos Discord, jamais des adresses IP : la v1 les exposait sur un
        # endpoint ouvert à tous.
        self._clients_label.setText(
            "\n".join(f"• {c.get('display_name', '?')}" for c in clients)
        )

    # -- état -----------------------------------------------------------------

    def set_identity(self, me: dict | None) -> None:
        self._me = me
        connected = me is not None
        self._login_button.setVisible(not connected)
        self._logout_button.setVisible(connected)
        self._server_field.setEnabled(not connected)

        admin_index = self._tabs.indexOf(self._admin_tab)
        is_admin = bool(me and me.get("user", {}).get("is_admin"))
        if is_admin and admin_index < 0:
            self._tabs.addTab(self._admin_tab, "Admin")
        elif not is_admin and admin_index >= 0:
            self._tabs.removeTab(admin_index)

        if me:
            limit = me.get("limits", {}).get("max_file_bytes", 0)
            self._limit_label.setText(f"Taille maximale acceptée par le serveur : {human(limit)}.")
            if not me.get("user", {}).get("may_upload", True):
                self._limit_label.setText("Vous n'êtes pas autorisé à envoyer des médias.")
                self._drop.setEnabled(False)

    def set_connected(self, connected: bool, detail: str = "") -> None:
        user = (self._me or {}).get("user", {})
        if connected and user:
            role = "propriétaire" if user.get("is_owner") else (
                "admin" if user.get("is_admin") else "connecté"
            )
            self._subtitle.setText(f"{user.get('display_name', '')} — {role}")
        else:
            self._subtitle.setText(detail or "Déconnecté")

    def notify(self, message: str, error: bool = False) -> None:
        self._message.setObjectName("error" if error else "ok")
        self._message.setStyleSheet("")
        self._message.setText(message)
        self.style().unpolish(self._message)
        self.style().polish(self._message)
        QTimer.singleShot(8000, lambda: self._message.setText(""))

    def open_near_cursor(self) -> None:
        screen = QApplication.instance().primaryScreen()
        area = screen.availableGeometry()
        self.adjustSize()
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)
        self.show()
        self.raise_()
        self.activateWindow()

    # -- utilitaires ----------------------------------------------------------

    def _slider(self, low: int, high: int, value: int) -> QSlider:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(max(low, min(high, int(value))))
        slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return slider

    def _change(self, key: str, value) -> None:
        self._settings.set(key, value)
        self.settings_changed.emit()

    # -- déplacement à la souris ---------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None


def _page() -> tuple[QWidget, QVBoxLayout]:
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(2, 10, 2, 4)
    layout.setSpacing(9)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setMinimumHeight(300)

    holder = QWidget()
    wrapper = QVBoxLayout(holder)
    wrapper.setContentsMargins(0, 0, 0, 0)
    wrapper.addWidget(area)
    return holder, layout


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("separator")
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("background:#262632; border:none; max-height:1px;")
    return line
