"""Mise à jour depuis les releases GitHub.

Trois étapes séparées, parce qu'elles peuvent échouer indépendamment : vérifier
qu'une version existe, la télécharger, puis l'installer.

L'installation en place n'est possible que sur Windows, et seulement si le
dossier est accessible en écriture. Partout ailleurs on télécharge le fichier et
on ouvre son dossier — mieux vaut une manipulation manuelle assumée qu'une
installation qui échoue à moitié et laisse l'application inutilisable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import platform

log = logging.getLogger(__name__)

REPO = "Valdouz/livechatoverlay"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

#: Le fichier à prendre dans la release, selon le système.
DEFAULT_ASSET = "LiveChat-linux"


def asset_name() -> str:
    """Le nom du fichier de release qui correspond à cette machine.

    Sur Mac il y a deux binaires : PySide6 n'est pas universal2, un exécutable
    Apple Silicon refuse simplement de démarrer sur un Mac Intel.
    """
    if sys.platform == "win32":
        return "LiveChat.exe"
    if sys.platform == "darwin":
        import platform as _platform

        machine = _platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "LiveChat-macos-apple-silicon.zip"
        return "LiveChat-macos-intel.zip"
    return DEFAULT_ASSET


def parse_version(text: str) -> tuple:
    """« v2.1.0 » → (2, 1, 0). Un suffixe comme -dev classe la version en dessous.

    Renvoie un tuple comparable ; les versions illisibles passent pour très
    anciennes, ce qui déclenche une proposition de mise à jour plutôt que de
    laisser quelqu'un sur une version cassée sans le savoir.
    """
    match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)", (text or "").strip())
    if not match:
        return (0, 0, 0, 0)
    major, minor, patch, rest = match.groups()
    # Sans suffixe la version est finale : elle doit primer sur ses pré-versions,
    # donc porter la clé la plus haute. 2.1.0 > 2.1.0-rc1 > 2.0.0.
    final = 0 if rest.strip(" .") else 1
    return (int(major), int(minor or 0), int(patch or 0), final)


class Updater(QObject):
    """Vérifie, télécharge, installe. Chaque étape prévient de son résultat."""

    up_to_date = Signal()
    available = Signal(str)               # version trouvée
    check_failed = Signal(str)
    download_progress = Signal(int, int)  # octets reçus, total
    ready = Signal(Path)                  # fichier téléchargé
    failed = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self._current = current
        self._nam = QNetworkAccessManager(self)
        self._latest = ""
        self._asset_url = ""
        self._reply: QNetworkReply | None = None
        self._file = None
        self._destination: Path | None = None

    # -- vérification ---------------------------------------------------------

    @property
    def latest(self) -> str:
        return self._latest

    def check(self) -> None:
        request = QNetworkRequest(QUrl(LATEST_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"LiveChat/{self._current}".encode())
        reply = self._nam.get(request)

        def done():
            raw = bytes(reply.readAll())
            error = reply.error() != QNetworkReply.NetworkError.NoError
            reply.deleteLater()
            if error or not raw:
                self.check_failed.emit("Impossible de joindre GitHub.")
                return
            try:
                release = json.loads(raw)
            except json.JSONDecodeError:
                self.check_failed.emit("Réponse inattendue de GitHub.")
                return

            tag = str(release.get("tag_name", ""))
            if not tag:
                self.check_failed.emit("Aucune version publiée.")
                return

            wanted = asset_name()
            for asset in release.get("assets", []):
                if asset.get("name") == wanted:
                    self._asset_url = asset.get("browser_download_url", "")
                    break

            self._latest = tag.lstrip("v")
            if parse_version(tag) > parse_version(self._current):
                log.info("Version %s disponible (vous avez %s).", self._latest, self._current)
                self.available.emit(self._latest)
            else:
                self.up_to_date.emit()

        reply.finished.connect(done)

    # -- téléchargement -------------------------------------------------------

    def download(self) -> None:
        if not self._asset_url:
            self.failed.emit(
                f"Aucun fichier pour votre système ({asset_name()}) dans cette version."
            )
            return
        if self._reply is not None:
            return

        directory = Path(
            QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            or tempfile.gettempdir()
        )
        directory.mkdir(parents=True, exist_ok=True)
        self._destination = directory / f"LiveChat-{self._latest}-{asset_name()}"

        try:
            self._file = self._destination.open("wb")
        except OSError as exc:
            self.failed.emit(f"Écriture impossible dans {directory} : {exc}")
            return

        request = QNetworkRequest(QUrl(self._asset_url))
        request.setRawHeader(b"User-Agent", f"LiveChat/{self._current}".encode())
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._reply = self._nam.get(request)
        self._reply.downloadProgress.connect(self.download_progress.emit)
        self._reply.readyRead.connect(self._drain)
        self._reply.finished.connect(self._finish)

    def _drain(self) -> None:
        # Écrire au fil de l'eau : garder 60 Mio en mémoire n'aurait aucun intérêt.
        if self._reply is not None and self._file is not None:
            self._file.write(bytes(self._reply.readAll()))

    def _finish(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        self._drain()
        error = reply.error() != QNetworkReply.NetworkError.NoError
        reason = reply.errorString()
        reply.deleteLater()

        if self._file is not None:
            self._file.close()
            self._file = None

        if error:
            if self._destination is not None:
                self._destination.unlink(missing_ok=True)
            self.failed.emit(f"Téléchargement interrompu : {reason}")
            return

        log.info("Mise à jour téléchargée : %s", self._destination)
        self.ready.emit(self._destination)

    def cancel(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    # -- installation ---------------------------------------------------------

    @staticmethod
    def why_manual() -> str:
        """Ce qui empêche l'installation automatique, chaîne vide si rien.

        Renvoyer la raison plutôt qu'un simple booléen : quand la mise à jour ne
        s'installe pas toute seule, savoir pourquoi évite de chercher longtemps.
        """
        if not getattr(sys, "frozen", False):
            return "lancé depuis les sources"
        if not platform.IS_WINDOWS:
            return "installation automatique réservée à Windows"

        directory = Path(sys.executable).parent
        # os.access ne regarde que l'attribut lecture seule sous Windows, jamais
        # les ACL : le seul test fiable est d'essayer d'écrire pour de bon.
        probe = directory / ".livechat-write-test"
        try:
            probe.touch()
            probe.unlink()
        except OSError as exc:
            return f"dossier non modifiable ({exc.strerror or exc})"
        return ""

    @staticmethod
    def can_replace_itself() -> bool:
        return Updater.why_manual() == ""

    def install(self, downloaded: Path) -> bool:
        """Remplace l'exécutable et relance. Renvoie False s'il faut faire à la main.

        Windows verrouille un exécutable en cours d'exécution : impossible de
        l'écraser depuis soi-même. On confie donc l'échange à un script qui attend
        la fin du processus, avec une sauvegarde restaurée si l'échange échoue.
        """
        reason = self.why_manual()
        if reason:
            log.info("Installation manuelle nécessaire : %s.", reason)
            return False

        # Un fichier tronqué remplacerait l'application par une coquille vide.
        try:
            if downloaded.stat().st_size < 4 * 1024 * 1024:
                log.warning("Fichier téléchargé trop petit, échange annulé.")
                return False
        except OSError:
            return False

        target = Path(sys.executable)
        backup = target.with_suffix(".old.exe")
        script = target.parent / "livechat-update.cmd"
        script.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            f'set "TARGET={target}"\r\n'
            f'set "SOURCE={downloaded}"\r\n'
            f'set "BACKUP={backup}"\r\n'
            "rem Attendre que l'application ait vraiment quitté et libéré son fichier.\r\n"
            "set /a TRIES=0\r\n"
            ":wait\r\n"
            'tasklist /FI "PID eq %1" 2>nul | find "%1" >nul || goto swap\r\n'
            "set /a TRIES+=1\r\n"
            "if %TRIES% GEQ 30 goto swap\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            "goto wait\r\n"
            ":swap\r\n"
            'if exist "%BACKUP%" del /f /q "%BACKUP%"\r\n'
            'move /y "%TARGET%" "%BACKUP%" >nul 2>&1\r\n'
            'move /y "%SOURCE%" "%TARGET%" >nul 2>&1\r\n'
            "if errorlevel 1 (\r\n"
            "  rem Échange raté : on remet la version précédente en place.\r\n"
            '  move /y "%BACKUP%" "%TARGET%" >nul 2>&1\r\n'
            ") else (\r\n"
            '  del /f /q "%BACKUP%" >nul 2>&1\r\n'
            ")\r\n"
            'start "" "%TARGET%"\r\n'
            'del /f /q "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )

        try:
            subprocess.Popen(
                ["cmd", "/c", str(script), str(os.getpid())],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                # Compilée en mode fenêtré, l'application n'a aucun descripteur
                # standard : sans ces trois-là, Popen échoue en essayant de les
                # transmettre, et la mise à jour retombait silencieusement en manuel.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            log.warning("Lancement du script de mise à jour impossible : %s", exc)
            script.unlink(missing_ok=True)
            return False

        log.info("Script de mise à jour lancé, échange après la fermeture.")
        return True


def reveal(path: Path) -> None:
    """Ouvre le dossier du fichier téléchargé, en le sélectionnant si possible."""
    try:
        if platform.IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif platform.IS_MAC:
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError as exc:
        log.warning("Ouverture du dossier impossible : %s", exc)
