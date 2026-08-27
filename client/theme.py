"""Constantes visuelles.

Un seul endroit à toucher pour changer l'allure de l'overlay.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

# -- overlay -----------------------------------------------------------------

#: Anneau autour de l'avatar. Vert fixe, volontairement : ce n'est pas la couleur
#: du rôle Discord, c'est l'identité visuelle de LiveChat.
RING_COLOR = QColor("#3ddc84")
RING_WIDTH = 4
RING_GLOW = QColor(61, 220, 132, 90)

#: L'avatar n'a pas de taille fixe : il vaut AVATAR_RATIO fois la hauteur du pseudo,
#: pour que la ligne reste équilibrée quelle que soit la taille de texte choisie.
AVATAR_RATIO = 1.18
AVATAR_MIN = 28
AUTHOR_GAP = 12          # entre la ligne auteur et le média
AVATAR_TEXT_GAP = 14     # entre l'avatar et le pseudo

#: Le pseudo est blanc à contour noir épais : lisible sur n'importe quel fond,
#: sans avoir besoin d'un fond opaque derrière.
NAME_COLOR = QColor("#ffffff")
NAME_OUTLINE_COLOR = QColor("#000000")
NAME_OUTLINE_WIDTH = 6
NAME_SIZE = 30

MEDIA_RADIUS = 16
MEDIA_SHADOW = QColor(0, 0, 0, 110)

CAPTION_SIZE = 22
CAPTION_COLOR = QColor("#ffffff")
CAPTION_OUTLINE_COLOR = QColor("#000000")
CAPTION_OUTLINE_WIDTH = 5
CAPTION_GAP = 10

FADE_MS = 260

# -- panneau -----------------------------------------------------------------

PANEL_QSS = """
QWidget#panel {
    background: #16161f;
    border: 1px solid #2c2c3a;
    border-radius: 14px;
}
QLabel#title      { color: #f0f0f5; font: 600 15px 'Segoe UI', sans-serif; }
QLabel#subtitle   { color: #7a7a92; font: 12px 'Segoe UI', sans-serif; }
QLabel#section    { color: #8b8ba7; font: 600 11px 'Segoe UI', sans-serif;
                    text-transform: uppercase; letter-spacing: 1px; }
QLabel            { color: #d8d8e4; font: 13px 'Segoe UI', sans-serif; }
QLabel#value      { color: #7a7a92; font: 12px 'Segoe UI', sans-serif; }
QLabel#error      { color: #ff8a8a; font: 12px 'Segoe UI', sans-serif; }
QLabel#ok         { color: #3ddc84; font: 12px 'Segoe UI', sans-serif; }

QPushButton {
    background: #24242f; color: #e4e4ee; border: none; border-radius: 8px;
    padding: 8px 14px; font: 13px 'Segoe UI', sans-serif;
}
QPushButton:hover    { background: #2f2f3d; }
QPushButton:pressed  { background: #3a3a4b; }
QPushButton:disabled { background: #1d1d26; color: #55556a; }
QPushButton#primary  { background: #3ddc84; color: #0d0d14; font-weight: 600; }
QPushButton#primary:hover { background: #52e594; }
QPushButton#danger   { background: #3a2028; color: #ff9d9d; }
QPushButton#danger:hover  { background: #4b262f; }
QPushButton#ghost    { background: transparent; color: #7a7a92; padding: 4px 8px; }
QPushButton#ghost:hover   { color: #e4e4ee; }

QComboBox {
    background: #24242f; color: #e4e4ee; border: 1px solid #33334a;
    border-radius: 8px; padding: 6px 10px; font: 13px 'Segoe UI', sans-serif;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #1d1d28; color: #e4e4ee; border: 1px solid #33334a;
    selection-background-color: #3ddc84; selection-color: #0d0d14; outline: none;
}

QSlider::groove:horizontal { height: 4px; background: #2c2c3a; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #3ddc84; width: 15px; height: 15px; margin: -6px 0; border-radius: 8px;
}
QSlider::sub-page:horizontal { background: #3ddc84; border-radius: 2px; }

QCheckBox { color: #d8d8e4; font: 13px 'Segoe UI', sans-serif; spacing: 9px; }
QCheckBox::indicator {
    width: 17px; height: 17px; border-radius: 5px;
    border: 2px solid #3f3f52; background: #24242f;
}
QCheckBox::indicator:checked { background: #3ddc84; border-color: #3ddc84; }

QLineEdit {
    background: #24242f; color: #e4e4ee; border: 1px solid #33334a;
    border-radius: 8px; padding: 7px 10px; font: 13px 'Segoe UI', sans-serif;
}
QLineEdit:focus { border-color: #3ddc84; }

QProgressBar {
    background: #24242f; border: none; border-radius: 5px; height: 8px; text-align: center;
}
QProgressBar::chunk { background: #3ddc84; border-radius: 5px; }

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; color: #7a7a92; padding: 7px 9px;
    font: 12px 'Segoe UI', sans-serif; border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #f0f0f5; border-bottom-color: #3ddc84; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #33334a; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }

QFrame#separator { background: #26263200; max-height: 1px; }

QWidget#drop_zone {
    border: 2px dashed #3f3f52; border-radius: 10px; background: #1b1b25;
}
QWidget#drop_zone[hover="true"] { border-color: #3ddc84; background: #1e2a22; }
"""
