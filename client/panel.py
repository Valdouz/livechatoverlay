"""Le panneau de contrôle.

C'est la seule fenêtre avec laquelle on interagit : l'overlay, lui, est traversé par
les clics par construction. Le glisser-déposer vise donc le panneau, jamais l'overlay.

Deux états, jamais mélangés : déconnecté, on ne propose que de se connecter ; connecté,
les onglets apparaissent. Montrer des réglages inutilisables à quelqu'un qui n'est pas
encore entré ne l'aide pas à entrer.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from . import fonts, platform, theme
from .settings import AUTHOR_POSITIONS, CORNERS

log = logging.getLogger(__name__)

GIGA = 1024 ** 3

COMPACT_WIDTH = 360
COMPACT_MAX_HEIGHT = 660
EXPANDED_SIZE = QSize(560, 780)


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


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background:#26263a; border:none;")
    return line


def logo(size: int = 56) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#1c1c28"))
    painter.drawEllipse(0, 0, size, size)
    # Un stylo neuf : painter.pen() renverrait celui posé juste avant, de style
    # NoPen — lui donner une couleur ne suffirait pas à le rendre visible.
    painter.setPen(QPen(theme.RING_COLOR, max(3, size // 14)))
    painter.setBrush(Qt.NoBrush)
    inset = size // 8
    painter.drawEllipse(inset, inset, size - 2 * inset, size - 2 * inset)
    painter.end()
    return pixmap


class Stack(QStackedWidget):
    """Pile qui se dimensionne sur la page affichée.

    Par défaut QStackedWidget réserve la taille de sa page la plus grande : l'écran
    de connexion héritait alors de la hauteur de l'onglet Apparence, et s'affichait
    dans une fenêtre trois fois trop haute.
    """

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(self._only_current_counts)

    def _only_current_counts(self, index: int) -> None:
        for i in range(self.count()):
            page = self.widget(i)
            page.setSizePolicy(
                QSizePolicy.Preferred,
                QSizePolicy.Preferred if i == index else QSizePolicy.Ignored,
            )
        self.adjustSize()

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class Slider(QWidget):
    """Curseur avec son libellé et sa valeur sur la même ligne.

    La v1 alignait libellé, curseur et valeur sur une seule rangée : à 360 px de
    large, il ne restait rien pour le curseur et la valeur passait à la trappe.
    """

    changed = Signal(int)

    def __init__(self, label: str, low: int, high: int, value: int, suffix: str):
        super().__init__()
        self._suffix = suffix

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(label)
        self._value = QLabel()
        self._value.setObjectName("value")
        header.addWidget(self._label)
        header.addStretch()
        header.addWidget(self._value)
        outer.addLayout(header)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(low, high)
        self.slider.setValue(max(low, min(high, int(value))))
        self.slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.slider.valueChanged.connect(self._on_change)
        outer.addWidget(self.slider)

        self._refresh(self.slider.value())

    def _refresh(self, value: int) -> None:
        self._value.setText(f"{value} {self._suffix}".strip())

    def _on_change(self, value: int) -> None:
        self._refresh(value)
        self.changed.emit(value)

    def set_value(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._refresh(value)

    def value(self) -> int:
        return self.slider.value()


class Field(QWidget):
    """Un libellé au-dessus de son contrôle, plutôt qu'une colonne d'étiquettes."""

    def __init__(self, label: str, widget: QWidget):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)


class DropZone(QWidget):
    file_chosen = Signal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop_zone")
        self.setAcceptDrops(True)
        self.setProperty("hover", "false")
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("＋")
        icon.setObjectName("drop_icon")
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("Glissez un fichier ici")
        title.setObjectName("drop_title")
        title.setAlignment(Qt.AlignCenter)
        browse = QPushButton("Parcourir…")
        browse.setObjectName("ghost_button")
        browse.clicked.connect(self._browse)

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(browse, alignment=Qt.AlignCenter)

    def _hover(self, hovering: bool) -> None:
        self.setProperty("hover", "true" if hovering else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, event) -> None:
        self._hover(False)

    def dropEvent(self, event) -> None:
        self._hover(False)
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
    upload_requested = Signal(Path, str, str)
    upload_cancelled = Signal()
    admin_action = Signal(str, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._me: dict | None = None
        self._drag_from: QPoint | None = None
        self._online = False
        self._expanded = False

        self.setObjectName("panel")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet(theme.PANEL_QSS)
        self.setFixedWidth(COMPACT_WIDTH)
        self.setWindowTitle("LiveChat")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)
        root.addLayout(self._build_header())

        self._stack = Stack()
        self._stack.addWidget(self._build_welcome())
        self._stack.addWidget(self._build_workspace())
        self._stack._only_current_counts(0)
        root.addWidget(self._stack)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setObjectName("hint")
        self._message.hide()
        root.addWidget(self._message)

        self.set_identity(None)
        if self._settings.get("panel_expanded"):
            self.set_expanded(True)

    # -- entête ---------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(logo(30))
        layout.addWidget(mark, alignment=Qt.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("LiveChat")
        title.setObjectName("title")

        status = QHBoxLayout()
        status.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setObjectName("dot_off")
        self._subtitle = QLabel("Hors ligne")
        self._subtitle.setObjectName("subtitle")
        status.addWidget(self._dot)
        status.addWidget(self._subtitle)
        status.addStretch()

        titles.addWidget(title)
        titles.addLayout(status)
        layout.addLayout(titles)
        layout.addStretch()

        self._expand_button = QPushButton("⤢")
        self._expand_button.setObjectName("ghost_button")
        self._expand_button.setFixedSize(26, 26)
        self._expand_button.setToolTip("Agrandir en fenêtre")
        self._expand_button.clicked.connect(lambda: self.set_expanded(not self._expanded))
        layout.addWidget(self._expand_button, alignment=Qt.AlignTop)

        self._close_button = QPushButton("✕")
        self._close_button.setObjectName("ghost_button")
        self._close_button.setFixedSize(26, 26)
        self._close_button.setToolTip("Masquer le panneau — LiveChat continue de tourner")
        self._close_button.clicked.connect(self.hide)
        layout.addWidget(self._close_button, alignment=Qt.AlignTop)
        return layout

    # -- petit panneau ou vraie fenêtre ---------------------------------------

    def set_expanded(self, expanded: bool) -> None:
        """Bascule entre le panneau flottant et une fenêtre système ordinaire.

        Agrandi, on rend la main au gestionnaire de fenêtres : barre de titre,
        redimensionnement, présence dans la barre des tâches. Changer les drapeaux
        d'une fenêtre exige de la recréer, d'où le hide/show.
        """
        self._expanded = expanded
        self._settings.set("panel_expanded", expanded)
        visible = self.isVisible()
        self.hide()

        if expanded:
            self.setWindowFlags(Qt.Window)
            # setFixedWidth avait verrouillé les deux bornes : il faut les rouvrir.
            self.setMinimumWidth(COMPACT_WIDTH)
            self.setMaximumWidth(16777215)
            self.setMinimumHeight(480)
            self.setMaximumHeight(16777215)
            self.resize(EXPANDED_SIZE)
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            )
            self.setMinimumHeight(0)
            self.setFixedWidth(COMPACT_WIDTH)

        self.setProperty("expanded", "true" if expanded else "false")
        self._repolish(self)
        self._expand_button.setText("⤡" if expanded else "⤢")
        self._expand_button.setToolTip(
            "Réduire en panneau" if expanded else "Agrandir en fenêtre"
        )
        self._close_button.setVisible(not expanded)

        if not expanded:
            self._fit()
        if visible:
            self.show()
            self.raise_()

    # -- écran de connexion ---------------------------------------------------

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(14)

        mark = QLabel()
        mark.setPixmap(logo(58))
        mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(mark)

        headline = QLabel("Les médias du groupe,\nen direct sur votre écran.")
        headline.setObjectName("headline")
        headline.setAlignment(Qt.AlignCenter)
        layout.addWidget(headline)

        self._server_field = QLineEdit(self._settings["server_url"])
        self._server_field.setPlaceholderText("https://livechat.exemple.fr")
        self._server_field.setAlignment(Qt.AlignCenter)
        self._server_field.returnPressed.connect(self._on_login_clicked)
        self._server_field.editingFinished.connect(
            lambda: self._settings.set("server_url", self._server_field.text().strip())
        )
        layout.addWidget(Field("Adresse du serveur", self._server_field))
        layout.addWidget(hint("Celle que vous a donnée l'hébergeur. C'est la seule chose "
                              "dont vous avez besoin."))

        self._login_button = QPushButton("Se connecter avec Discord")
        self._login_button.setObjectName("primary")
        self._login_button.setMinimumHeight(38)
        self._login_button.clicked.connect(self._on_login_clicked)
        layout.addWidget(self._login_button)

        layout.addWidget(separator())
        self._autostart = QCheckBox("Lancer au démarrage de la session")
        self._autostart.setChecked(platform.autostart_enabled())
        self._autostart.toggled.connect(self._on_autostart)
        layout.addWidget(self._autostart)
        layout.addStretch()
        return page

    def _on_login_clicked(self) -> None:
        self._settings.set("server_url", self._server_field.text().strip())
        self._login_button.setEnabled(False)
        self._login_button.setText("En attente du navigateur…")
        QTimer.singleShot(20000, self._reset_login_button)
        self.login_requested.emit()

    def _reset_login_button(self) -> None:
        self._login_button.setEnabled(True)
        self._login_button.setText("Se connecter avec Discord")

    def _on_autostart(self, enabled: bool) -> None:
        if not platform.set_autostart(enabled):
            self.notify("Impossible de modifier le démarrage automatique.", error=True)
            self._autostart.setChecked(not enabled)

    # -- espace de travail ----------------------------------------------------

    def _build_workspace(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_send_tab(), "Envoyer")
        self._tabs.addTab(self._build_look_tab(), "Apparence")
        self._admin_tab = self._build_admin_tab()
        layout.addWidget(self._tabs)

        footer = QHBoxLayout()
        logout = QPushButton("Se déconnecter")
        logout.setObjectName("ghost_button")
        logout.clicked.connect(self.logout_requested.emit)
        footer.addStretch()
        footer.addWidget(logout)
        layout.addLayout(footer)
        return page

    # -- envoyer --------------------------------------------------------------

    def _build_send_tab(self) -> QWidget:
        page, layout = _tab()

        self._drop = DropZone()
        self._drop.file_chosen.connect(self._on_file_chosen)
        layout.addWidget(self._drop)

        self._caption_field = QLineEdit()
        self._caption_field.setPlaceholderText("Légende (facultative)")
        layout.addWidget(self._caption_field)

        # Par défaut le média part sur tous les écrans ; on peut viser une personne.
        self._target_box = QComboBox()
        self._target_box.addItem("Tout le monde", "")
        self._target_names: dict[str, str] = {}
        layout.addWidget(Field("Destinataire", self._target_box))

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)

        progress_row = QHBoxLayout()
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("value")
        self._progress_label.hide()
        self._cancel_upload = QPushButton("Annuler")
        self._cancel_upload.setObjectName("ghost_button")
        self._cancel_upload.clicked.connect(self.upload_cancelled.emit)
        self._cancel_upload.hide()
        progress_row.addWidget(self._progress_label)
        progress_row.addStretch()
        progress_row.addWidget(self._cancel_upload)
        layout.addLayout(progress_row)

        self._limit_label = hint("")
        layout.addWidget(self._limit_label)
        layout.addStretch()
        return page

    def _on_file_chosen(self, path: Path) -> None:
        self.upload_requested.emit(
            path, self._caption_field.text().strip(), self._target_box.currentData() or ""
        )

    def show_participants(self, people: list) -> None:
        """Rafraîchit la liste sans perdre la sélection en cours."""
        chosen = self._target_box.currentData()
        self._target_box.blockSignals(True)
        self._target_box.clear()
        self._target_box.addItem("Tout le monde", "")
        self._target_names.clear()
        for person in people:
            if person.get("is_you"):
                continue  # s'envoyer un média à soi-même n'a pas d'intérêt
            self._target_names[person["id"]] = person["display_name"]
            self._target_box.addItem(f"Seulement {person['display_name']}", person["id"])
        index = self._target_box.findData(chosen)
        self._target_box.setCurrentIndex(index if index >= 0 else 0)
        self._target_box.blockSignals(False)

    def target_name(self) -> str:
        """Le pseudo seul du destinataire choisi, vide si l'envoi est global."""
        chosen = self._target_box.currentData()
        return self._target_names.get(chosen, "") if chosen else ""

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

    # -- apparence ------------------------------------------------------------

    def _build_look_tab(self) -> QWidget:
        page, layout = _tab()

        layout.addWidget(section("Où"))
        self._screen_box = QComboBox()
        self._screen_box.currentIndexChanged.connect(
            lambda: self._change("screen_name", self._screen_box.currentData())
        )
        layout.addWidget(Field("Écran", self._screen_box))
        self.refresh_screens()

        self._corner_box = QComboBox()
        for key, label in CORNERS.items():
            self._corner_box.addItem(label, key)
        index = self._corner_box.findData(self._settings["corner"])
        self._corner_box.setCurrentIndex(index if index >= 0 else 0)
        self._corner_box.currentIndexChanged.connect(
            lambda: self._change("corner", self._corner_box.currentData())
        )
        layout.addWidget(Field("Position", self._corner_box))
        self._margin = self._slider(layout, "Marge", 0, 200,
                                    self._settings["margin"], "px", "margin")

        layout.addWidget(separator())
        layout.addWidget(section("Taille"))
        self._scale = self._slider(layout, "Taille du média", 5, 100,
                                   self._settings.scale_percent, "%", "scale_percent")
        self._opacity = self._slider(layout, "Opacité", 20, 100,
                                     self._settings["opacity_percent"], "%", "opacity_percent")
        self._duration = self._slider(layout, "Durée des images", 1, 60,
                                      self._settings.image_duration, "s",
                                      "image_duration_seconds")

        layout.addWidget(separator())
        layout.addWidget(section("Texte"))
        self._font_box = QComboBox()
        self._font_box.addItem(f"Embarquée — {fonts.embedded_family()}", "")
        for family in QFontDatabase.families():
            self._font_box.addItem(family, family)
        index = self._font_box.findData(self._settings["font_family"])
        self._font_box.setCurrentIndex(index if index >= 0 else 0)
        self._font_box.currentIndexChanged.connect(
            lambda: self._change("font_family", self._font_box.currentData())
        )
        layout.addWidget(Field("Police", self._font_box))
        layout.addWidget(hint("La police embarquée est identique chez tout le monde. "
                              "Une police personnelle ne vaudra que pour votre écran."))
        self._name_size = self._slider(layout, "Taille du pseudo", 12, 72,
                                       self._settings["name_size"], "px", "name_size")
        self._caption_size = self._slider(layout, "Taille de la légende", 10, 60,
                                          self._settings["caption_size"], "px", "caption_size")

        self._author_box = QComboBox()
        for key, label in AUTHOR_POSITIONS.items():
            self._author_box.addItem(label, key)
        index = self._author_box.findData(self._settings["author_position"])
        self._author_box.setCurrentIndex(index if index >= 0 else 0)
        self._author_box.currentIndexChanged.connect(
            lambda: self._change("author_position", self._author_box.currentData())
        )
        layout.addWidget(Field("Affichage de l'auteur", self._author_box))

        layout.addWidget(separator())
        layout.addWidget(section("Son et confort"))
        self._volume = self._slider(layout, "Volume", 0, 100,
                                    self._settings["volume"], "%", "volume")
        self._mute = QCheckBox("Couper le son")
        self._mute.setChecked(bool(self._settings["muted"]))
        self._mute.toggled.connect(lambda v: self._change("muted", v))
        layout.addWidget(self._mute)

        self._avoid = QCheckBox("Basculer d'écran si un jeu passe en plein écran")
        self._avoid.setChecked(bool(self._settings["avoid_fullscreen"]))
        self._avoid.toggled.connect(lambda v: self._change("avoid_fullscreen", v))
        layout.addWidget(self._avoid)
        layout.addStretch()
        return page

    def _slider(self, layout, label, low, high, value, suffix, key) -> Slider:
        widget = Slider(label, low, high, value, suffix)
        widget.changed.connect(lambda v: self._change(key, v))
        layout.addWidget(widget)
        return widget

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

    # -- administration -------------------------------------------------------

    def _build_admin_tab(self) -> QWidget:
        page, layout = _tab()

        layout.addWidget(section("Sur tous les écrans"))
        clear = QPushButton("Retirer le média affiché")
        clear.setObjectName("danger")
        clear.clicked.connect(lambda: self.admin_action.emit("clear", None))
        layout.addWidget(clear)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        mute_all = QPushButton("Couper le son")
        mute_all.clicked.connect(lambda: self.admin_action.emit("mute", None))
        unmute_all = QPushButton("Rétablir le son")
        unmute_all.clicked.connect(lambda: self.admin_action.emit("unmute", None))
        buttons.addWidget(mute_all)
        buttons.addWidget(unmute_all)
        layout.addLayout(buttons)

        layout.addWidget(separator())
        layout.addWidget(section("Serveur"))

        self._disk_bar = QProgressBar()
        self._disk_bar.setTextVisible(False)
        self._disk_bar.setRange(0, 100)
        layout.addWidget(self._disk_bar)
        self._disk_label = hint("—")
        layout.addWidget(self._disk_label)

        self._quota = Slider("Quota disque", 1, 500, 30, "Gio")
        self._quota.slider.sliderReleased.connect(
            lambda: self.admin_action.emit(
                "settings", {"disk_quota_bytes": self._quota.value() * GIGA})
        )
        layout.addWidget(self._quota)

        self._max_file = Slider("Taille maximale par fichier", 1, 20, 5, "Gio")
        self._max_file.slider.sliderReleased.connect(
            lambda: self.admin_action.emit(
                "settings", {"max_file_bytes": self._max_file.value() * GIGA})
        )
        layout.addWidget(self._max_file)

        channel_row = QHBoxLayout()
        channel_row.setContentsMargins(0, 0, 0, 0)
        channel_row.setSpacing(8)
        self._channel_field = QLineEdit()
        self._channel_field.setPlaceholderText("Identifiant du salon")
        apply_channel = QPushButton("Appliquer")
        apply_channel.clicked.connect(self._apply_channel)
        channel_row.addWidget(self._channel_field, 1)
        channel_row.addWidget(apply_channel)
        holder = QWidget()
        holder.setLayout(channel_row)
        layout.addWidget(Field("Salon Discord surveillé", holder))

        layout.addWidget(separator())
        self._clients_title = section("Personne de connecté")
        layout.addWidget(self._clients_title)
        self._clients_label = hint("—")
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
        used, quota = disk.get("used_bytes", 0), max(disk.get("quota_bytes", 1), 1)
        self._disk_bar.setValue(min(100, int(used * 100 / quota)))
        self._disk_label.setText(f"{human(used)} occupés sur {human(quota)}")
        for widget, key in ((self._quota, "disk_quota_bytes"),
                            (self._max_file, "max_file_bytes")):
            if key in settings:
                widget.set_value(max(1, int(settings[key] / GIGA)))
        # Ne pas écraser ce que l'admin est en train de taper.
        if settings.get("channel_id") and not self._channel_field.hasFocus():
            self._channel_field.setText(str(settings["channel_id"]))

    def show_admin_clients(self, clients: list) -> None:
        count = len(clients)
        plural = "s" if count > 1 else ""
        self._clients_title.setText(
            "Personne de connecté" if not count
            else f"{count} participant{plural} connecté{plural}"
        )
        # Des pseudos Discord, jamais des adresses IP : la v1 les exposait sur un
        # endpoint ouvert à tous.
        self._clients_label.setText(
            "—" if not count
            else "   ".join(f"· {c.get('display_name', '?')}" for c in clients)
        )

    # -- état -----------------------------------------------------------------

    def set_identity(self, me: dict | None) -> None:
        self._me = me
        self._stack.setCurrentIndex(1 if me else 0)
        self._reset_login_button()

        if me is None:
            self.set_connected(False)
            self._fit()
            return

        user = me.get("user", {})
        admin_index = self._tabs.indexOf(self._admin_tab)
        if user.get("is_admin") and admin_index < 0:
            self._tabs.addTab(self._admin_tab, "Admin")
        elif not user.get("is_admin") and admin_index >= 0:
            self._tabs.removeTab(admin_index)

        limit = me.get("limits", {}).get("max_file_bytes", 0)
        if user.get("may_upload", True):
            self._limit_label.setText(f"Jusqu'à {human(limit)} par fichier.")
            self._drop.setEnabled(True)
        else:
            self._limit_label.setText("Vous n'êtes pas autorisé à envoyer des médias.")
            self._drop.setEnabled(False)

        self.set_connected(self._online)
        self._fit()

    def set_connected(self, connected: bool, detail: str = "") -> None:
        self._online = connected
        user = (self._me or {}).get("user", {})
        if connected and user:
            role = ("propriétaire" if user.get("is_owner")
                    else "admin" if user.get("is_admin") else "connecté")
            self._dot.setObjectName("dot_on")
            self._subtitle.setText(f"{user.get('display_name', '')} · {role}")
        elif self._me:
            self._dot.setObjectName("dot_wait")
            self._subtitle.setText(detail or "Reconnexion…")
        else:
            self._dot.setObjectName("dot_off")
            self._subtitle.setText(detail or "Hors ligne")
        self._repolish(self._dot)

    def notify(self, message: str, error: bool = False) -> None:
        if not message:
            self._message.hide()
            return
        self._message.setObjectName("error" if error else "ok")
        self._message.setText(message)
        self._message.show()
        self._repolish(self._message)
        self._fit()
        QTimer.singleShot(9000, self._clear_message)

    def _clear_message(self) -> None:
        self._message.hide()
        self._fit()

    def _fit(self) -> None:
        """En mode compact la fenêtre épouse son contenu, sans jamais couvrir tout
        l'écran ; agrandie, c'est l'utilisateur qui décide, on n'y touche pas."""
        if self._expanded:
            return
        self.setMaximumHeight(self._compact_cap())
        self.adjustSize()

    def _compact_cap(self) -> int:
        screen = self.screen() or QApplication.instance().primaryScreen()
        return min(COMPACT_MAX_HEIGHT, screen.availableGeometry().height() - 90)

    def _repolish(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def open_near_cursor(self) -> None:
        area = QApplication.instance().primaryScreen().availableGeometry()
        self._fit()
        if self._expanded:
            # Première ouverture agrandie : centrer plutôt que rester collé en 0,0.
            if self.pos().isNull():
                self.move(area.center() - self.rect().center())
        else:
            self.move(area.right() - self.width() - 20, area.bottom() - self.height() - 20)
        self.show()
        self.raise_()
        self.activateWindow()

    # -- utilitaires ----------------------------------------------------------

    def _change(self, key: str, value) -> None:
        self._settings.set(key, value)
        self.settings_changed.emit()

    # -- déplacement à la souris ---------------------------------------------

    def mousePressEvent(self, event) -> None:
        # Agrandie, la fenêtre a sa barre de titre : c'est elle qui la déplace.
        if event.button() == Qt.LeftButton and not self._expanded:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None


def _tab() -> tuple[QWidget, QVBoxLayout]:
    """Contenu défilant : l'onglet Apparence est long, et une fenêtre de 360 px de
    large ne doit pas s'étirer sur toute la hauteur de l'écran pour l'afficher."""
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(2, 14, 10, 4)
    layout.setSpacing(11)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area, layout
