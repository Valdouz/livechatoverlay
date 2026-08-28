"""Découpe d'un extrait avant envoi.

Le fichier n'est pas retaillé : on retient deux instants, et la lecture s'y
limite chez tout le monde. Aucun réencodage, donc rien à installer, aucune
attente et aucune perte de qualité — au prix d'un fichier envoyé entier.

Pour un extrait de dix secondes tiré d'une vidéo de téléphone, l'échange est
bon. Pour tailler dans un fichier de plusieurs gigaoctets, il faudrait une vraie
découpe côté expéditeur.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme

log = logging.getLogger(__name__)

HANDLE = 9


def clock(ms: int) -> str:
    seconds, ms = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}.{ms // 100}"


class RangeBar(QWidget):
    """Une barre de temps avec deux poignées et la tête de lecture.

    Deux curseurs superposés seraient plus simples à écrire, mais on ne verrait
    pas d'un coup d'œil quelle portion est retenue — c'est pourtant la seule
    chose qui compte ici.
    """

    changed = Signal(int, int)      # début, fin
    scrubbed = Signal(int)          # position demandée

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.SizeHorCursor)
        self._duration = 0
        self._start = 0
        self._end = 0
        self._position = 0
        self._grabbed: str | None = None

    # -- état ------------------------------------------------------------------

    def set_duration(self, duration: int) -> None:
        self._duration = max(0, int(duration))
        self._start = 0
        self._end = self._duration
        self.update()
        self.changed.emit(self._start, self._end)

    def set_position(self, position: int) -> None:
        self._position = int(position)
        self.update()

    @property
    def duration(self) -> int:
        return self._duration

    @property
    def start(self) -> int:
        return self._start

    @property
    def end(self) -> int:
        return self._end

    # -- géométrie -------------------------------------------------------------

    def _track(self):
        return self.rect().adjusted(HANDLE, 12, -HANDLE, -12)

    def _to_x(self, ms: int) -> float:
        track = self._track()
        if self._duration <= 0:
            return track.left()
        return track.left() + track.width() * (ms / self._duration)

    def _to_ms(self, x: float) -> int:
        track = self._track()
        if track.width() <= 0 or self._duration <= 0:
            return 0
        ratio = (x - track.left()) / track.width()
        return int(max(0.0, min(1.0, ratio)) * self._duration)

    # -- souris ----------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if self._duration <= 0:
            return
        x = event.position().x()
        near_start = abs(x - self._to_x(self._start))
        near_end = abs(x - self._to_x(self._end))
        # La poignée la plus proche gagne, à condition d'être à portée du doigt.
        if min(near_start, near_end) <= 14:
            self._grabbed = "start" if near_start <= near_end else "end"
        else:
            self._grabbed = "position"
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._grabbed is None or self._duration <= 0:
            return
        ms = self._to_ms(event.position().x())
        if self._grabbed == "start":
            # Garder au moins un dixième de seconde : un extrait vide n'a pas de sens.
            self._start = min(ms, max(0, self._end - 100))
            self.changed.emit(self._start, self._end)
            self.scrubbed.emit(self._start)
        elif self._grabbed == "end":
            self._end = max(ms, min(self._duration, self._start + 100))
            self.changed.emit(self._start, self._end)
            self.scrubbed.emit(max(self._start, self._end - 400))
        else:
            self.scrubbed.emit(max(self._start, min(ms, self._end)))
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._grabbed = None

    # -- peinture --------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = self._track()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#23232f"))
        painter.drawRoundedRect(track, 5, 5)

        if self._duration <= 0:
            painter.end()
            return

        # La portion retenue, en vert : le reste est visiblement écarté.
        kept = track.adjusted(0, 0, 0, 0)
        kept.setLeft(int(self._to_x(self._start)))
        kept.setRight(int(self._to_x(self._end)))
        painter.setBrush(QColor(61, 220, 132, 70))
        painter.drawRect(kept)

        painter.setPen(QPen(QColor("#f0f0f6"), 2))
        head = self._to_x(self._position)
        painter.drawLine(int(head), track.top() - 4, int(head), track.bottom() + 4)

        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.RING_COLOR)
        for ms in (self._start, self._end):
            x = self._to_x(ms)
            painter.drawRoundedRect(
                int(x) - HANDLE // 2, track.top() - 6, HANDLE, track.height() + 12, 4, 4
            )
        painter.end()


class TrimDialog(QDialog):
    """Aperçu et choix de l'extrait à envoyer."""

    def __init__(self, path, parent=None, start: int = 0, end: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Découper avant l'envoi")
        self.setStyleSheet(theme.PANEL_QSS)
        self.setMinimumSize(QSize(620, 480))
        self._wanted = (start, end)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._video = QVideoWidget()
        self._video.setMinimumHeight(260)
        self._video.setStyleSheet("background: #0b0b12; border-radius: 10px;")
        root.addWidget(self._video, 1)

        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._video)
        self._player.setAudioOutput(self._audio)
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.errorOccurred.connect(
            lambda _, message: log.warning("Aperçu impossible : %s", message)
        )

        self._bar = RangeBar()
        self._bar.changed.connect(self._on_range)
        self._bar.scrubbed.connect(self._player.setPosition)
        root.addWidget(self._bar)

        info = QHBoxLayout()
        self._play = QPushButton("Lire")
        self._play.clicked.connect(self._toggle)
        self._range_label = QLabel("—")
        self._range_label.setObjectName("value")
        info.addWidget(self._play)
        info.addWidget(self._range_label, 1)
        root.addLayout(info)

        root.addWidget(QLabel(
            "Le fichier est envoyé entier ; seul l'extrait choisi est joué."
        ), alignment=Qt.AlignLeft)
        root.itemAt(root.count() - 1).widget().setObjectName("hint")

        actions = QHBoxLayout()
        whole = QPushButton("Tout garder")
        whole.setObjectName("ghost_button")
        whole.clicked.connect(self._reset)
        cancel = QPushButton("Annuler")
        cancel.setObjectName("ghost_button")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("Valider l'extrait")
        confirm.setObjectName("primary")
        confirm.setMinimumHeight(34)
        confirm.clicked.connect(self.accept)
        actions.addWidget(whole)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        root.addLayout(actions)

        self._player.setSource(QUrl.fromLocalFile(str(path)))

    # -- lecture ---------------------------------------------------------------

    def _on_duration(self, duration: int) -> None:
        if duration <= 0:
            return
        self._bar.set_duration(duration)
        start, end = self._wanted
        if end and end <= duration:
            self._bar._start, self._bar._end = start, end
            self._bar.update()
            self._on_range(start, end)

    def _on_position(self, position: int) -> None:
        self._bar.set_position(position)
        # Boucler sur l'extrait : on juge mieux une coupe en la revoyant.
        if self._bar.end and position >= self._bar.end:
            self._player.setPosition(self._bar.start)

    def _on_range(self, start: int, end: int) -> None:
        self._range_label.setText(
            f"{clock(start)} → {clock(end)}   ({clock(end - start)} retenues)"
        )

    def _toggle(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play.setText("Lire")
        else:
            if self._player.position() < self._bar.start:
                self._player.setPosition(self._bar.start)
            self._player.play()
            self._play.setText("Pause")

    def _reset(self) -> None:
        self._bar.set_duration(self._player.duration())

    # -- résultat ---------------------------------------------------------------

    def selection(self) -> tuple[int, int]:
        """(début, fin) en millisecondes. (0, 0) si tout est gardé.

        La durée vient de la barre, pas du lecteur : celui-ci est vidé à la
        fermeture et renverrait zéro. On concluait alors que la fin couvrait tout
        le média, et raccourcir la fin — le cas le plus courant — était
        silencieusement annulé.
        """
        start, end = self._bar.start, self._bar.end
        duration = self._bar.duration
        if duration <= 0:
            return (0, 0)
        if start <= 0 and end >= duration:
            return (0, 0)
        return (start, end)

    def done(self, result: int) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        super().done(result)
