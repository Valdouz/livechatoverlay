"""Réglages locaux du participant.

Ce sont eux qui gagnent : le serveur ne fournit que des valeurs par défaut, utilisées
tant que le participant n'a touché à rien. En v1 le serveur poussait la taille et la
durée dans chaque message et écrasait tout, ce qui rendait le panneau inutile.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CORNERS = {
    "bottom-right": "En bas à droite",
    "bottom-left": "En bas à gauche",
    "top-right": "En haut à droite",
    "top-left": "En haut à gauche",
    "center": "Au centre",
}

AUTHOR_POSITIONS = {
    "above": "Au-dessus du média",
    "over": "Sur le média",
    "hidden": "Masqué",
}

DEFAULTS: dict[str, Any] = {
    "server_url": "",
    "token": "",
    # Affichage
    "screen_name": "",          # vide = écran principal
    "corner": "bottom-right",
    "margin": 40,
    "scale_percent": 0,         # 0 = suivre la valeur par défaut du serveur
    "opacity_percent": 100,
    "image_duration_seconds": 0,  # 0 = suivre le serveur
    # Texte
    "font_family": "",          # vide = la police embarquée
    "caption_size": 22,
    "name_size": 30,
    # Auteur
    "author_position": "above",
    # Son
    "volume": 80,
    "muted": False,
    # Comportement
    "avoid_fullscreen": True,   # basculer d'écran si un jeu occupe celui-ci
    "panel_expanded": False,    # petit panneau flottant, ou vraie fenêtre
}

#: Réglages dont la valeur 0 signifie « prendre celle du serveur ».
_SERVER_FALLBACK = {"scale_percent", "image_duration_seconds"}


class ClientSettings:
    def __init__(self, path: Path):
        self._path = path
        self._values = dict(DEFAULTS)
        self._server_defaults = {"media_scale_percent": 30, "image_duration_seconds": 8}
        self._load()

    # -- lecture --------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def get(self, key: str, fallback: Any = None) -> Any:
        return self._values.get(key, fallback)

    @property
    def scale_percent(self) -> int:
        chosen = self._values["scale_percent"]
        return chosen or self._server_defaults["media_scale_percent"]

    @property
    def image_duration(self) -> int:
        chosen = self._values["image_duration_seconds"]
        return chosen or self._server_defaults["image_duration_seconds"]

    def follows_server(self, key: str) -> bool:
        return key in _SERVER_FALLBACK and not self._values[key]

    # -- écriture -------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        if self._values[key] == value:
            return
        self._values[key] = value
        self._save()

    def apply_server_defaults(self, defaults: dict) -> None:
        """Le serveur annonce ses valeurs par défaut ; elles n'écrasent aucun choix local."""
        for key in ("media_scale_percent", "image_duration_seconds"):
            if key in defaults:
                try:
                    self._server_defaults[key] = int(defaults[key])
                except (TypeError, ValueError):
                    pass

    # -- persistance ----------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Réglages illisibles (%s), valeurs par défaut.", exc)
            return
        self._values.update({k: v for k, v in stored.items() if k in DEFAULTS})

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
        tmp.replace(self._path)
