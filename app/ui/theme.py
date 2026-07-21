from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Designsprache abgeleitet von https://www.kolpingjugend-regensburg.de/
# (Divi/WordPress-Theme: Primaerfarbe Orange #ff8c00 / #ef800c, warmes Dunkelgrau
# #2f2c2a als Textfarbe, helle Flaechen #f7f7f7/#ffffff, Schrift "Open Sans").
ORANGE = "#FF8C00"
ORANGE_HOVER = "#EF800C"
ORANGE_PRESSED = "#D97400"
ORANGE_TINT = "#FFF1E0"
ORANGE_TINT_STRONG = "#FFE3C2"

TEXT_DARK = "#2F2C2A"
TEXT_MUTED = "#6B6864"

BG_PAGE = "#F7F7F7"
BG_SURFACE = "#FFFFFF"
BORDER = "#E0DFDD"
BORDER_STRONG = "#D3D1CD"

FONT_FAMILIES = ["Open Sans", "Segoe UI", "Arial", "sans-serif"]

STYLESHEET = f"""
QWidget {{
    background-color: {BG_PAGE};
    color: {TEXT_DARK};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {BG_PAGE};
}}

QLabel {{
    background: transparent;
}}

QLabel[role="pageTitle"] {{
    color: {TEXT_DARK};
    font-size: 22px;
    font-weight: 600;
    padding: 2px 0 0 0;
}}

QLabel[role="pageSubtitle"] {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding: 0 0 4px 0;
}}

/* Seitenleiste */
QListWidget#Sidebar {{
    background-color: {BG_SURFACE};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 14px 0px;
    outline: 0;
    font-size: 14px;
}}
QListWidget#Sidebar::item {{
    padding: 11px 20px;
    margin: 1px 0;
    border-left: 3px solid transparent;
    color: {TEXT_DARK};
    font-weight: 600;
}}
QListWidget#Sidebar::item:hover {{
    background-color: {ORANGE_TINT};
}}
QListWidget#Sidebar::item:selected {{
    background-color: {ORANGE_TINT};
    border-left: 3px solid {ORANGE};
    color: {ORANGE_HOVER};
}}

/* Buttons */
QPushButton {{
    background-color: {ORANGE};
    color: {BG_SURFACE};
    border: none;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {ORANGE_HOVER};
}}
QPushButton:pressed {{
    background-color: {ORANGE_PRESSED};
}}
QPushButton:disabled {{
    background-color: {BORDER};
    color: {TEXT_MUTED};
}}
QPushButton[role="secondary"] {{
    background-color: {BG_SURFACE};
    color: {ORANGE_HOVER};
    border: 1px solid {ORANGE};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {ORANGE_TINT};
}}

/* Eingabefelder */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {ORANGE};
    selection-color: {BG_SURFACE};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ORANGE};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

/* Tabellen und Listen */
QTableWidget, QListWidget {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    gridline-color: {BORDER};
    selection-background-color: {ORANGE_TINT_STRONG};
    selection-color: {TEXT_DARK};
}}
QHeaderView::section {{
    background-color: {BG_PAGE};
    color: {TEXT_DARK};
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid {ORANGE};
    font-weight: 600;
}}
QTableWidget::item, QListWidget::item {{
    padding: 3px 4px;
}}

/* Gruppen */
QGroupBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    font-weight: 600;
    padding-top: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {ORANGE_HOVER};
}}

QSplitter::handle {{
    background-color: {BORDER};
}}

/* Tabs */
QTabWidget::pane {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {BG_PAGE};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 2px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    background-color: {ORANGE_TINT};
    color: {ORANGE_HOVER};
}}
QTabBar::tab:selected {{
    background-color: {BG_SURFACE};
    color: {ORANGE_HOVER};
    border-bottom: 2px solid {ORANGE};
}}

QStatusBar {{
    background-color: {BG_SURFACE};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}

QScrollBar:vertical {{
    background: {BG_PAGE};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ORANGE};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Wendet die an die Kolpingjugend-Regensburg-Website angelehnte Designsprache an."""
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
