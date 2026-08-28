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
from PySide6.QtGui import (QAction, QColor, QGuiApplication, QIcon, QPainter,  # noqa: E402
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from . import fonts, theme  # noqa: E402
from .api import Api  # noqa: E402
from .overlay import Overlay  # noqa: E402
from .panel import Panel  # noqa: E402
from .settings import ClientSettings, normalise_server_url  # noqa: E402
from .updates import Updater, reveal  # noqa: E402
from . import __version__  # noqa: E402

log = logging.getLogger("livechat.client")

ADMIN_REFRESH_MS = 5000
PEOPLE_REFRESH_MS = 8000

#: Laisser l'interface s'installer avant d'aller interroger GitHub.
UPDATE_CHECK_DELAY_MS = 4000


def settings_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    return Path(base or Path.home() / ".config" / "LiveChat") / "settings.json"


SIDECAR_NAMES = ("server.txt", "livechat-server.txt")

HELP = """LiveChat — partage de médias en overlay

  LiveChat [--server URL] [--tray]

  --server URL   serveur à utiliser. Sans cette option : un fichier server.txt
                 posé à côté de l'exécutable, la variable LIVECHAT_SERVER, ou
                 l'adresse saisie au premier lancement.
  --tray         démarrer discrètement, sans ouvrir le panneau.

L'adresse de votre groupe est affichée sur la page d'accueil du serveur."""


def app_dir() -> Path:
    """Le dossier de l'exécutable, ou des sources en développement."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def preset_server() -> str:
    """Adresse du serveur imposée au lancement, s'il y en a une.

    Trois façons de la fournir, dans l'ordre de priorité :

    1. ``LiveChat --server https://exemple.fr`` — pour un raccourci ou un script ;
    2. un fichier ``server.txt`` posé à côté de l'exécutable — le host distribue
       alors deux fichiers et ses amis n'ont rien à saisir ;
    3. la variable d'environnement ``LIVECHAT_SERVER``.

    Sans rien de tout ça, le panneau demande l'adresse au premier lancement :
    elle est affichée en gros sur la page d'accueil du serveur.
    """
    for index, argument in enumerate(sys.argv):
        if argument == "--server" and index + 1 < len(sys.argv):
            return sys.argv[index + 1].strip()
        if argument.startswith("--server="):
            return argument.split("=", 1)[1].strip()

    for name in SIDECAR_NAMES:
        candidate = app_dir() / name
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
            except OSError as exc:
                log.warning("Lecture de %s impossible : %s", candidate, exc)

    return os.environ.get("LIVECHAT_SERVER", "").strip()


#: Même normalisation que celle du panneau : une seule règle, un seul endroit.
normalise = normalise_server_url


def make_icon() -> QIcon:
    """L'icône de l'application : le fichier embarqué, dessin de secours sinon.

    Le fichier porte le même anneau vert que le panneau et que le cercle d'avatar
    de l'overlay — c'est la seule marque visuelle du projet.
    """
    path = fonts.icon_path()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#16161f"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QPen(theme.RING_COLOR, 6))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pixmap)


class LiveChatClient:
    def __init__(self, app: QApplication, start_in_tray: bool = False):
        self._app = app
        self._settings = ClientSettings(settings_path())

        # Une adresse imposée au lancement l'emporte : elle vient du host, pas du
        # participant, et corrige une adresse enregistrée devenue caduque.
        imposed = normalise(preset_server())
        if imposed and imposed != self._settings["server_url"]:
            log.info("Serveur imposé au lancement : %s", imposed)
            self._settings.set("server_url", imposed)
            self._settings.set("token", "")  # l'ancienne session ne vaut plus rien

        self._api = Api(self._settings)
        self._overlay = Overlay(self._settings)
        self._panel = Panel(self._settings)

        self._updater = Updater(__version__)
        self._downloaded = None
        self._panel.set_version(__version__)

        self._wire()
        self._build_tray()

        # Le suivi des écrans branchés à chaud : la liste du panneau doit rester juste.
        QGuiApplication.instance().screenAdded.connect(self._on_screens_changed)
        QGuiApplication.instance().screenRemoved.connect(self._on_screens_changed)

        # Brancher un casque doit faire apparaître le périphérique dans la liste.
        from PySide6.QtMultimedia import QMediaDevices
        self._media_devices = QMediaDevices(self._app)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_devices_changed)

        self._admin_timer = QTimer()
        self._admin_timer.timeout.connect(self._refresh_admin)

        # La liste des destinataires doit suivre les allées et venues du groupe.
        self._people_timer = QTimer()
        self._people_timer.timeout.connect(self._refresh_people)

        if self._settings["server_url"] and self._settings["token"]:
            self._api.fetch_me()
        # Lancé à la main, on montre le panneau ; lancé avec la session, on se range
        # dans la zone de notification. Sans ça, rouvrir l'application avec une
        # session enregistrée ne produisait rien de visible.
        if not start_in_tray:
            self._panel.open_near_cursor()

        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self._updater.check)

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
        api.upload_finished.connect(self._on_upload_finished)
        api.upload_failed.connect(lambda message: panel.upload_ended(message, error=True))
        api.participants.connect(panel.show_participants)
        api.admin_data.connect(self._on_admin_data)
        api.admin_error.connect(lambda message: panel.notify(message, error=True))

        overlay.acknowledged.connect(api.acknowledge)
        overlay.media_failed.connect(lambda message: panel.notify(message, error=True))

        panel.login_requested.connect(api.login)
        panel.logout_requested.connect(self._on_logout)
        panel.settings_changed.connect(overlay.refresh)
        panel.upload_requested.connect(self._on_upload)
        panel.upload_cancelled.connect(api.cancel_upload)
        panel.admin_action.connect(self._on_admin_action)
        panel.update_requested.connect(self._updater.download)

        self._updater.available.connect(panel.show_update)
        self._updater.up_to_date.connect(panel.hide_update)
        self._updater.check_failed.connect(
            lambda reason: log.info("Vérification des mises à jour : %s", reason))
        self._updater.download_progress.connect(panel.update_progress)
        self._updater.ready.connect(self._on_update_ready)
        self._updater.failed.connect(
            lambda reason: panel.update_finished(reason, error=True))

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

        self._api.fetch_participants()
        self._people_timer.start(PEOPLE_REFRESH_MS)

        if me.get("user", {}).get("is_admin"):
            self._refresh_admin()
            self._admin_timer.start(ADMIN_REFRESH_MS)
        else:
            self._admin_timer.stop()

    def _on_logout(self) -> None:
        self._admin_timer.stop()
        self._people_timer.stop()
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

    def _on_upload(self, path: Path, caption: str, target: str, animation: str) -> None:
        try:
            total = path.stat().st_size
        except OSError as exc:
            self._panel.notify(f"Fichier illisible : {exc}", error=True)
            return
        self._panel.upload_started(total)
        self._api.upload(path, caption, target, animation)

    def _on_upload_finished(self, payload: dict) -> None:
        delivered = payload.get("delivered", 0)
        if payload.get("private"):
            if delivered:
                name = self._panel.target_name() or "cette personne"
                self._panel.upload_ended(f"Envoyé à {name}.")
            else:
                self._panel.upload_ended(
                    "Envoyé, mais cette personne n'était plus connectée.", error=True)
        elif delivered:
            self._panel.upload_ended(
                f"Envoyé sur {delivered} écran{'s' if delivered > 1 else ''}.")
        else:
            self._panel.upload_ended("Envoyé, mais personne n'était connecté.", error=True)

    # -- administration -------------------------------------------------------

    def _on_admin_action(self, action: str, payload) -> None:
        if action == "settings":
            self._api.admin_patch("settings", "patched", payload)
        elif action in ("clear", "mute", "unmute"):
            self._api.admin_post(action, action)

    def _refresh_people(self) -> None:
        if self._panel.isVisible():
            self._api.fetch_participants()

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

    # -- mise à jour -----------------------------------------------------------

    def _on_update_ready(self, path) -> None:
        """Le fichier est là. On l'installe si on peut, sinon on le montre.

        Remplacer un exécutable en cours d'exécution n'est possible que sur
        Windows et via un script tiers ; ailleurs on préfère une manipulation
        manuelle assumée à une installation qui échoue à moitié.
        """
        self._downloaded = path
        if self._updater.install(path):
            self._panel.update_finished("Redémarrage…")
            log.info("Mise à jour installée, relance en cours.")
            # Laisser le script démarrer et voir un processus encore vivant :
            # il attend notre fermeture, il ne doit pas la manquer.
            QTimer.singleShot(600, self._quit)
            return

        reason = self._updater.why_manual()
        reveal(path)
        detail = f" ({reason})" if reason else ""
        self._panel.update_finished(
            f"Téléchargé dans {path.parent.name}{detail}. "
            f"Fermez LiveChat et remplacez l'application par ce fichier."
        )

    # -- divers ---------------------------------------------------------------

    def _on_screens_changed(self, _=None) -> None:
        self._panel.refresh_screens()
        self._overlay.place_on_screen()

    def _on_audio_devices_changed(self) -> None:
        self._panel.refresh_audio_devices()
        self._overlay.apply_volume()

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
    app.setWindowIcon(make_icon())
    app.setQuitOnLastWindowClosed(False)  # le panneau se ferme, l'overlay reste

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("Pas de zone de notification : le panneau restera ouvert.")

    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP)
        return 0

    in_tray = "--tray" in sys.argv and QSystemTrayIcon.isSystemTrayAvailable()
    client = LiveChatClient(app, start_in_tray=in_tray)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
