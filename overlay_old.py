import sys
import os
import json
import ctypes
import socket
from urllib.parse import urlparse

# Force Windows Media Foundation (supporte HTTPS + H.264)
os.environ['QT_MULTIMEDIA_PREFERRED_PLUGINS'] = 'windowsmediafoundation'

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QGraphicsDropShadowEffect,
                              QSystemTrayIcon, QMenu, QAction, QVBoxLayout, QHBoxLayout,
                              QPushButton, QSlider, QCheckBox, QScrollArea, QFrame,
                              QSizePolicy)
from PyQt5.QtMultimedia import (QMediaPlayer, QMediaContent, QAbstractVideoSurface, QVideoFrame)
from PyQt5.QtCore import Qt, QUrl, QTimer, QBuffer, QIODevice, QRectF, pyqtSignal, QPoint
from PyQt5.QtGui import QPixmap, QMovie, QColor, QImage, QPainter, QPainterPath, QTransform
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtWebSockets import QWebSocket

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    with open(os.path.join(BASE_DIR, "config.json")) as f:
        config = json.load(f)
    SERVER = config.get("server", "http://localhost:3000").rstrip("/")
except Exception as e:
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(
            0, f"Impossible de lire config.json :\n{e}", "LiveChat Overlay — Erreur", 0x10)
    sys.exit(1)

WS_URL = SERVER.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
MARGIN = 40
MAX_W  = 0.30
MAX_H  = 0.45
RADIUS = 14


def _is_local_server():
    """Renvoie True si le serveur tourne sur cette machine."""
    host = urlparse(SERVER).hostname
    if host in ('localhost', '127.0.0.1', '::1'):
        return True
    try:
        server_ip = socket.gethostbyname(host)
        # IPs locales : loopback + toutes les interfaces
        local_ips = {'127.0.0.1', '::1'}
        try:
            local_ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except Exception:
            pass
        # Vérifie aussi toutes les interfaces réseau via socket
        import socket as _s
        for info in _s.getaddrinfo(_s.gethostname(), None):
            local_ips.add(info[4][0])
        # IP publique : connexion sortante
        try:
            s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
        return server_ip in local_ips
    except Exception:
        return False


IS_ADMIN = config.get("admin", False) or _is_local_server()


def _get_autostart():
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        winreg.QueryValueEx(key, "LiveChatOverlay")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _set_autostart(enable):
    if sys.platform != 'win32':
        return
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    if enable:
        exe = sys.executable
        winreg.SetValueEx(key, "LiveChatOverlay", 0, winreg.REG_SZ, f'"{exe}"')
    else:
        try:
            winreg.DeleteValue(key, "LiveChatOverlay")
        except Exception:
            pass
    winreg.CloseKey(key)


def _mp4_rotation(data: bytes) -> int:
    import struct

    def boxes(buf, start, stop):
        i = start
        while i + 8 <= stop and i + 8 <= len(buf):
            sz = struct.unpack_from('>I', buf, i)[0]
            if sz < 8:
                break
            yield buf[i+4:i+8], i+8, min(i+sz, stop)
            i += sz

    for t, s, e in boxes(data, 0, len(data)):
        if t == b'moov':
            for t2, s2, e2 in boxes(data, s, e):
                if t2 == b'trak':
                    for t3, s3, e3 in boxes(data, s2, e2):
                        if t3 == b'tkhd' and e3 - s3 >= 48:
                            v = data[s3]
                            off = s3 + (40 if v == 0 else 52)
                            if off + 24 > len(data):
                                continue
                            a  = struct.unpack_from('>i', data, off)[0] / 65536
                            b_ = struct.unpack_from('>i', data, off+4)[0] / 65536
                            c_ = struct.unpack_from('>i', data, off+12)[0] / 65536
                            d  = struct.unpack_from('>i', data, off+16)[0] / 65536
                            ra, rb, rc, rd = round(a), round(b_), round(c_), round(d)
                            if   ra== 0 and rb== 1 and rc==-1 and rd== 0: return 90
                            elif ra==-1 and rb== 0 and rc== 0 and rd==-1: return 180
                            elif ra== 0 and rb==-1 and rc== 1 and rd== 0: return 270
    return 0


def rounded_pixmap(pixmap, radius=RADIUS):
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    p = QPainter(result)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(result.rect()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pixmap)
    p.end()
    return result


PANEL_STYLE = """
QWidget#panel {
    background: #1e1e2e;
    border-radius: 12px;
    border: 1px solid #444466;
}
QLabel#title {
    color: #cdd6f4;
    font: bold 13px sans-serif;
}
QLabel#section {
    color: #a6adc8;
    font: bold 11px sans-serif;
    margin-top: 6px;
}
QLabel#client_entry {
    color: #cdd6f4;
    font: 11px sans-serif;
    background: #313244;
    border-radius: 6px;
    padding: 4px 8px;
}
QPushButton {
    background: #313244;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    font: 12px sans-serif;
    padding: 6px 10px;
}
QPushButton:hover  { background: #45475a; }
QPushButton:pressed { background: #585b70; }
QPushButton#danger {
    background: #f38ba8;
    color: #1e1e2e;
    font: bold 12px sans-serif;
}
QPushButton#danger:hover { background: #eba0ac; }
QPushButton#close_btn {
    background: transparent;
    color: #6c7086;
    font: bold 14px sans-serif;
    padding: 2px 6px;
}
QPushButton#close_btn:hover { color: #f38ba8; background: transparent; }
QSlider::groove:horizontal {
    height: 4px;
    background: #45475a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #89b4fa;
    border-radius: 2px;
}
QCheckBox {
    color: #cdd6f4;
    font: 12px sans-serif;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 2px solid #585b70;
    background: #313244;
}
QCheckBox::indicator:checked {
    background: #89b4fa;
    border-color: #89b4fa;
}
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
"""


class Panel(QWidget):
    def __init__(self, player, nam):
        super().__init__()
        self.player = player
        self.nam    = nam
        self._drag_pos = None

        self.setObjectName("panel")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(PANEL_STYLE)
        self.setFixedWidth(280)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(6)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("LiveChat Overlay")
        title.setObjectName("title")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("close_btn")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(close_btn)
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        root.addWidget(sep)

        # ── Volume ────────────────────────────────────────────────────────────
        vol_label = QLabel("Volume")
        vol_label.setObjectName("section")
        root.addWidget(vol_label)

        vol_row = QHBoxLayout()
        self.mute_btn = QPushButton("🔇 Muet")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._on_mute_toggle)
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(player.volume())
        self.vol_slider.valueChanged.connect(self._on_volume)
        vol_row.addWidget(self.mute_btn)
        vol_row.addWidget(self.vol_slider)
        root.addLayout(vol_row)

        # ── Démarrage auto ────────────────────────────────────────────────────
        startup_label = QLabel("Système")
        startup_label.setObjectName("section")
        root.addWidget(startup_label)

        self.startup_cb = QCheckBox("Lancer au démarrage de Windows")
        self.startup_cb.setChecked(_get_autostart())
        self.startup_cb.toggled.connect(_set_autostart)
        root.addWidget(self.startup_cb)

        # ── Admin ─────────────────────────────────────────────────────────────
        if IS_ADMIN:
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.HLine)
            sep2.setStyleSheet("color: #313244; margin-top: 4px;")
            root.addWidget(sep2)

            admin_hdr = QHBoxLayout()
            admin_label = QLabel("Admin")
            admin_label.setObjectName("section")
            self.refresh_btn = QPushButton("↻")
            self.refresh_btn.setFixedSize(24, 24)
            self.refresh_btn.clicked.connect(self._refresh_clients)
            admin_hdr.addWidget(admin_label)
            admin_hdr.addStretch()
            admin_hdr.addWidget(self.refresh_btn)
            root.addLayout(admin_hdr)

            # Liste clients
            self.clients_area = QScrollArea()
            self.clients_area.setWidgetResizable(True)
            self.clients_area.setFixedHeight(100)
            self.clients_widget = QWidget()
            self.clients_layout = QVBoxLayout(self.clients_widget)
            self.clients_layout.setContentsMargins(0, 0, 0, 0)
            self.clients_layout.setSpacing(3)
            self.clients_layout.addStretch()
            self.clients_area.setWidget(self.clients_widget)
            root.addWidget(self.clients_area)

            # Actions admin
            actions_row = QHBoxLayout()
            clear_btn = QPushButton("🗑 Retirer média")
            clear_btn.setObjectName("danger")
            clear_btn.clicked.connect(self._admin_clear)
            mute_all_btn = QPushButton("🔇 Couper son (tous)")
            mute_all_btn.clicked.connect(self._admin_mute)
            unmute_all_btn = QPushButton("🔊 Son (tous)")
            unmute_all_btn.clicked.connect(self._admin_unmute)
            actions_row.addWidget(clear_btn)
            root.addLayout(actions_row)
            actions_row2 = QHBoxLayout()
            actions_row2.addWidget(mute_all_btn)
            actions_row2.addWidget(unmute_all_btn)
            root.addLayout(actions_row2)

            # Rafraîchissement auto toutes les 5s
            self._refresh_timer = QTimer(self)
            self._refresh_timer.timeout.connect(self._refresh_clients)
            self._refresh_timer.start(5000)

        self.adjustSize()

    # ── Volume ────────────────────────────────────────────────────────────────

    def _on_volume(self, val):
        self.player.setVolume(val)
        if val == 0:
            self.mute_btn.setChecked(True)
        elif self.mute_btn.isChecked():
            self.mute_btn.setChecked(False)

    def _on_mute_toggle(self, muted):
        self.player.setMuted(muted)
        self.mute_btn.setText("🔊 Son" if muted else "🔇 Muet")

    # ── Admin ─────────────────────────────────────────────────────────────────

    def _refresh_clients(self):
        reply = self.nam.get(QNetworkRequest(QUrl(f"{SERVER}/admin/clients")))

        def done():
            if reply.error() != QNetworkReply.NoError:
                reply.deleteLater()
                return
            try:
                clients = json.loads(bytes(reply.readAll()).decode())
            except Exception:
                reply.deleteLater()
                return
            reply.deleteLater()

            # Vider la liste
            while self.clients_layout.count() > 1:
                item = self.clients_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            if not clients:
                lbl = QLabel("Aucun client connecté")
                lbl.setObjectName("client_entry")
                self.clients_layout.insertWidget(0, lbl)
            else:
                for i, c in enumerate(clients):
                    lbl = QLabel(f"  {c['host']}  —  {c['ip']}")
                    lbl.setObjectName("client_entry")
                    self.clients_layout.insertWidget(i, lbl)

        reply.finished.connect(done)

    def _admin_post(self, endpoint):
        req = QNetworkRequest(QUrl(f"{SERVER}/admin/{endpoint}"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        reply = self.nam.post(req, b"{}")
        reply.finished.connect(reply.deleteLater)

    def _admin_clear(self):   self._admin_post("clear")
    def _admin_mute(self):    self._admin_post("mute")
    def _admin_unmute(self):  self._admin_post("unmute")

    # ── Drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


# ─────────────────────────────────────────────────────────────────────────────


class FrameSurface(QAbstractVideoSurface):
    frame_ready = pyqtSignal(QImage)

    def supportedPixelFormats(self, handle_type=None):
        return [getattr(QVideoFrame, a) for a in dir(QVideoFrame)
                if a.startswith('Format_') and a != 'Format_Invalid']

    def present(self, frame):
        if not frame.isValid():
            return True
        img = frame.image()
        if img.isNull():
            print(f"frame null — format: {frame.pixelFormat()}, size: {frame.width()}x{frame.height()}")
        else:
            self.frame_ready.emit(img)
        return True


class Overlay(QWidget):
    _show = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        app    = QApplication.instance()
        screen = app.primaryScreen().availableGeometry()
        self.sw, self.sh = screen.width(), screen.height()
        self.max_w = int(self.sw * MAX_W)
        self.max_h = int(self.sh * MAX_H)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(screen)

        self.label = QLabel(self)
        self.label.setAttribute(Qt.WA_TranslucentBackground, True)
        self.label.hide()

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 153))
        self.label.setGraphicsEffect(shadow)

        self.auth = QLabel(self)
        self.auth.setStyleSheet(
            "color:white; font:bold 14px sans-serif;"
            "background:rgba(0,0,0,160);"
            "border-bottom-left-radius:14px; border-bottom-right-radius:14px;"
            "padding:4px 12px 8px;"
        )
        self.auth.hide()

        self.surface = FrameSurface(self)
        self.surface.frame_ready.connect(self._on_frame)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.surface)
        self.player.setVolume(100)
        self.player.stateChanged.connect(self._on_player_state)
        self.player.error.connect(lambda e: print(f"Player erreur {e}: {self.player.errorString()}"))
        self._rotation = 0
        self._stopping = False

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._hide)

        self.nam    = QNetworkAccessManager(self)
        self._movie = None
        self._buf   = None
        self._video_w = self.max_w
        self._video_h = int(self.max_w * 9 / 16)

        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._on_msg)
        self.ws.disconnected.connect(lambda: QTimer.singleShot(2000, self._connect))
        self.ws.error.connect(      lambda: QTimer.singleShot(2000, self._connect))

        self._show.connect(self._display)

        # Panneau
        self.panel = Panel(self.player, self.nam)

    # ── démarrage ─────────────────────────────────────────────────────────────

    def start(self):
        self.show()
        self._clickthrough()
        self._connect()
        self._setup_tray()

    def _setup_tray(self):
        icon = self.style().standardIcon(self.style().SP_ComputerIcon)
        self._tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        panel_action = QAction("Panneau", self)
        panel_action.triggered.connect(self._toggle_panel)
        quit_action  = QAction("Quitter", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(panel_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._toggle_panel() if reason == QSystemTrayIcon.Trigger else None)
        self._tray.setToolTip("LiveChat Overlay")
        self._tray.show()

    def _toggle_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            # Positionne le panneau en bas à droite au-dessus de la barre des tâches
            screen = QApplication.instance().primaryScreen().availableGeometry()
            self.panel.adjustSize()
            x = screen.right()  - self.panel.width()  - 10
            y = screen.bottom() - self.panel.height() - 10
            self.panel.move(x, y)
            self.panel.show()
            self.panel.raise_()
            if IS_ADMIN:
                self.panel._refresh_clients()

    # ── WebSocket ─────────────────────────────────────────────────────────────

    def _connect(self):
        self.ws.open(QUrl(WS_URL))

    def _on_msg(self, raw):
        try:
            data = json.loads(raw)
        except Exception:
            return

        t = data.get("type")
        if t == "clear":
            self._hide()
        elif t == "mute":
            self.player.setMuted(True)
            self.panel.mute_btn.setChecked(True)
        elif t == "unmute":
            self.player.setMuted(False)
            self.panel.mute_btn.setChecked(False)
        else:
            self._show.emit(data)

    # ── affichage ─────────────────────────────────────────────────────────────

    def _display(self, data):
        self.timer.stop()
        self.label.hide()
        self.auth.hide()
        self._stopping = True
        self.player.stop()
        self._stopping = False
        if self._movie:
            self._movie.stop()
            self._movie = None
        self._buf = None

        author   = data.get("author", "")
        url      = data.get("url", "")
        duration = int(data.get("duration", 8))
        scale    = data.get("scale", MAX_W * 100) / 100

        self.max_w = int(self.sw * scale)
        self.max_h = int(self.sh * scale * (MAX_H / MAX_W))

        if data.get("type") == "video":
            self._play_video(url, author)
        else:
            self._fetch_image(url, author, duration)

    def _fetch_image(self, url, author, duration):
        reply = self.nam.get(QNetworkRequest(QUrl(url)))

        def done():
            if reply.error() != QNetworkReply.NoError:
                reply.deleteLater()
                return
            raw = reply.readAll()
            reply.deleteLater()

            if bytes(raw[:6])[:3] == b"GIF":
                buf = QBuffer()
                buf.setData(raw)
                buf.open(QIODevice.ReadOnly)
                movie = QMovie()
                movie.setDevice(buf)
                movie.jumpToFrame(0)
                orig = movie.currentPixmap().size()
                if movie.isValid() and orig.width() > 0:
                    scaled = orig.scaled(self.max_w, self.max_h, Qt.KeepAspectRatio)
                    movie.setScaledSize(scaled)
                    w, h = scaled.width(), scaled.height()
                    self._buf, self._movie = buf, movie
                    self.label.setMovie(movie)
                    self._place(self.label, w, h)
                    self.label.show()
                    self._show_auth(author, w, h)
                    movie.start()
                    self.timer.start(duration * 1000)
                    return

            pix = QPixmap()
            if pix.loadFromData(raw):
                pix = pix.scaled(self.max_w, self.max_h,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pix = rounded_pixmap(pix)
                w, h = pix.width(), pix.height()
                self.label.setPixmap(pix)
                self._place(self.label, w, h)
                self.label.show()
                self._show_auth(author, w, h)
                self.timer.start(duration * 1000)

        reply.finished.connect(done)

    def _play_video(self, url, author):
        self._video_w = self.max_w
        self._video_h = int(self.max_w * 9 / 16)
        self._rotation = 0
        self._place(self.label, self._video_w, self._video_h)
        self._show_auth(author, self._video_w, self._video_h)

        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"Range", b"bytes=0-131071")
        reply = self.nam.get(req)

        def _start():
            self._rotation = _mp4_rotation(bytes(reply.readAll()))
            reply.deleteLater()
            self.player.setMedia(QMediaContent(QUrl(url)))
            self.player.play()

        reply.finished.connect(_start)

    def _on_frame(self, img):
        if self._rotation:
            img = img.transformed(QTransform().rotate(self._rotation))
        w, h = img.width(), img.height()
        if w > 0 and h > 0:
            scaled = img.scaled(self.max_w, self.max_h,
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            w, h = scaled.width(), scaled.height()
            if w != self._video_w or h != self._video_h:
                self._video_w, self._video_h = w, h
                self._place(self.label, w, h)
                auth = self.auth.text()
                if auth:
                    self._show_auth(auth, w, h)
            self.label.setPixmap(QPixmap.fromImage(scaled))
            if not self.label.isVisible():
                self.label.show()

    def _on_player_state(self, state):
        if state == QMediaPlayer.StoppedState and not self._stopping:
            self._hide()

    # ── utilitaires ───────────────────────────────────────────────────────────

    def _place(self, widget, w, h):
        x = self.sw - w - MARGIN
        y = self.sh - h - MARGIN
        widget.setGeometry(x, y, w, h)

    def _show_auth(self, text, content_w, content_h):
        if not text:
            return
        self.auth.setText(text)
        self.auth.setFixedWidth(content_w)
        self.auth.adjustSize()
        x = self.sw - content_w - MARGIN
        y = self.sh - MARGIN - self.auth.height()
        self.auth.setGeometry(x, y, content_w, self.auth.height())
        self.auth.show()

    def _hide(self):
        self._stopping = True
        self.player.stop()
        self._stopping = False
        if self._movie:
            self._movie.stop()
            self._movie = None
        self._buf = None
        self.label.clear()
        self.label.setGeometry(0, 0, 0, 0)
        self.label.hide()
        self.auth.hide()

    def _clickthrough(self):
        if sys.platform == 'win32':
            try:
                import win32gui, win32con
                hwnd  = int(self.winId())
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE,
                    style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED)
                print("Overlay actif — clic-traversant activé.")
            except Exception as e:
                print(f"(clic-traversant non disponible : {e})")
        elif sys.platform == 'darwin':
            try:
                import ctypes, ctypes.util
                objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
                objc.sel_registerName.restype  = ctypes.c_void_p
                objc.objc_msgSend.restype      = ctypes.c_void_p
                objc.objc_msgSend.argtypes     = [ctypes.c_void_p, ctypes.c_void_p]
                ns_view   = int(self.winId())
                ns_window = objc.objc_msgSend(ns_view, objc.sel_registerName(b'window'))
                ignore_sel = objc.sel_registerName(b'setIgnoresMouseEvents:')
                send = objc.objc_msgSend
                send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
                send.restype  = None
                send(ns_window, ignore_sel, True)
                print("Overlay actif — clic-traversant activé (Mac).")
            except Exception as e:
                print(f"(clic-traversant non disponible : {e})")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ov  = Overlay()
    ov.start()
    sys.exit(app.exec_())
