"""Authentification Discord (OAuth2).

Le `client_secret` ne quitte jamais le serveur : c'est lui qui échange le code, pas le
client. Portée demandée : `identify` seule. Le bot étant déjà membre du serveur Discord,
il résout lui-même l'appartenance et les rôles — inutile de demander `guilds` au visiteur.

    client      GET  /auth/start          -> url d'autorisation + state
    navigateur  ---> Discord ---> GET /auth/callback
    client      GET  /auth/poll?state=..  -> jeton de session
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp

from .identity import Identity, Sessions

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
USER_URL = "https://discord.com/api/users/@me"

PENDING_TTL = 10 * 60  # un état d'authentification non consommé expire


class AuthError(RuntimeError):
    """Échec d'authentification, avec un message présentable à l'utilisateur."""


@dataclass
class Pending:
    state: str
    created_at: float
    token: str | None = None
    error: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > PENDING_TTL


class DiscordAuth:
    def __init__(self, config, sessions: Sessions, member_lookup):
        """`member_lookup` : coroutine (user_id) -> discord.Member | None."""
        self._config = config
        self._sessions = sessions
        self._member_lookup = member_lookup
        self._pending: dict[str, Pending] = {}

    # -- démarrage ------------------------------------------------------------

    def start(self) -> dict:
        self._forget_stale()
        state = secrets.token_urlsafe(24)
        self._pending[state] = Pending(state=state, created_at=time.time())
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "scope": "identify",
                "state": state,
                "prompt": "none",
            }
        )
        return {"state": state, "authorize_url": f"{AUTHORIZE_URL}?{query}"}

    # -- retour de Discord ----------------------------------------------------

    async def complete(self, code: str, state: str) -> Identity:
        pending = self._pending.get(state)
        if pending is None or pending.expired:
            raise AuthError("Demande de connexion inconnue ou expirée. Relancez la connexion.")

        try:
            identity = await self._exchange(code)
        except AuthError as exc:
            pending.error = str(exc)
            raise

        session = self._sessions.create(identity)
        pending.token = session.token
        log.info("Authentifié : %s (%s)", identity.display_name, identity.user_id)
        return identity

    async def _exchange(self, code: str) -> Identity:
        data = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
        }
        async with aiohttp.ClientSession() as http:
            async with http.post(TOKEN_URL, data=data) as response:
                if response.status != 200:
                    body = await response.text()
                    log.warning("Échange OAuth2 refusé (%s) : %s", response.status, body[:300])
                    raise AuthError(
                        "Discord a refusé la connexion. Vérifiez que l'URL de redirection "
                        "déclarée dans le portail Discord correspond exactement à PUBLIC_URL."
                    )
                token_payload = await response.json()

            access_token = token_payload.get("access_token")
            if not access_token:
                raise AuthError("Réponse inattendue de Discord.")

            headers = {"Authorization": f"Bearer {access_token}"}
            async with http.get(USER_URL, headers=headers) as response:
                if response.status != 200:
                    raise AuthError("Impossible de lire votre profil Discord.")
                user = await response.json()

        user_id = int(user["id"])
        member = await self._member_lookup(user_id)
        if member is None:
            raise AuthError(
                "Vous n'êtes pas membre du serveur Discord associé à cette instance."
            )

        return Identity(
            user_id=user_id,
            username=user.get("username", ""),
            display_name=getattr(member, "display_name", None) or user.get("username", ""),
            avatar_url=str(getattr(member, "display_avatar", "") or ""),
            role_ids=[role.id for role in getattr(member, "roles", [])],
        )

    # -- récupération par le client -------------------------------------------

    def poll(self, state: str) -> dict:
        pending = self._pending.get(state)
        if pending is None or pending.expired:
            self._pending.pop(state, None)
            raise AuthError("Demande de connexion inconnue ou expirée.")
        if pending.error:
            self._pending.pop(state, None)
            raise AuthError(pending.error)
        if pending.token is None:
            return {"status": "pending"}

        # Le jeton n'est délivré qu'une fois.
        self._pending.pop(state, None)
        session = self._sessions.get(pending.token)
        if session is None:
            raise AuthError("Session expirée avant d'avoir pu être récupérée.")
        return {"status": "ok", "token": session.token}

    def _forget_stale(self) -> None:
        for state, pending in list(self._pending.items()):
            if pending.expired:
                del self._pending[state]
