"""Qui est qui : sessions authentifiées et niveaux d'autorisation.

L'autorisation est décidée ici, côté serveur, à partir de l'identité Discord.
Le client ne fait qu'afficher ou masquer de l'interface — il n'a jamais le dernier mot.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

SESSION_TTL = 30 * 24 * 3600  # 30 jours


@dataclass
class Identity:
    user_id: int
    username: str
    display_name: str
    avatar_url: str
    role_ids: list[int] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "id": str(self.user_id),
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
        }


@dataclass
class Session:
    token: str
    identity: Identity
    created_at: float

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > SESSION_TTL


class Sessions:
    """Jetons de session opaques, persistés pour survivre à un redémarrage."""

    def __init__(self, path: Path):
        self._path = path
        self._by_token: dict[str, Session] = {}
        self._load()

    def create(self, identity: Identity) -> Session:
        session = Session(secrets.token_urlsafe(32), identity, time.time())
        self._by_token[session.token] = session
        self._save()
        return session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        session = self._by_token.get(token)
        if session is None:
            return None
        if session.expired:
            self.revoke(token)
            return None
        return session

    def revoke(self, token: str) -> None:
        if self._by_token.pop(token, None) is not None:
            self._save()

    def revoke_user(self, user_id: int) -> int:
        """Coupe toutes les sessions d'un compte — utilisé au bannissement."""
        doomed = [t for t, s in self._by_token.items() if s.identity.user_id == user_id]
        for token in doomed:
            del self._by_token[token]
        if doomed:
            self._save()
        return len(doomed)

    # ── persistance ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Sessions illisibles (%s), tout le monde devra se reconnecter.", exc)
            return
        for raw in stored:
            try:
                session = Session(
                    token=raw["token"],
                    identity=Identity(**raw["identity"]),
                    created_at=raw["created_at"],
                )
            except (KeyError, TypeError):
                continue
            if not session.expired:
                self._by_token[session.token] = session

    def _save(self) -> None:
        payload = [
            {
                "token": s.token,
                "identity": asdict(s.identity),
                "created_at": s.created_at,
            }
            for s in self._by_token.values()
        ]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self._path)


class Authorizer:
    """Traduit une identité Discord en droits.

    Trois niveaux : owner (déclaré à l'installation), admin (promu par l'owner ou
    porteur du rôle configuré), participant (membre du serveur Discord).
    """

    def __init__(self, owner_id: int, settings):
        self._owner_id = owner_id
        self._settings = settings

    def is_owner(self, identity: Identity) -> bool:
        return identity.user_id == self._owner_id

    def is_admin(self, identity: Identity) -> bool:
        if self.is_owner(identity):
            return True
        if identity.user_id in self._settings["admin_ids"]:
            return True
        admin_role = self._settings["admin_role_id"]
        return admin_role is not None and admin_role in identity.role_ids

    def is_banned(self, identity: Identity) -> bool:
        # Un owner ne peut pas se bannir lui-même hors de son propre serveur.
        return not self.is_owner(identity) and identity.user_id in self._settings["banned_ids"]

    def may_upload(self, identity: Identity) -> bool:
        if self.is_banned(identity):
            return False
        if self.is_admin(identity):
            return True
        required = self._settings["upload_role_id"]
        return required is None or required in identity.role_ids

    def describe(self, identity: Identity) -> dict:
        return {
            **identity.public(),
            "is_owner": self.is_owner(identity),
            "is_admin": self.is_admin(identity),
            "may_upload": self.may_upload(identity),
        }
