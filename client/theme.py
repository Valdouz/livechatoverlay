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
/* Compact : fenêtre sans cadre, coins arrondis dessinés par la feuille de style.
   Agrandi : cadre natif du système, donc ni bordure ni arrondi de notre part. */
QWidget#panel {
    background: #14141d;
    border: 1px solid #2a2a3a;
    border-radius: 14px;
}
QWidget#panel[expanded="true"] {
    border: none;
    border-radius: 0;
}

QLabel            { color: #d5d5e2; font: 13px 'Segoe UI', sans-serif; }
QLabel#title      { color: #f2f2f7; font: 600 16px 'Segoe UI', sans-serif; }
QLabel#subtitle   { color: #8a8aa2; font: 12px 'Segoe UI', sans-serif; }
QLabel#headline   { color: #e8e8f2; font: 500 15px 'Segoe UI', sans-serif; line-height: 140%; }
QLabel#section    { color: #7f7f9c; font: 600 10px 'Segoe UI', sans-serif;
                    letter-spacing: 1.2px; }
QLabel#value      { color: #9a9ab4; font: 600 12px 'Segoe UI', sans-serif; }
QLabel#hint       { color: #6e6e88; font: 12px 'Segoe UI', sans-serif; }
QLabel#error      { color: #ff9090; font: 12px 'Segoe UI', sans-serif; }
QLabel#ok         { color: #3ddc84; font: 12px 'Segoe UI', sans-serif; }

QLabel#dot_on     { color: #3ddc84; font: 11px 'Segoe UI', sans-serif; }
QLabel#dot_wait   { color: #f0b040; font: 11px 'Segoe UI', sans-serif; }
QLabel#dot_off    { color: #55556a; font: 11px 'Segoe UI', sans-serif; }

QPushButton {
    background: #23232f; color: #e2e2ee; border: none; border-radius: 8px;
    padding: 9px 14px; font: 13px 'Segoe UI', sans-serif;
}
QPushButton:hover    { background: #2e2e3d; }
QPushButton:pressed  { background: #38384a; }
QPushButton:disabled { background: #1b1b24; color: #4e4e63; }

QPushButton#primary  { background: #3ddc84; color: #0b0b12;
                       font: 600 13px 'Segoe UI', sans-serif; }
QPushButton#primary:hover    { background: #55e295; }
QPushButton#primary:disabled { background: #26402f; color: #6a8a76; }

QPushButton#danger   { background: #34202a; color: #ff9d9d; }
QPushButton#danger:hover { background: #452833; }

QPushButton#ghost_button {
    background: transparent; color: #7f7f9c; padding: 5px 10px;
}
QPushButton#ghost_button:hover { color: #e8e8f2; background: #20202c; }

QComboBox {
    background: #1e1e29; color: #e2e2ee; border: 1px solid #30304a;
    border-radius: 8px; padding: 8px 10px; font: 13px 'Segoe UI', sans-serif;
}
QComboBox:hover { border-color: #3d3d5c; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #1a1a24; color: #e2e2ee; border: 1px solid #30304a; padding: 4px;
    selection-background-color: #3ddc84; selection-color: #0b0b12; outline: none;
}

QLineEdit {
    background: #1e1e29; color: #e2e2ee; border: 1px solid #30304a;
    border-radius: 8px; padding: 9px 11px; font: 13px 'Segoe UI', sans-serif;
}
QLineEdit:focus       { border-color: #3ddc84; }
QLineEdit::placeholder { color: #55556a; }

QSlider::groove:horizontal { height: 4px; background: #292937; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #3ddc84; width: 15px; height: 15px; margin: -6px 0; border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: #55e295; }
QSlider::sub-page:horizontal { background: #3ddc84; border-radius: 2px; }

QCheckBox { color: #d5d5e2; font: 13px 'Segoe UI', sans-serif; spacing: 9px; }
QCheckBox::indicator {
    width: 17px; height: 17px; border-radius: 5px;
    border: 2px solid #3b3b52; background: #1e1e29;
}
QCheckBox::indicator:hover   { border-color: #4d4d6b; }
QCheckBox::indicator:checked { background: #3ddc84; border-color: #3ddc84; }

QProgressBar {
    background: #23232f; border: none; border-radius: 4px; height: 7px; text-align: center;
}
QProgressBar::chunk { background: #3ddc84; border-radius: 4px; }

QTabWidget::pane { border: none; }
QTabBar::tab {
    background: transparent; color: #7f7f9c; padding: 8px 14px;
    font: 13px 'Segoe UI', sans-serif; border-bottom: 2px solid transparent;
}
QTabBar::tab:hover    { color: #b9b9d0; }
QTabBar::tab:selected { color: #f2f2f7; border-bottom-color: #3ddc84; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #2e2e40; border-radius: 4px; min-height: 26px; }
QScrollBar::handle:vertical:hover { background: #3c3c54; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QWidget#drop_zone {
    border: 2px dashed #38384f; border-radius: 12px; background: #191922;
}
QWidget#drop_zone[hover="true"] { border-color: #3ddc84; background: #17251c; }
QLabel#drop_icon  { color: #4a4a66; font: 300 26px 'Segoe UI', sans-serif; }
QLabel#drop_title { color: #b9b9d0; font: 13px 'Segoe UI', sans-serif; }
"""
