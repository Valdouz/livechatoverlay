"""L'overlay : une seule fenêtre, tout est peint dedans.

La v1 empilait cinq fenêtres de premier niveau — média, auteur, légende, vidéo,
panneau — qui se disputaient le z-order du système, d'où les `hide()/show()` de
colmatage pour forcer le tag auteur devant la vidéo. Ici il n'y a qu'une fenêtre :
le conflit ne peut plus exister, et le contour du texte devient trois lignes de
`QPainter` au lieu d'un problème insoluble.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (QBuffer, QByteArray, QEasingCurve, QIODevice, QPoint,
                            QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal)
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
        self._video_native = QSize()
        self._frame_dirty = False
        self._author = ""
        self._avatar: QPixmap | None = None
        self._caption = ""
        self._private = False
        self._filename = ""
        self._animation = "fade"
        self._progress = 0.0
        self._block = QRect()

        # -- vidéo ------------------------------------------------------------
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._player.setAudioOutput(self._audio)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        # La carte audio affiche l'avancement : il faut la repeindre en continu.
        self._player.positionChanged.connect(lambda _: self.update(self._paint_region()))
        self._player.errorOccurred.connect(
            lambda _, message: log.warning("Lecture vidéo : %s", message)
        )
        self.apply_volume()

        # -- minuteries -------------------------------------------------------
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.clear)

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step_animation)
        self._anim_target = 0.0

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
        # Un média qui en remplace un autre repart de zéro. Sans ça l'avancement
        # valait encore 1 et l'animation se croyait terminée : seul le tout
        # premier média du groupe s'animait.
        self._progress = 0.0
        self._media_id = media.get("id")
        self._kind = media.get("kind", "image")
        self._animation = media.get("animation", "fade")
        self._filename = media.get("filename", "")
        self._author = author.get("display_name", "")
        self._caption = (payload.get("caption") or "").strip()
        self._private = bool(payload.get("private"))
        self._avatar = None

        avatar_url = author.get("avatar_url", "")
        if avatar_url:
            self._fetch(avatar_url, self._on_avatar)

        url = media.get("url", "")
        if self._kind in ("video", "audio"):
            self._play_media(url)
        else:
            self._fetch(url, self._on_image)

        self._fade_to(1.0)

    def clear(self) -> None:
        if self._media_id or self._pixmap or self._frame_image or self._kind == "audio":
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
        self._video_native = QSize()
        self._frame_dirty = False
        self._media_id = None
        self._caption = ""
        self._author = ""
        self._private = False
        self._filename = ""
        self._kind = ""
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

    def _play_media(self, url: str) -> None:
        """Vidéo et audio passent par le même lecteur ; seul le rendu diffère."""
        self._player.setSource(QUrl(self._authorized(url)))
        self._player.play()
        if self._kind == "audio":
            # Pas d'image à attendre : la carte peut être placée tout de suite.
            self._relayout()
            self._acknowledge()

    def _on_frame(self, frame) -> None:
        # Une trame reçue alors que la précédente n'est pas encore peinte est
        # abandonnée. Sans ce garde-fou, chaque trame paie sa conversion en image
        # même quand l'affichage a déjà du retard : le retard s'accumule et la
        # lecture saccade. En sautant, on descend simplement en fréquence.
        if self._frame_dirty:
            return
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return

        # Qt 6 applique lui-même la rotation portrait déclarée dans le conteneur :
        # la v1 devait lire les boîtes moov/trak/tkhd à la main pour y arriver.
        first = self._video_native.isEmpty()
        if first:
            self._video_native = image.size()

        # Réduire une fois ici plutôt qu'à chaque peinture : une trame 4K affichée
        # dans une vignette était redimensionnée soixante fois par seconde.
        target = self._media_size()
        if not target.isEmpty() and image.width() > target.width() * 1.5:
            image = image.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._frame_image = image
        self._frame_dirty = True
        if first:
            self._relayout()
        self.update(self._paint_region())

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
        self._anim_target = target
        if target > 0 and not self.isVisible():
            self.show()
            platform.make_click_through(self)
            platform.reassert_topmost(self)
        if self._animation == "none":
            self._progress = target
            self.update(self._paint_region())
            if target == 0.0:
                self._reset_media()
            return
        self._anim_timer.start(16)

    def _step_animation(self) -> None:
        step = 16 / max(theme.ANIMATION_MS, 1)
        if self._progress < self._anim_target:
            self._progress = min(self._anim_target, self._progress + step)
        elif self._progress > self._anim_target:
            self._progress = max(self._anim_target, self._progress - step)
        else:
            self._anim_timer.stop()
            if self._anim_target == 0.0:
                self._reset_media()
            return
        self.update(self._paint_region())

    def _paint_region(self) -> QRect:
        """Zone à repeindre.

        Pendant une animation le bloc sort de ses bornes, il faut donc peindre
        large. Au repos on s'en tient au bloc : une vidéo repeint à chaque image,
        et élargir la zone de 70 % à 60 images par seconde coûte cher pour rien.
        """
        if self._block.isEmpty():
            return self.rect()
        if not self._anim_timer.isActive():
            return self._block.adjusted(-2, -2, 2, 2)
        margin = max(80, int(max(self._block.width(), self._block.height()) * 0.7))
        return self._block.adjusted(-margin, -margin, margin, margin)

    def _animation_state(self) -> tuple[QPointF, float, float]:
        """Décalage, échelle et opacité pour l'avancement courant."""
        progress = self._progress
        name = self._animation
        if name == "none":
            return QPointF(0, 0), 1.0, 1.0 if progress > 0.5 else 0.0

        eased = QEasingCurve(QEasingCurve.OutCubic).valueForProgress(progress)
        if name == "fade":
            return QPointF(0, 0), 1.0, eased

        if name.startswith("slide-"):
            span = max(self._block.width(), self._block.height()) * 0.45
            travel = span * (1.0 - eased)
            direction = {
                "slide-up": (0, 1), "slide-down": (0, -1),
                "slide-left": (1, 0), "slide-right": (-1, 0),
            }[name]
            return QPointF(direction[0] * travel, direction[1] * travel), 1.0, eased

        if name == "zoom":
            return QPointF(0, 0), 0.72 + 0.28 * eased, eased

        if name == "bounce":
            # OutBack dépasse volontairement 1 puis revient : c'est le rebond.
            back = QEasingCurve(QEasingCurve.OutBack).valueForProgress(progress)
            return QPointF(0, 0), 0.55 + 0.45 * back, min(1.0, progress * 2.2)

        return QPointF(0, 0), 1.0, eased

    # -- géométrie ------------------------------------------------------------

    def _media_size(self) -> QSize:
        area = self.rect()
        scale = self._settings.scale_percent / 100.0
        max_w = max(1, int(area.width() * scale))

        if self._kind == "audio":
            # Rien à afficher du fichier lui-même : une carte de proportions fixes.
            height = int(max_w * theme.AUDIO_HEIGHT_RATIO)
            height = max(theme.AUDIO_HEIGHT_MIN, min(theme.AUDIO_HEIGHT_MAX, height))
            return QSize(max_w, height)

        source = self._source_size()
        if source.isEmpty():
            return QSize()
        max_h = int(area.height() * scale * 1.5)
        return source.scaled(max_w, max_h, Qt.KeepAspectRatio)

    def _source_size(self) -> QSize:
        # Toujours la taille native, jamais celle de la trame réduite : sinon la
        # mise en page se recalculerait sur sa propre sortie et rétrécirait.
        if not self._video_native.isEmpty():
            return self._video_native
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
        if self._block.isEmpty():
            return
        offset, scale, opacity = self._animation_state()
        if opacity <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        painter.setOpacity(opacity * (self._settings["opacity_percent"] / 100.0))

        # L'animation déplace et met à l'échelle l'ensemble du bloc, autour de son
        # centre : le média, l'auteur et la légende restent solidaires.
        if not offset.isNull():
            painter.translate(offset)
        if abs(scale - 1.0) > 0.001:
            center = QPointF(self._block.center())
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)

        name_font, caption_font = self._fonts()
        media = self._media_size()
        position = self._settings["author_position"]

        top = self._block.top()
        if position == "above" and (self._author or self._avatar):
            self._paint_author(painter, QPoint(self._block.left(), top), name_font,
                               width=self._block.width())
            top += self._author_row_height(name_font) + theme.AUTHOR_GAP

        # Le média garde sa taille : c'est le bloc qui s'élargit, pas lui.
        media_rect = QRect(self._block.left(), top, media.width(), media.height())
        if self._kind == "audio":
            self._paint_audio(painter, media_rect)
        else:
            self._paint_media(painter, media_rect)

        if position == "over" and (self._author or self._avatar):
            self._paint_author(
                painter,
                QPoint(media_rect.left() + 14, media_rect.top() + 14),
                name_font,
                width=media_rect.width() - 28,
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
        # La trame est à l'écran : le lecteur peut en proposer une nouvelle.
        self._frame_dirty = False

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

    def _paint_audio(self, painter: QPainter, rect: QRect) -> None:
        """Un fichier audio n'a rien à montrer : on dessine une carte de lecture
        avec le nom du fichier et l'avancement."""
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.MEDIA_SHADOW)
        painter.drawRoundedRect(
            QRectF(rect).adjusted(-2, 2, 2, 6), theme.MEDIA_RADIUS + 2, theme.MEDIA_RADIUS + 2
        )
        painter.setBrush(theme.AUDIO_BACKGROUND)
        painter.drawRoundedRect(QRectF(rect), theme.MEDIA_RADIUS, theme.MEDIA_RADIUS)

        pad = max(12, rect.height() // 6)
        disc = rect.height() - 2 * pad
        circle = QRectF(rect.left() + pad, rect.top() + pad, disc, disc)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.AUDIO_ACCENT, max(2, disc // 14)))
        painter.drawEllipse(circle)

        note = fonts.display_font(max(12, int(disc * 0.42)), QFont.Black)
        painter.setFont(note)
        painter.setPen(theme.AUDIO_ACCENT)
        painter.drawText(circle, Qt.AlignCenter, "♪")

        text_left = int(circle.right()) + pad
        text_width = rect.right() - text_left - pad
        title_font = fonts.display_font(max(11, int(disc * 0.28)), QFont.Bold)
        metrics = QFontMetrics(title_font)
        title = metrics.elidedText(
            self._filename or "Audio", Qt.ElideMiddle, max(text_width, 1)
        )
        painter.setFont(title_font)
        painter.setPen(theme.AUDIO_TITLE)
        painter.drawText(
            QRect(text_left, rect.top() + pad, text_width, disc // 2),
            Qt.AlignLeft | Qt.AlignVCenter, title,
        )

        # Barre d'avancement : sans elle on ne saurait pas combien il reste.
        bar_h = max(4, disc // 10)
        bar = QRectF(text_left, rect.bottom() - pad - bar_h, text_width, bar_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.AUDIO_TRACK)
        painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)

        duration = self._player.duration()
        if duration > 0:
            done = max(0.0, min(1.0, self._player.position() / duration))
            if done > 0:
                painter.setBrush(theme.AUDIO_ACCENT)
                filled = QRectF(bar.left(), bar.top(), bar.width() * done, bar_h)
                painter.drawRoundedRect(filled, bar_h / 2, bar_h / 2)
        painter.restore()

    def _paint_author(self, painter: QPainter, origin: QPoint, font: QFont,
                      width: int = 0, shadow: bool = False) -> None:
        """Dessine avatar et pseudo, rangés à gauche ou à droite.

        À droite, l'ordre s'inverse : pseudo puis avatar. L'avatar reste ainsi
        contre le bord, comme à gauche, et la ligne se lit de la même façon en
        miroir plutôt que de paraître décalée.
        """
        metrics = QFontMetrics(font)
        row_h = self._author_row_height(font)
        avatar = self._avatar_size(font) if self._avatar is not None else 0
        right_side = self._settings["author_side"] == "right"

        span = width or self._block.width()
        available = span - avatar - (theme.AVATAR_TEXT_GAP if avatar else 0)
        name = metrics.elidedText(
            self._name_text(), Qt.ElideRight,
            max(available - theme.NAME_OUTLINE_WIDTH, 1),
        ) if self._author else ""
        name_width = metrics.horizontalAdvance(name) if name else 0

        used = avatar + (theme.AVATAR_TEXT_GAP if avatar and name else 0) + name_width
        start = origin.x() + (span - used if right_side else 0)

        # À droite le pseudo précède l'avatar ; à gauche c'est l'inverse.
        avatar_x = start + name_width + theme.AVATAR_TEXT_GAP if right_side else start
        name_x = start if right_side else start + avatar + (
            theme.AVATAR_TEXT_GAP if avatar else 0
        )

        if avatar:
            top = origin.y() + (row_h - avatar) // 2
            circle = QRectF(avatar_x, top, avatar, avatar)

            painter.save()
            # Halo léger : sur un fond clair l'anneau vert perdrait son contraste.
            painter.setPen(QPen(theme.RING_GLOW, theme.RING_WIDTH + 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(circle)

            clip = QPainterPath()
            clip.addEllipse(circle)
            painter.setClipPath(clip)
            scaled = self._avatar.scaled(
                avatar, avatar, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(circle.toRect(), scaled)
            painter.setClipping(False)

            painter.setPen(QPen(theme.RING_COLOR, theme.RING_WIDTH))
            painter.drawEllipse(circle)
            painter.restore()

        if name:
            baseline = origin.y() + (row_h + metrics.capHeight()) // 2
            self._paint_outlined(
                painter, name, QPoint(name_x, baseline), font,
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
