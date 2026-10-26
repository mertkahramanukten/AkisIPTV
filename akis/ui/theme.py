"""Koyu tema. Renkler tek yerde; QSS bunlardan üretilir."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

C = {
    "bg": "#0E131B",
    "bg2": "#141B26",
    "panel": "#18212E",
    "panel2": "#1E2836",
    "line": "#263243",
    "text": "#E6EDF5",
    "muted": "#8A99AD",
    "dim": "#5E6C80",
    "accent": "#3FE0BE",
    "accent2": "#7C8CFF",
    "warn": "#F5B84B",
    "error": "#FF6B6B",
    "ok": "#3FE0BE",
    "sel": "#22324A",
    "hover": "#1C2A3D",
}

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QDialog {{ background: {C['bg']}; }}
QWidget#TopBar {{ background: {C['bg2']}; border-bottom: 1px solid {C['line']}; }}
QWidget#SidePanel, QWidget#ListPanel {{ background: {C['bg2']}; }}
QWidget#InfoPanel {{ background: {C['panel']}; border-top: 1px solid {C['line']}; }}
QWidget#PlayerBar {{ background: {C['panel']}; border-top: 1px solid {C['line']}; }}
QLabel#AppTitle {{ font-size: 15pt; font-weight: 700; color: {C['accent']}; padding-right: 10px; }}
QLabel#H1 {{ font-size: 15pt; font-weight: 700; }}
QLabel#H2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#Muted {{ color: {C['muted']}; }}
QLabel#SectionTitle {{ color: {C['muted']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; padding: 10px 12px 4px 12px; }}
QLabel#Error {{ color: {C['error']}; }}
QLabel#Badge {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 9px; padding: 2px 8px; color: {C['muted']}; font-size: 8.5pt; }}

QPushButton {{ background: {C['panel2']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ background: {C['hover']}; border-color: #34465E; }}
QPushButton:pressed {{ background: {C['sel']}; }}
QPushButton:disabled {{ color: {C['dim']}; }}
QPushButton#Primary {{ background: {C['accent']}; color: #06261F; border: none; font-weight: 700; }}
QPushButton#Primary:hover {{ background: #5BF0D0; }}
QPushButton#Primary:disabled {{ background: #2A5C52; color: #0E2A25; }}
QPushButton#Mode {{ background: transparent; border: none; border-radius: 0; padding: 14px 16px 12px 16px;
                    color: {C['muted']}; font-weight: 600; border-bottom: 2px solid transparent; }}
QPushButton#Mode:hover {{ color: {C['text']}; }}
QPushButton#Mode:checked {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px; }}
QToolButton:hover {{ background: {C['hover']}; }}
QToolButton:checked {{ background: {C['sel']}; }}

QLineEdit, QComboBox, QSpinBox {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 6px 10px;
                                  selection-background-color: {C['accent2']}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {C['panel']}; border: 1px solid {C['line']}; selection-background-color: {C['sel']}; outline: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['line']}; background: {C['panel']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}

QListView, QListWidget, QTreeView {{ background: transparent; border: none; outline: 0; }}
QListWidget#Categories::item {{ padding: 7px 12px; border-radius: 6px; margin: 1px 6px; color: {C['muted']}; }}
QListWidget#Categories::item:hover {{ background: {C['hover']}; color: {C['text']}; }}
QListWidget#Categories::item:selected {{ background: {C['sel']}; color: {C['text']}; }}
QListWidget#Episodes::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 0; }}
QListWidget#Episodes::item:hover {{ background: {C['hover']}; }}
QListWidget#Episodes::item:selected {{ background: {C['sel']}; }}
QListWidget#Upcoming::item {{ padding: 3px 2px; color: {C['muted']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2B3A50; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4E6A; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2B3A50; border-radius: 4px; min-width: 30px; }}

QSlider::groove:horizontal {{ height: 4px; background: {C['line']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {C['text']}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QProgressBar {{ background: {C['line']}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}

QSplitter::handle {{ background: {C['line']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {C['bg2']}; border-top: 1px solid {C['line']}; color: {C['muted']}; }}
QStatusBar QLabel {{ color: {C['muted']}; padding: 0 6px; }}
QMenu {{ background: {C['panel']}; border: 1px solid {C['line']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['sel']}; }}
QMenu::separator {{ height: 1px; background: {C['line']}; margin: 4px 8px; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['line']}; padding: 4px; }}
QTabWidget::pane {{ border: none; }}
QGroupBox {{ border: 1px solid {C['line']}; border-radius: 10px; margin-top: 14px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {C['muted']}; }}
"""


def apply(app) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(C["bg"]))
    pal.setColor(QPalette.WindowText, QColor(C["text"]))
    pal.setColor(QPalette.Base, QColor(C["panel"]))
    pal.setColor(QPalette.AlternateBase, QColor(C["panel2"]))
    pal.setColor(QPalette.Text, QColor(C["text"]))
    pal.setColor(QPalette.Button, QColor(C["panel2"]))
    pal.setColor(QPalette.ButtonText, QColor(C["text"]))
    pal.setColor(QPalette.Highlight, QColor(C["sel"]))
    pal.setColor(QPalette.HighlightedText, QColor(C["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(C["panel2"]))
    pal.setColor(QPalette.ToolTipText, QColor(C["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(C["dim"]))
    app.setPalette(pal)
    f = QFont("Segoe UI", 10)
    app.setFont(f)
    app.setStyleSheet(QSS)
