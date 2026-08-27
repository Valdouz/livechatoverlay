"""Réglages modifiables à chaud depuis le panneau admin.

Persistés dans un JSON du dossier de données, séparé de la configuration
d'installation qui, elle, ne contient que des secrets.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

GIGA = 1024 ** 3

DEFAULTS: dict[str, Any] = {
    # Stockage
    "disk_quota_bytes": 30 * GIGA,
    "max_file_bytes": 5 * GIGA,
    # Rétention : suppression 10 min après réception par tous, plafond 1 h
    "retention_after_ack_seconds": 10 * 60,
    "retention_hard_cap_seconds": 60 * 60,
    # Affichage — valeurs par défaut, chaque participant peut les surcharger
    "image_duration_seconds": 8,
    "media_scale_percent": 30,
    # Discord
    "channel_id": None,          # salon surveillé ; None = aucun
    "upload_role_id": None,      # rôle requis pour envoyer ; None = tout le monde
    "admin_role_id": None,       # rôle donnant les droits admin ; None = aucun
    # Administration
    "admin_ids": [],             # identifiants Discord promus par l'owner
    "banned_ids": [],
}

# Bornes de validation : (minimum, maximum) pour les entiers réglables.
BOUNDS: dict[str, tuple[int, int]] = {
    "disk_quota_bytes": (1 * GIGA, 2000 * GIGA),
    "max_file_bytes": (1024 * 1024, 20 * GIGA),
    "retention_after_ack_seconds": (0, 24 * 3600),
    "retention_hard_cap_seconds": (60, 7 * 24 * 3600),
    "image_duration_seconds": (1, 300),
    "media_scale_percent": (5, 100),
}

_ID_FIELDS = {"channel_id", "upload_role_id", "admin_role_id"}
_ID_LIST_FIELDS = {"admin_ids", "banned_ids"}


class SettingsError(ValueError):
    """Valeur refusée — le message remonte tel quel au panneau admin."""


class Settings:
    def __init__(self, path: Path):
        self._path = path
        self._values = dict(DEFAULTS)
        self._load()

    # ── lecture ───────────────────────────────────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    # ── écriture ──────────────────────────────────────────────────────────────

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Valide et applique un lot de modifications. Tout ou rien."""
        unknown = set(patch) - set(DEFAULTS)
        if unknown:
            raise SettingsError(f"Réglages inconnus : {', '.join(sorted(unknown))}")

        validated = {key: self._coerce(key, value) for key, value in patch.items()}
        self._values.update(validated)
        self._save()
        log.info("Réglages modifiés : %s", ", ".join(sorted(validated)))
        return validated

    def _coerce(self, key: str, value: Any) -> Any:
        if key in BOUNDS:
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} doit être un nombre entier.") from None
            low, high = BOUNDS[key]
            if not low <= number <= high:
                raise SettingsError(f"{key} doit être compris entre {low} et {high}.")
            return number

        if key in _ID_FIELDS:
            if value in (None, "", 0):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} doit être un identifiant Discord numérique.") from None

        if key in _ID_LIST_FIELDS:
            if not isinstance(value, list):
                raise SettingsError(f"{key} doit être une liste d'identifiants.")
            try:
                return sorted({int(item) for item in value})
            except (TypeError, ValueError):
                raise SettingsError(f"{key} ne doit contenir que des identifiants numériques.") from None

        return value

    # ── persistance ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            self._save()
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Réglages illisibles (%s), retour aux valeurs par défaut.", exc)
            return
        # Les clés retirées d'une version à l'autre sont ignorées silencieusement.
        self._values.update({k: v for k, v in stored.items() if k in DEFAULTS})

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
        tmp.replace(self._path)
