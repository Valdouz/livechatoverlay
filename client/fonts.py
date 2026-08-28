"""La police embarquée.

Elle voyage avec l'application pour une raison précise : si le texte s'appuyait sur
une police installée localement, chaque participant verrait une substitution
différente, et personne ne verrait la même chose au même moment.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

log = logging.getLogger(__name__)

FONT_FILE = "Inter-Variable.ttf"
ICON_FILE = "icon.png"

_family: str | None = None


def assets_dir() -> Path:
    # PyInstaller déballe les ressources dans un dossier temporaire.
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parent / "assets"


def icon_path():
    """Le fichier d'icône embarqué, ou None s'il manque."""
    path = assets_dir() / ICON_FILE
    return path if path.exists() else None


def embedded_family() -> str:
    """Charge la police une fois et renvoie son nom de famille.

    En cas d'échec on retombe sur la police par défaut du système : mieux vaut un
    texte dans la mauvaise police qu'aucun texte.
    """
    global _family
    if _family is not None:
        return _family

    path = assets_dir() / FONT_FILE
    if path.exists():
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
        if families:
            _family = families[0]
            return _family
        log.warning("Police embarquée illisible : %s", path)
    else:
        log.warning("Police embarquée absente : %s", path)

    _family = QFont().defaultFamily()
    return _family


def display_font(size: int, weight: QFont.Weight, family: str = "") -> QFont:
    font = QFont(family or embedded_family(), size)
    font.setWeight(weight)
    return font
