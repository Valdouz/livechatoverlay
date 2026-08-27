"""Point d'entrée du client.

Le forçage de la plateforme Qt doit précéder l'import de PySide6 : sous Wayland, une
application ordinaire ne peut ni se positionner en coordonnées globales ni rester au
premier plan. En passant par XWayland on récupère les deux — c'est exactement ce que
font tous les overlays qui fonctionnent sous GNOME.
"""

from __future__ import annotations

import os
import sys

if sys.platform not in ("win32", "darwin") and not os.environ.get("LIVECHAT_KEEP_PLATFORM"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6.QtCore import QStandardPaths, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from . import theme  # noqa: E402
from .api import Api  # noqa: E402
from .overlay import Overlay  # noqa: E402
from .panel import Panel  # noqa: E402
from .settings import ClientSettings  # noqa: E402

log = logging.getLogger("livechat.client")

ADMIN_REFRESH_MS = 5000


def settings_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    return Path(base or Path.home() / ".config" / "LiveChat") / "settings.json"


def make_icon() -> QIcon:
    """Icône dessinée à la volée : un fichier de moins à embarquer."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#16161f"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    pen = painter.pen()
    pen.setColor(theme.RING_COLOR)
    pen.setWidth(6)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pixmap)


class LiveChatClient:
    def __init__(self, app: QApplication):
        self._app = app
        self._settings = ClientSettings(settings_path())
        self._api = Api(self._settings)
        self._overlay = Overlay(self._settings)
        self._panel = Panel(self._settings)

        self._wire()
        self._build_tray()

        # Le suivi des écrans branchés à chaud : la liste du panneau doit rester juste.
        QGuiApplication.instance().screenAdded.connect(self._on_screens_changed)
        QGuiApplication.instance().screenRemoved.connect(self._on_screens_changed)

        self._admin_timer = QTimer()
        self._admin_timer.timeout.connect(self._refresh_admin)

        if self._settings["server_url"] and self._settings["token"]:
            self._api.fetch_me()
        else:
            self._panel.open_near_cursor()

    # -- câblage --------------------------------------------------------------

    def _wire(self) -> None:
        api, overlay, panel = self._api, self._overlay, self._panel

        api.authenticated.connect(self._on_authenticated)
        api.auth_pending.connect(self._on_auth_pending)
        api.auth_failed.connect(lambda message: (panel.set_identity(None),
                                                 panel.notify(message, error=True)))
        api.connected.connect(lambda: panel.set_connected(True))
        api.disconnected.connect(lambda: panel.set_connected(False, "Reconnexion…"))
        api.media_received.connect(overlay.show_media)
        api.command_received.connect(self._on_command)

        api.upload_progress.connect(panel.upload_progress)
        api.upload_finished.connect(lambda _: panel.upload_ended("Média envoyé."))
        api.upload_failed.connect(lambda message: panel.upload_ended(message, error=True))
        api.admin_data.connect(self._on_admin_data)
        api.admin_error.connect(lambda message: panel.notify(message, error=True))

        overlay.acknowledged.connect(api.acknowledge)

        panel.login_requested.connect(api.login)
        panel.logout_requested.connect(self._on_logout)
        panel.settings_changed.connect(overlay.refresh)
        panel.upload_requested.connect(self._on_upload)
        panel.upload_cancelled.connect(api.cancel_upload)
        panel.admin_action.connect(self._on_admin_action)

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(make_icon())
        menu = QMenu()

        open_panel = QAction("Ouvrir le panneau", menu)
        open_panel.triggered.connect(self._panel.open_near_cursor)
        hide_media = QAction("Masquer le média", menu)
        hide_media.triggered.connect(self._overlay.clear)
        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(self._quit)

        menu.addAction(open_panel)
        menu.addAction(hide_media)
        menu.addSeparator()
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.setToolTip("LiveChat")
        self._tray.activated.connect(
            lambda reason: self._panel.open_near_cursor()
            if reason == QSystemTrayIcon.Trigger else None
        )
        self._tray.show()

    # -- authentification -----------------------------------------------------

    def _on_auth_pending(self, url: str) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(url))
        self._panel.notify("Autorisez LiveChat dans votre navigateur, puis revenez ici.")

    def _on_authenticated(self, me: dict) -> None:
        self._panel.set_identity(me)
        self._panel.set_connected(True)
        self._api.start()
        self._overlay.refresh()

        if me.get("user", {}).get("is_admin"):
            self._refresh_admin()
            self._admin_timer.start(ADMIN_REFRESH_MS)
        else:
            self._admin_timer.stop()

    def _on_logout(self) -> None:
        self._admin_timer.stop()
        self._api.logout()
        self._overlay.clear()
        self._panel.set_identity(None)
        self._panel.set_connected(False)

    # -- messages du serveur --------------------------------------------------

    def _on_command(self, payload: dict) -> None:
        kind = payload.get("type")
        if kind == "clear":
            self._overlay.clear()
        elif kind == "mute":
            self._settings.set("muted", bool(payload.get("muted", True)))
            self._overlay.apply_volume()
        elif kind == "settings":
            # Des valeurs par défaut, pas des ordres : un réglage local reste prioritaire.
            self._settings.apply_server_defaults(payload.get("defaults", {}))
            self._overlay.refresh()
        elif kind == "disconnected":
            self._panel.notify(payload.get("reason", "Déconnecté."), error=True)

    # -- envoi ----------------------------------------------------------------

    def _on_upload(self, path: Path, caption: str) -> None:
        try:
            total = path.stat().st_size
        except OSError as exc:
            self._panel.notify(f"Fichier illisible : {exc}", error=True)
            return
        self._panel.upload_started(total)
        self._api.upload(path, caption)

    # -- administration -------------------------------------------------------

    def _on_admin_action(self, action: str, payload) -> None:
        if action == "settings":
            self._api.admin_patch("settings", "patched", payload)
        elif action in ("clear", "mute", "unmute"):
            self._api.admin_post(action, action)

    def _refresh_admin(self) -> None:
        if not self._panel.isVisible():
            return
        self._api.admin_get("settings", "settings")
        self._api.admin_get("clients", "clients")

    def _on_admin_data(self, name: str, payload) -> None:
        if name == "settings" and isinstance(payload, dict):
            self._panel.show_admin_settings(payload)
        elif name == "clients" and isinstance(payload, list):
            self._panel.show_admin_clients(payload)
        elif name == "patched":
            self._panel.notify("Réglage appliqué.")
            self._api.admin_get("settings", "settings")

    # -- divers ---------------------------------------------------------------

    def _on_screens_changed(self, _=None) -> None:
        self._panel.refresh_screens()
        self._overlay.place_on_screen()

    def _quit(self) -> None:
        self._api.stop()
        self._tray.hide()
        self._app.quit()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("LiveChat")
    app.setOrganizationName("LiveChat")
    app.setQuitOnLastWindowClosed(False)  # le panneau se ferme, l'overlay reste

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("Pas de zone de notification : le panneau restera ouvert.")

    client = LiveChatClient(app)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        client._panel.open_near_cursor()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
