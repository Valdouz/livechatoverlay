"""Le dialogue avec le serveur : authentification, WebSocket, envoi de fichiers, admin.

Tout passe par le réseau de Qt et reste donc dans la boucle d'évènements de
l'interface — pas de threads, pas d'asyncio à marier avec Qt.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QUrl, QTimer, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

log = logging.getLogger(__name__)

CHUNK_BYTES = 8 * 1024 * 1024
AUTH_POLL_MS = 2000
AUTH_TIMEOUT_MS = 5 * 60 * 1000

#: Reconnexion avec attente croissante : marteler un serveur qui redémarre
#: ne le fait pas revenir plus vite.
RECONNECT_STEPS_MS = [1000, 2000, 4000, 8000, 15000, 30000]


class Api(QObject):
    authenticated = Signal(dict)          # /me
    auth_failed = Signal(str)
    auth_pending = Signal(str)            # url d'autorisation à ouvrir

    connected = Signal()
    disconnected = Signal()
    media_received = Signal(dict)
    command_received = Signal(dict)

    upload_progress = Signal(int, int)    # octets envoyés, total
    upload_finished = Signal(dict)
    upload_failed = Signal(str)

    participants = Signal(list)           # qui est en ligne
    admin_data = Signal(str, object)      # nom de la requête, contenu
    admin_error = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._nam = QNetworkAccessManager(self)
        self._ws = QWebSocket()
        self._ws.textMessageReceived.connect(self._on_ws_text)
        self._ws.connected.connect(self._on_ws_connected)
        self._ws.disconnected.connect(self._on_ws_closed)
        self._ws.errorOccurred.connect(lambda _: self._on_ws_closed())

        self._reconnect = QTimer(self)
        self._reconnect.setSingleShot(True)
        self._reconnect.timeout.connect(self._open_ws)
        self._attempt = 0
        self._wanted = False

        self._auth_state = ""
        self._auth_timer = QTimer(self)
        self._auth_timer.timeout.connect(self._poll_auth)
        self._auth_elapsed = 0

        self._upload: dict | None = None

    # -- adresses -------------------------------------------------------------

    @property
    def base(self) -> str:
        return (self._settings["server_url"] or "").rstrip("/")

    @property
    def token(self) -> str:
        return self._settings["token"] or ""

    def _url(self, path: str) -> QUrl:
        return QUrl(f"{self.base}{path}")

    def _request(self, path: str, json_body: bool = False) -> QNetworkRequest:
        request = QNetworkRequest(self._url(path))
        if self.token:
            request.setRawHeader(b"Authorization", f"Bearer {self.token}".encode())
        if json_body:
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        return request

    # -- authentification -----------------------------------------------------

    def login(self) -> None:
        """Ouvre une session : le serveur fabrique l'URL Discord, on l'ouvre dans le
        navigateur, puis on interroge le serveur jusqu'à obtenir le jeton.
        """
        if not self.base:
            self.auth_failed.emit("Renseignez d'abord l'adresse du serveur.")
            return

        reply = self._nam.get(self._request("/auth/start"))

        def done():
            payload = _read_json(reply)
            reply.deleteLater()
            if payload is None or "authorize_url" not in payload:
                self.auth_failed.emit(
                    "Serveur injoignable. Vérifiez l'adresse, elle doit ressembler à "
                    "https://livechat.exemple.fr"
                )
                return
            self._auth_state = payload["state"]
            self._auth_elapsed = 0
            self._auth_timer.start(AUTH_POLL_MS)
            self.auth_pending.emit(payload["authorize_url"])

        reply.finished.connect(done)

    def _poll_auth(self) -> None:
        self._auth_elapsed += AUTH_POLL_MS
        if self._auth_elapsed > AUTH_TIMEOUT_MS:
            self._auth_timer.stop()
            self.auth_failed.emit("Connexion abandonnée : aucune réponse en cinq minutes.")
            return

        reply = self._nam.get(self._request(f"/auth/poll?state={self._auth_state}"))

        def done():
            status = _status(reply)
            payload = _read_json(reply)
            reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            reply.deleteLater()

            if status == 401:
                self._auth_timer.stop()
                self.auth_failed.emit(str(reason or "Connexion refusée."))
                return
            if not payload or payload.get("status") == "pending":
                return

            self._auth_timer.stop()
            token = payload.get("token", "")
            if not token:
                self.auth_failed.emit("Réponse inattendue du serveur.")
                return
            self._settings.set("token", token)
            self.fetch_me()

        reply.finished.connect(done)

    def fetch_me(self) -> None:
        if not self.token:
            self.auth_failed.emit("Vous n'êtes pas connecté.")
            return
        reply = self._nam.get(self._request("/me"))

        def done():
            status = _status(reply)
            payload = _read_json(reply)
            reply.deleteLater()
            if status in (401, 403) or payload is None:
                self._settings.set("token", "")
                self.auth_failed.emit("Session expirée, reconnectez-vous.")
                return
            self._settings.apply_server_defaults(payload.get("defaults", {}))
            self.authenticated.emit(payload)

        reply.finished.connect(done)

    def fetch_participants(self) -> None:
        """Qui est en ligne, pour proposer une cible d'envoi."""
        if not self.token:
            return
        reply = self._nam.get(self._request("/participants"))

        def done():
            payload = _read_json(reply)
            reply.deleteLater()
            if isinstance(payload, list):
                self.participants.emit(payload)

        reply.finished.connect(done)

    def logout(self) -> None:
        if self.token:
            reply = self._nam.post(self._request("/logout", json_body=True), b"{}")
            reply.finished.connect(reply.deleteLater)
        self._settings.set("token", "")
        self.stop()

    # -- WebSocket ------------------------------------------------------------

    def start(self) -> None:
        self._wanted = True
        self._attempt = 0
        self._open_ws()

    def stop(self) -> None:
        self._wanted = False
        self._reconnect.stop()
        self._ws.close()

    def _open_ws(self) -> None:
        if not self._wanted or not self.base or not self.token:
            return
        url = self.base.replace("https://", "wss://").replace("http://", "ws://")
        # Le jeton passe en paramètre : QWebSocket ne permet pas d'en-tête
        # personnalisé sur la poignée de main.
        self._ws.open(QUrl(f"{url}/ws?token={self.token}"))

    def _on_ws_connected(self) -> None:
        self._attempt = 0
        self.connected.emit()

    def _on_ws_closed(self) -> None:
        self.disconnected.emit()
        if not self._wanted or self._reconnect.isActive():
            return
        # Un seul point de reprogrammation : `disconnected` et `errorOccurred`
        # arrivent souvent ensemble, et la v1 ouvrait alors deux connexions.
        delay = RECONNECT_STEPS_MS[min(self._attempt, len(RECONNECT_STEPS_MS) - 1)]
        self._attempt += 1
        self._reconnect.start(delay)

    def _on_ws_text(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if payload.get("type") == "media":
            self.media_received.emit(payload)
        else:
            self.command_received.emit(payload)

    def acknowledge(self, media_id: str) -> None:
        """Confirme au serveur que le média a été reçu et affiché.

        C'est ce signal qui déclenche son effacement côté serveur.
        """
        if media_id and self._ws.isValid():
            self._ws.sendTextMessage(json.dumps({"type": "ack", "media_id": media_id}))

    # -- envoi de fichier -----------------------------------------------------

    def upload(self, path: Path, caption: str = "", target: str = "") -> None:
        if self._upload is not None:
            self.upload_failed.emit("Un envoi est déjà en cours.")
            return
        try:
            size = path.stat().st_size
        except OSError as exc:
            self.upload_failed.emit(f"Fichier illisible : {exc}")
            return

        body = json.dumps(
            {
                "filename": path.name,
                "size": size,
                "content_type": _guess_type(path),
            }
        ).encode()
        reply = self._nam.post(self._request("/upload/init", json_body=True), body)

        def done():
            payload = _read_json(reply)
            reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            reply.deleteLater()
            if payload is None or "id" not in payload:
                self.upload_failed.emit(str(reason or "Le serveur a refusé l'envoi."))
                return
            self._upload = {
                "id": payload["id"],
                "path": path,
                "size": size,
                "offset": 0,
                "caption": caption,
                "target": target,
                "handle": path.open("rb"),
            }
            self.upload_progress.emit(0, size)
            self._send_next_chunk()

        reply.finished.connect(done)

    def _send_next_chunk(self) -> None:
        job = self._upload
        if job is None:
            return
        chunk = job["handle"].read(CHUNK_BYTES)
        if not chunk:
            self._finish_upload()
            return

        offset = job["offset"]
        request = self._request(f"/upload/{job['id']}?offset={offset}")
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/octet-stream")
        reply = self._nam.put(request, QByteArray(chunk))

        def done():
            payload = _read_json(reply)
            reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            reply.deleteLater()
            if self._upload is None:
                return
            if payload is None or "offset" not in payload:
                self._abort_upload(str(reason or "Envoi interrompu."))
                return
            self._upload["offset"] = payload["offset"]
            self.upload_progress.emit(payload["offset"], self._upload["size"])
            self._send_next_chunk()

        reply.finished.connect(done)

    def _finish_upload(self) -> None:
        job = self._upload
        if job is None:
            return
        body = json.dumps({"caption": job["caption"],
                           "target_user_id": job["target"] or "all"}).encode()
        reply = self._nam.post(
            self._request(f"/upload/{job['id']}/complete", json_body=True), body
        )

        def done():
            payload = _read_json(reply)
            reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            reply.deleteLater()
            self._close_upload()
            if payload is None or not payload.get("ok"):
                self.upload_failed.emit(str(reason or "Finalisation impossible."))
                return
            self.upload_finished.emit(payload)

        reply.finished.connect(done)

    def cancel_upload(self) -> None:
        if self._upload is not None:
            self._abort_upload("Envoi annulé.")

    def _abort_upload(self, message: str) -> None:
        self._close_upload()
        self.upload_failed.emit(message)

    def _close_upload(self) -> None:
        if self._upload is not None:
            try:
                self._upload["handle"].close()
            except Exception:
                pass
            self._upload = None

    @property
    def uploading(self) -> bool:
        return self._upload is not None

    # -- administration -------------------------------------------------------

    def admin_get(self, path: str, name: str) -> None:
        reply = self._nam.get(self._request(f"/admin/{path}"))
        self._admin_reply(reply, name)

    def admin_post(self, path: str, name: str, body: dict | None = None) -> None:
        payload = json.dumps(body or {}).encode()
        reply = self._nam.post(self._request(f"/admin/{path}", json_body=True), payload)
        self._admin_reply(reply, name)

    def admin_patch(self, path: str, name: str, body: dict) -> None:
        request = self._request(f"/admin/{path}", json_body=True)
        reply = self._nam.sendCustomRequest(request, b"PATCH", json.dumps(body).encode())
        self._admin_reply(reply, name)

    def _admin_reply(self, reply: QNetworkReply, name: str) -> None:
        def done():
            status = _status(reply)
            payload = _read_json(reply)
            reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            reply.deleteLater()
            if status and status >= 400:
                self.admin_error.emit(str(reason or f"Erreur {status}"))
                return
            self.admin_data.emit(name, payload)

        reply.finished.connect(done)


# -- utilitaires -------------------------------------------------------------


def _status(reply: QNetworkReply) -> int | None:
    return reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)


def _read_json(reply: QNetworkReply):
    try:
        raw = bytes(reply.readAll())
        return json.loads(raw) if raw else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _guess_type(path: Path) -> str:
    import mimetypes

    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"
