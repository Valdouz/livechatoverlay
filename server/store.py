"""Stockage des médias envoyés depuis le client.

Les médias venus de Discord ne passent pas par ici : ce sont des URL du CDN Discord,
relayées telles quelles. Seuls les fichiers téléversés occupent du disque, et ils sont
supprimés dès que tout le monde les a reçus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024        # 8 Mio par morceau
JANITOR_INTERVAL = 15               # secondes entre deux passages du concierge
UPLOAD_ABANDON_SECONDS = 6 * 3600   # un envoi jamais terminé finit par être balayé

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class StoreError(RuntimeError):
    """Refus explicite — le message est destiné à l'utilisateur qui envoie."""


def human(size: float) -> str:
    for unit in ("o", "Kio", "Mio", "Gio"):
        if size < 1024 or unit == "Gio":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} Gio"


@dataclass
class Upload:
    id: str
    owner_id: int
    filename: str
    declared_size: int
    content_type: str
    started_at: float
    path: Path

    @property
    def received(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


@dataclass
class Retention:
    """Suivi d'un média diffusé, en attente des accusés de réception."""

    media_id: str
    broadcast_at: float
    pending: set[str] = field(default_factory=set)
    all_acked_at: float | None = None


class MediaStore:
    def __init__(self, config, settings):
        self._config = config
        self._settings = settings
        self._uploads: dict[str, Upload] = {}
        self._retention: dict[str, Retention] = {}
        self._janitor: asyncio.Task | None = None

    # -- cycle de vie ---------------------------------------------------------

    async def start(self) -> None:
        # Purge au démarrage : rien de ce qui reste d'une exécution précédente
        # n'a de destinataire, plus personne ne l'attend.
        removed = self.purge_all()
        if removed:
            log.info("Purge au démarrage : %d fichier(s) supprimé(s).", removed)
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def close(self) -> None:
        if self._janitor:
            self._janitor.cancel()
            try:
                await self._janitor
            except asyncio.CancelledError:
                pass

    def purge_all(self) -> int:
        count = 0
        for directory in (self._config.media_dir, self._config.uploads_dir):
            for path in directory.glob("*"):
                if path.is_file():
                    path.unlink(missing_ok=True)
                    count += 1
        self._uploads.clear()
        self._retention.clear()
        return count

    # -- occupation disque ----------------------------------------------------

    def usage_bytes(self) -> int:
        total = 0
        for directory in (self._config.media_dir, self._config.uploads_dir):
            for path in directory.glob("*"):
                if path.is_file():
                    total += path.stat().st_size
        return total

    # -- envoi ----------------------------------------------------------------

    def begin_upload(self, owner_id: int, filename: str, size: int, content_type: str) -> Upload:
        max_bytes = self._settings["max_file_bytes"]
        if size <= 0:
            raise StoreError("Taille de fichier invalide.")
        if size > max_bytes:
            raise StoreError(
                f"Fichier trop volumineux : {human(size)}, maximum {human(max_bytes)}."
            )

        quota = self._settings["disk_quota_bytes"]
        used = self.usage_bytes()
        if used + size > quota:
            raise StoreError(
                f"Espace insuffisant sur le serveur : {human(used)} occupés sur "
                f"{human(quota)}. Réessayez dans quelques minutes, les médias sont "
                f"supprimés peu après leur réception."
            )

        upload_id = secrets.token_urlsafe(16)
        upload = Upload(
            id=upload_id,
            owner_id=owner_id,
            filename=_SAFE_NAME.sub("_", filename)[:120] or "media",
            declared_size=size,
            content_type=content_type or "application/octet-stream",
            started_at=time.time(),
            path=self._config.uploads_dir / f"{upload_id}.part",
        )
        upload.path.touch()
        self._uploads[upload_id] = upload
        log.info("Envoi ouvert : %s (%s) par %s", upload.filename, human(size), owner_id)
        return upload

    def get_upload(self, upload_id: str, owner_id: int) -> Upload:
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise StoreError("Envoi inconnu ou déjà terminé.")
        if upload.owner_id != owner_id:
            raise StoreError("Cet envoi ne vous appartient pas.")
        return upload

    async def write_chunk(self, upload: Upload, offset: int, reader) -> int:
        """Écrit un morceau à `offset`, renvoie la nouvelle position.

        Un morceau déjà reçu est réécrit sans erreur : c'est ce qui rend l'envoi
        reprenable après une coupure.
        """
        received = upload.received
        if offset > received:
            raise StoreError(
                f"Morceau hors séquence : reprise attendue à l'octet {received}."
            )

        loop = asyncio.get_running_loop()
        written = offset
        with upload.path.open("r+b") as handle:
            handle.seek(offset)
            async for chunk in reader.iter_chunked(256 * 1024):
                if written + len(chunk) > upload.declared_size:
                    raise StoreError("Envoi plus volumineux que la taille annoncée.")
                await loop.run_in_executor(None, handle.write, chunk)
                written += len(chunk)
        return max(written, received)

    def complete_upload(self, upload: Upload) -> dict:
        received = upload.received
        if received != upload.declared_size:
            raise StoreError(
                f"Envoi incomplet : {human(received)} reçus sur "
                f"{human(upload.declared_size)} annoncés."
            )

        media_id = upload.id
        final = self._config.media_dir / f"{media_id}.bin"
        upload.path.replace(final)

        guessed, _ = mimetypes.guess_type(upload.filename)
        content_type = upload.content_type
        if content_type == "application/octet-stream" and guessed:
            content_type = guessed

        meta = {
            "id": media_id,
            "filename": upload.filename,
            "content_type": content_type,
            "size": received,
            "owner_id": upload.owner_id,
        }
        (self._config.media_dir / f"{media_id}.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
        self._uploads.pop(upload.id, None)
        log.info("Envoi terminé : %s (%s)", upload.filename, human(received))
        return meta

    def abort_upload(self, upload: Upload) -> None:
        upload.path.unlink(missing_ok=True)
        self._uploads.pop(upload.id, None)

    # -- lecture --------------------------------------------------------------

    def resolve(self, media_id: str) -> tuple[Path, dict] | None:
        if not media_id or "/" in media_id or "\\" in media_id or ".." in media_id:
            return None
        path = self._config.media_dir / f"{media_id}.bin"
        meta_path = self._config.media_dir / f"{media_id}.json"
        if not path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return path, meta

    # -- rétention ------------------------------------------------------------

    def track(self, media_id: str, expected: set[str]) -> None:
        """Démarre le suivi d'un média diffusé.

        `expected` est l'ensemble des participants connectés au moment de la diffusion.
        S'il est vide — personne en ligne — le compte à rebours démarre immédiatement,
        sans quoi le fichier resterait sur le disque indéfiniment.
        """
        now = time.time()
        entry = Retention(media_id=media_id, broadcast_at=now, pending=set(expected))
        if not entry.pending:
            entry.all_acked_at = now
        self._retention[media_id] = entry

    def ack(self, media_id: str, client_id: str) -> None:
        entry = self._retention.get(media_id)
        if entry is None:
            return
        entry.pending.discard(client_id)
        if not entry.pending and entry.all_acked_at is None:
            entry.all_acked_at = time.time()
            log.info("Média %s reçu par tous, suppression programmée.", media_id)

    def forget_client(self, client_id: str) -> None:
        """Un participant déconnecté ne renverra plus d'accusé — ne pas l'attendre."""
        for media_id in list(self._retention):
            self.ack(media_id, client_id)

    def delete(self, media_id: str) -> None:
        (self._config.media_dir / f"{media_id}.bin").unlink(missing_ok=True)
        (self._config.media_dir / f"{media_id}.json").unlink(missing_ok=True)
        self._retention.pop(media_id, None)

    def tracked(self) -> list[dict]:
        now = time.time()
        return [
            {
                "media_id": entry.media_id,
                "age_seconds": round(now - entry.broadcast_at),
                "pending": len(entry.pending),
            }
            for entry in self._retention.values()
        ]

    async def _janitor_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(JANITOR_INTERVAL)
                self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Le concierge a échoué, il repassera.")

    def _sweep(self) -> None:
        now = time.time()
        grace = self._settings["retention_after_ack_seconds"]
        hard_cap = self._settings["retention_hard_cap_seconds"]

        for media_id, entry in list(self._retention.items()):
            # Plafond absolu : sans lui, un participant qui éteint son PC en pleine
            # réception laisserait le fichier sur le disque pour toujours.
            if now - entry.broadcast_at > hard_cap:
                log.info("Média %s supprimé (plafond de rétention atteint).", media_id)
                self.delete(media_id)
                continue
            if entry.all_acked_at is not None and now - entry.all_acked_at > grace:
                log.info("Média %s supprimé (reçu par tous).", media_id)
                self.delete(media_id)

        for upload in list(self._uploads.values()):
            if now - upload.started_at > UPLOAD_ABANDON_SECONDS:
                log.info("Envoi %s abandonné, nettoyé.", upload.filename)
                self.abort_upload(upload)
