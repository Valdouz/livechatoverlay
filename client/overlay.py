"""L'overlay : une seule fenêtre, tout est peint dedans.

La v1 empilait cinq fenêtres de premier niveau — média, auteur, légende, vidéo,
panneau — qui se disputaient le z-order du système, d'où les `hide()/show()` de
colmatage pour forcer le tag auteur devant la vidéo. Ici il n'y a qu'une fenêtre :
le conflit ne peut plus exister, et le contour du texte devient trois lignes de
`QPainter` au lieu d'un problème insoluble.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QPoint, QRect, QRectF,
                            QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QMovie, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import QApplication, QWidget

from . import fonts, platform, theme

log = logging.getLogger(__name__)

TOPMOST_INTERVAL_MS = 2000
FULLSCREEN_CHECK_MS = 3000


class Overlay(QWidget):
    acknowledged = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._nam = QNetworkAccessManager(self)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # -- média courant ----------------------------------------------------
        self._media_id: str | None = None
        self._kind = ""
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_buffer: QBuffer | None = None
        self._frame_image: QImage | None = None
        self._author = ""
        self._avatar: QPixmap | None = None
        self._caption = ""
        self._private = False
        self._opacity = 0.0
        self._block = QRect()

        # -- vidéo ------------------------------------------------------------
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(
            lambda _, message: log.warning("Lecture vidéo : %s", message)
        )
        self.apply_volume()

        # -- minuteries -------------------------------------------------------
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.clear)

        self._fade = QTimer(self)
        self._fade.timeout.connect(self._step_fade)
        self._fade_target = 0.0

        self._topmost = QTimer(self)
        self._topmost.timeout.connect(lambda: platform.reassert_topmost(self))
        self._topmost.start(TOPMOST_INTERVAL_MS)

        self._fullscreen_watch = QTimer(self)
        self._fullscreen_watch.timeout.connect(self._check_fullscreen)
        self._fullscreen_watch.start(FULLSCREEN_CHECK_MS)

        self._blocked_screen: str | None = None
        self.place_on_screen()

    # -- écran ----------------------------------------------------------------

    def _wanted_screen(self):
        app = QApplication.instance()
        wanted = self._settings["screen_name"]
        if wanted:
            for screen in app.screens():
                if screen.name() == wanted and screen.name() != self._blocked_screen:
                    return screen
        for screen in app.screens():
            if screen.name() != self._blocked_screen:
                return screen
        return app.primaryScreen()

    def place_on_screen(self) -> None:
        screen = self._wanted_screen()
        if screen is None:
            return
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self._relayout()

    def _check_fullscreen(self) -> None:
        """Un plein écran exclusif court-circuite le compositeur : aucune fenêtre ne
        peut composer par-dessus. Plutôt que de disparaître, on va sur un autre écran
        en gardant exactement la même configuration.
        """
        if not self._settings["avoid_fullscreen"]:
            return
        app = QApplication.instance()
        blocked = platform.exclusive_fullscreen_active()

        if blocked and self._blocked_screen is None:
            if len(app.screens()) < 2:
                return  # une seule sortie vidéo : aucun repli possible
            self._blocked_screen = self.screen().name() if self.screen() else None
            log.info("Plein écran détecté, bascule vers un autre écran.")
            self.place_on_screen()
        elif not blocked and self._blocked_screen is not None:
            self._blocked_screen = None
            log.info("Plein écran terminé, retour à l'écran choisi.")
            self.place_on_screen()

    # -- réception ------------------------------------------------------------

    def show_media(self, payload: dict) -> None:
        media = payload.get("media", {})
        author = payload.get("author", {})

        self._reset_media()
        self._media_id = media.get("id")
        self._kind = media.get("kind", "image")
        self._author = author.get("display_name", "")
        self._caption = (payload.get("caption") or "").strip()
        self._private = bool(payload.get("private"))
        self._avatar = None

        avatar_url = author.get("avatar_url", "")
        if avatar_url:
            self._fetch(avatar_url, self._on_avatar)

        url = media.get("url", "")
        if self._kind == "video":
            self._play_video(url)
        else:
            self._fetch(url, self._on_image)

        self._fade_to(1.0)

    def clear(self) -> None:
        if self._media_id or self._pixmap or self._frame_image:
            self._fade_to(0.0)
        else:
            self._reset_media()

    def _reset_media(self) -> None:
        self._hide_timer.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        if self._movie is not None:
            self._movie.stop()
        self._movie = None
        self._movie_buffer = None
        self._pixmap = None
        self._frame_image = None
        self._media_id = None
        self._caption = ""
        self._author = ""
        self._private = False
        self._avatar = None
        self._block = QRect()
        self.update()

    # -- chargement -----------------------------------------------------------

    def _authorized(self, url: str) -> str:
        """Ajoute le jeton aux médias hébergés par notre serveur.

        Les requêtes Range du lecteur vidéo ne peuvent pas porter d'en-tête
        d'autorisation ; le jeton en paramètre est le seul chemin possible.
        Les URL du CDN Discord, elles, sont publiques et n'en ont pas besoin.
        """
        base = (self._settings["server_url"] or "").rstrip("/")
        token = self._settings["token"] or ""
        if base and token and url.startswith(base):
            joiner = "&" if "?" in url else "?"
            return f"{url}{joiner}token={token}"
        return url

    def _fetch(self, url: str, callback) -> None:
        reply = self._nam.get(QNetworkRequest(QUrl(self._authorized(url))))

        def done():
            data = bytes(reply.readAll()) if reply.error() == reply.NetworkError.NoError else b""
            reply.deleteLater()
            if data:
                callback(data)

        reply.finished.connect(done)

    def _on_avatar(self, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            # Conservé en pleine résolution : sa taille finale dépend de celle du
            # pseudo, que le participant peut changer à tout moment.
            self._avatar = pixmap
            self._relayout()

    def _on_image(self, data: bytes) -> None:
        if data[:3] == b"GIF":
            buffer = QBuffer(self)
            buffer.setData(QByteArray(data))
            buffer.open(QIODevice.ReadOnly)
            movie = QMovie(self)
            movie.setDevice(buffer)
            movie.setCacheMode(QMovie.CacheAll)
            if movie.isValid():
                self._movie_buffer = buffer
                self._movie = movie
                movie.frameChanged.connect(self._on_gif_frame)
                movie.start()
                self._relayout()
                self._arm_image_timer()
                return

        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            log.warning("Image illisible, ignorée.")
            return
        self._pixmap = pixmap
        self._relayout()
        self._arm_image_timer()

    def _on_gif_frame(self) -> None:
        if self._movie is not None:
            self._pixmap = self._movie.currentPixmap()
            self.update(self._block)

    def _arm_image_timer(self) -> None:
        self._hide_timer.start(self._settings.image_duration * 1000)
        self._acknowledge()

    def _play_video(self, url: str) -> None:
        self._player.setSource(QUrl(self._authorized(url)))
        self._player.play()

    def _on_frame(self, frame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        # Qt 6 applique lui-même la rotation portrait déclarée dans le conteneur :
        # la v1 devait lire les boîtes moov/trak/tkhd à la main pour y arriver.
        first = self._frame_image is None
        self._frame_image = image
        if first:
            self._relayout()
        self.update(self._block)

    def _on_media_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._acknowledge()
            self.clear()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            log.warning("Média vidéo illisible.")
            self.clear()

    def _acknowledge(self) -> None:
        """Prévient le serveur : c'est cet accusé qui déclenche l'effacement du fichier."""
        if self._media_id:
            self.acknowledged.emit(self._media_id)

    # -- son ------------------------------------------------------------------

    def apply_volume(self) -> None:
        self._audio.setMuted(bool(self._settings["muted"]))
        self._audio.setVolume(max(0, min(100, int(self._settings["volume"]))) / 100.0)

    # -- fondu ----------------------------------------------------------------

    def _fade_to(self, target: float) -> None:
        self._fade_target = target
        if target > 0 and not self.isVisible():
            self.show()
            platform.make_click_through(self)
            platform.reassert_topmost(self)
        self._fade.start(16)

    def _step_fade(self) -> None:
        span = 16 / max(theme.FADE_MS, 1)
        if self._opacity < self._fade_target:
            self._opacity = min(self._fade_target, self._opacity + span)
        elif self._opacity > self._fade_target:
            self._opacity = max(self._fade_target, self._opacity - span)
        else:
            self._fade.stop()
            if self._fade_target == 0.0:
                self._reset_media()
            return
        self.update(self._block.adjusted(-60, -60, 60, 60))

    # -- géométrie ------------------------------------------------------------

    def _media_size(self) -> QSize:
        source = self._source_size()
        if source.isEmpty():
            return QSize()
        area = self.rect()
        scale = self._settings.scale_percent / 100.0
        max_w = int(area.width() * scale)
        max_h = int(area.height() * scale * 1.5)
        return source.scaled(max_w, max_h, Qt.KeepAspectRatio)

    def _source_size(self) -> QSize:
        if self._frame_image is not None:
            return self._frame_image.size()
        if self._pixmap is not None:
            return self._pixmap.size()
        return QSize()

    def _fonts(self) -> tuple[QFont, QFont]:
        family = self._settings["font_family"]
        name = fonts.display_font(self._settings["name_size"], QFont.Black, family)
        caption = fonts.display_font(self._settings["caption_size"], QFont.Bold, family)
        return name, caption

    def _relayout(self) -> None:
        media = self._media_size()
        if media.isEmpty():
            self._block = QRect()
            self.update()
            return

        name_font, caption_font = self._fonts()
        position = self._settings["author_position"]
        header = 0
        if position == "above" and (self._author or self._avatar):
            header = self._author_row_height(name_font) + theme.AUTHOR_GAP

        caption_h = 0
        if self._caption:
            metrics = QFontMetrics(caption_font)
            rect = metrics.boundingRect(
                QRect(0, 0, media.width(), 4000), Qt.TextWordWrap | Qt.AlignHCenter, self._caption
            )
            caption_h = rect.height() + theme.CAPTION_GAP

        # Le bloc est aussi large que son élément le plus large : un pseudo long
        # dépasse la largeur du média, et sans ça il sortirait de l'écran. Au-delà
        # de la place disponible, c'est le pseudo qui est raccourci à la peinture —
        # jamais le média qu'on pousse hors de l'écran.
        width = media.width()
        if position == "above":
            width = max(width, self._author_row_width(name_font))
        width = min(width, max(media.width(), self.rect().width() - 2 * self._settings["margin"]))

        total = QSize(width, header + media.height() + caption_h)
        origin = self._anchor(total)
        self._block = QRect(origin, total)
        self.update()

    def _anchor(self, size: QSize) -> QPoint:
        area = self.rect()
        margin = self._settings["margin"]
        corner = self._settings["corner"]
        if corner == "center":
            return QPoint(
                (area.width() - size.width()) // 2, (area.height() - size.height()) // 2
            )
        x = margin if "left" in corner else area.width() - size.width() - margin
        y = margin if "top" in corner else area.height() - size.height() - margin
        return QPoint(max(0, x), max(0, y))

    # -- peinture -------------------------------------------------------------

    def paintEvent(self, event) -> None:
        if self._block.isEmpty() or self._opacity <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        painter.setOpacity(self._opacity * (self._settings["opacity_percent"] / 100.0))

        name_font, caption_font = self._fonts()
        media = self._media_size()
        position = self._settings["author_position"]

        top = self._block.top()
        if position == "above" and (self._author or self._avatar):
            self._paint_author(painter, QPoint(self._block.left(), top), name_font)
            top += self._author_row_height(name_font) + theme.AUTHOR_GAP

        # Le média garde sa taille : c'est le bloc qui s'élargit, pas lui.
        media_rect = QRect(self._block.left(), top, media.width(), media.height())
        self._paint_media(painter, media_rect)

        if position == "over" and (self._author or self._avatar):
            self._paint_author(
                painter,
                QPoint(media_rect.left() + 14, media_rect.top() + 14),
                name_font,
                shadow=True,
            )

        if self._caption:
            self._paint_caption(
                painter,
                QRect(media_rect.left(), media_rect.bottom() + theme.CAPTION_GAP,
                      media_rect.width(), self._block.bottom() - media_rect.bottom()),
                caption_font,
            )
        painter.end()

    def _paint_media(self, painter: QPainter, rect: QRect) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), theme.MEDIA_RADIUS, theme.MEDIA_RADIUS)

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.MEDIA_SHADOW)
        painter.drawRoundedRect(
            QRectF(rect).adjusted(-2, 2, 2, 6), theme.MEDIA_RADIUS + 2, theme.MEDIA_RADIUS + 2
        )
        painter.setClipPath(path)
        if self._frame_image is not None:
            painter.drawImage(rect, self._frame_image)
        elif self._pixmap is not None:
            painter.drawPixmap(rect, self._pixmap)
        painter.restore()

    @staticmethod
    def _avatar_size(font: QFont) -> int:
        """L'avatar suit la taille du pseudo, pour que la ligne reste équilibrée
        quelle que soit la taille choisie dans le panneau."""
        return max(theme.AVATAR_MIN, int(QFontMetrics(font).height() * theme.AVATAR_RATIO))

    def _author_row_height(self, font: QFont) -> int:
        return max(self._avatar_size(font), QFontMetrics(font).height())

    def _name_text(self) -> str:
        """Un média visé sur une seule personne doit le dire : sans ça, celle-ci
        ne peut pas savoir que les autres ne l'ont pas vu."""
        return f"{self._author} → vous" if self._private else self._author

    def _author_row_width(self, font: QFont) -> int:
        if self._settings["author_position"] != "above":
            return 0
        width = 0
        if self._avatar is not None:
            width += self._avatar_size(font) + theme.AVATAR_TEXT_GAP
        if self._author:
            # Le contour déborde de l'avance du texte, il faut le compter.
            width += QFontMetrics(font).horizontalAdvance(self._name_text())
            width += theme.NAME_OUTLINE_WIDTH
        return width

    def _paint_author(self, painter: QPainter, origin: QPoint, font: QFont,
                      shadow: bool = False) -> None:
        metrics = QFontMetrics(font)
        row_h = self._author_row_height(font)
        x = origin.x()

        if self._avatar is not None:
            size = self._avatar_size(font)
            top = origin.y() + (row_h - size) // 2
            circle = QRectF(x, top, size, size)

            painter.save()
            # Halo léger : sur un fond clair l'anneau vert perdrait son contraste.
            painter.setPen(QPen(theme.RING_GLOW, theme.RING_WIDTH + 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(circle)

            clip = QPainterPath()
            clip.addEllipse(circle)
            painter.setClipPath(clip)
            scaled = self._avatar.scaled(
                size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(circle.toRect(), scaled)
            painter.setClipping(False)

            painter.setPen(QPen(theme.RING_COLOR, theme.RING_WIDTH))
            painter.drawEllipse(circle)
            painter.restore()
            x += size + theme.AVATAR_TEXT_GAP

        if self._author:
            available = self._block.right() - x - theme.NAME_OUTLINE_WIDTH
            name = metrics.elidedText(self._name_text(), Qt.ElideRight, max(available, 1))
            baseline = origin.y() + (row_h + metrics.capHeight()) // 2
            self._paint_outlined(
                painter, name, QPoint(x, baseline), font,
                theme.NAME_COLOR, theme.NAME_OUTLINE_COLOR, theme.NAME_OUTLINE_WIDTH,
            )

    def _paint_caption(self, painter: QPainter, rect: QRect, font: QFont) -> None:
        metrics = QFontMetrics(font)
        painter.setFont(font)
        flags = Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop
        bounds = metrics.boundingRect(QRect(0, 0, rect.width(), 4000), flags, self._caption)

        y = rect.top() + metrics.ascent()
        for line in self._wrap(self._caption, metrics, rect.width()):
            width = metrics.horizontalAdvance(line)
            x = rect.left() + (rect.width() - width) // 2
            self._paint_outlined(
                painter, line, QPoint(x, y), font,
                theme.CAPTION_COLOR, theme.CAPTION_OUTLINE_COLOR, theme.CAPTION_OUTLINE_WIDTH,
            )
            y += metrics.lineSpacing()
        del bounds

    @staticmethod
    def _wrap(text: str, metrics: QFontMetrics, width: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _paint_outlined(painter: QPainter, text: str, baseline: QPoint, font: QFont,
                        fill: QColor, outline: QColor, width: int) -> None:
        """Texte blanc à contour noir épais.

        Impossible à obtenir proprement en v1 : le tag auteur y était une fenêtre
        séparée, et un contour se dessine, il ne se met pas en feuille de style.
        """
        path = QPainterPath()
        path.addText(baseline, font, text)
        painter.save()
        pen = QPen(outline, width)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)
        painter.restore()

    # -- réglages -------------------------------------------------------------

    def refresh(self) -> None:
        """Après une modification dans le panneau."""
        self.apply_volume()
        self.place_on_screen()
        self._relayout()
