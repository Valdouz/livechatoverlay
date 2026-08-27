"""Configuration d'installation.

Lue une fois au démarrage depuis l'environnement, jamais modifiée en cours de route.
Tout ce qui se règle à chaud vit dans `settings.py` et se pilote depuis le panneau admin.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Configuration absente ou invalide — le message est destiné à l'humain qui installe."""


def load_dotenv(path: Path | None = None) -> bool:
    """Charge un fichier .env dans l'environnement, sans dépendance externe.

    Docker s'en charge lui-même via `env_file` ; ceci sert au lancement direct,
    pour que `python -m server` fonctionne sans exporter dix variables à la main.
    Ce qui est déjà présent dans l'environnement gagne.
    """
    target = path or Path(__file__).resolve().parent.parent / ".env"
    if not target.exists():
        return False
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} est absent.\n"
            f"Copiez .env.example en .env et remplissez-le — voir INSTALL.md."
        )
    return value


def _required_int(name: str) -> int:
    raw = _required(name)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(
            f"{name} doit être un identifiant Discord numérique, reçu : {raw!r}.\n"
            f"Dans Discord : Paramètres > Avancés > Mode développeur, puis clic droit > "
            f"Copier l'identifiant."
        ) from None


@dataclass(frozen=True)
class Config:
    discord_token: str
    client_id: str
    client_secret: str
    guild_id: int
    owner_id: int
    public_url: str
    data_dir: Path
    host: str
    port: int

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @classmethod
    def from_env(cls) -> Config:
        public_url = _required("PUBLIC_URL").rstrip("/")
        if not public_url.startswith(("http://", "https://")):
            raise ConfigError(
                f"PUBLIC_URL doit commencer par http:// ou https://, reçu : {public_url!r}"
            )

        config = cls(
            discord_token=_required("DISCORD_TOKEN"),
            client_id=_required("DISCORD_CLIENT_ID"),
            client_secret=_required("DISCORD_CLIENT_SECRET"),
            guild_id=_required_int("DISCORD_GUILD_ID"),
            owner_id=_required_int("OWNER_ID"),
            public_url=public_url,
            data_dir=Path(os.environ.get("DATA_DIR", "./data")).resolve(),
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "3000")),
        )
        config.media_dir.mkdir(parents=True, exist_ok=True)
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        return config
