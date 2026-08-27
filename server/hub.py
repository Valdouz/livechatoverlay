"""Les participants connectés, et la diffusion des médias vers leurs overlays."""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from aiohttp import web

from .identity import Identity

log = logging.getLogger(__name__)


@dataclass
class Client:
    id: str
    ws: web.WebSocketResponse
    identity: Identity
    connected_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        # Ni IP ni nom d'hôte : la v1 les exposait sur un endpoint ouvert.
        return {
            "client_id": self.id,
            "connected_since": round(time.time() - self.connected_at),
            **self.identity.public(),
        }


class Hub:
    def __init__(self, store):
        self._store = store
        self._clients: dict[str, Client] = {}

    # -- connexions -----------------------------------------------------------

    def add(self, ws: web.WebSocketResponse, identity: Identity) -> Client:
        client = Client(id=secrets.token_urlsafe(12), ws=ws, identity=identity)
        self._clients[client.id] = client
        log.info("Connecté : %s (%d au total)", identity.display_name, len(self._clients))
        return client

    def remove(self, client: Client) -> None:
        self._clients.pop(client.id, None)
        # Un participant parti ne renverra jamais son accusé : ne pas l'attendre,
        # sinon le média resterait sur le disque jusqu'au plafond de rétention.
        self._store.forget_client(client.id)
        log.info("Déconnecté : %s (%d restant)", client.identity.display_name, len(self._clients))

    def clients(self) -> list[Client]:
        return list(self._clients.values())

    def client_ids(self) -> set[str]:
        return set(self._clients)

    def by_user(self, user_id: int) -> list[Client]:
        return [c for c in self._clients.values() if c.identity.user_id == user_id]

    # -- diffusion ------------------------------------------------------------

    async def broadcast(self, payload: dict) -> int:
        message = json.dumps(payload)
        delivered = 0
        for client in list(self._clients.values()):
            try:
                await client.ws.send_str(message)
                delivered += 1
            except Exception:
                # La boucle de lecture du client fera le ménage de son côté.
                log.debug("Envoi impossible vers %s", client.identity.display_name)
        return delivered

    async def send_to(self, client: Client, payload: dict) -> None:
        try:
            await client.ws.send_str(json.dumps(payload))
        except Exception:
            log.debug("Envoi impossible vers %s", client.identity.display_name)

    async def disconnect_user(self, user_id: int, reason: str) -> int:
        """Coupe toutes les connexions d'un compte — utilisé au bannissement."""
        victims = self.by_user(user_id)
        for client in victims:
            await self.send_to(client, {"type": "disconnected", "reason": reason})
            try:
                await client.ws.close(code=4003, message=reason.encode("utf-8"))
            except Exception:
                pass
        return len(victims)
