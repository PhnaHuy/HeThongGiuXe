"""Shared light theme for the desktop application."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

APP_STYLESHEET = """
QWidget {
    color: #172b3a;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QMainWindow, QDialog {
    background: #f3f6fa;
}
QWidget#appHeader {
    background: #ffffff;
    border: 1px solid #e1e8ef;
    border-radius: 12px;
}
QLabel#appTitle {
    color: #123047;
    font-size: 17pt;
    font-weight: 700;
}
QLabel#appSubtitle {
    color: #687d8c;
    font-size: 9pt;
}
QLabel#userInfo {
    color: #365266;
    background: #f0f6f7;
    border: 1px solid #dce9e9;
    border-radius: 9px;
    padding: 8px 12px;
    font-weight: 600;
}
QFrame#headerDivider {
    color: #e2e8ef;
    background: #e2e8ef;
    max-height: 1px;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #dce5ed;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    color: #526879;
    background: transparent;
    border: 0;
    border-bottom: 3px solid transparent;
    min-height: 40px;
    padding: 0 15px;
    margin-right: 3px;
    font-weight: 600;
}
QTabBar::tab:hover {
    color: #0f766e;
    background: #edf7f6;
}
QTabBar::tab:selected {
    color: #0f766e;
    background: #ffffff;
    border-bottom: 3px solid #0f766e;
}
QPushButton {
    color: #234052;
    background: #ffffff;
    border: 1px solid #cbd8e2;
    border-radius: 7px;
    min-height: 34px;
    padding: 0 13px;
    font-weight: 600;
}
QPushButton:hover {
    color: #0f625c;
    background: #eff8f7;
    border-color: #79b9b2;
}
QPushButton:pressed {
    background: #dcefeb;
}
QPushButton:disabled {
    color: #9aa8b3;
    background: #edf1f4;
    border-color: #dce3e8;
}
QPushButton#primaryButton {
    color: #ffffff;
    background: #0f766e;
    border-color: #0f766e;
}
QPushButton#primaryButton:hover {
    background: #0b625c;
    border-color: #0b625c;
}
QPushButton#dangerButton {
    color: #ffffff;
    background: #b94145;
    border-color: #b94145;
}
QPushButton#dangerButton:hover {
    background: #a33136;
    border-color: #a33136;
}
QLineEdit, QComboBox, QSpinBox, QDateEdit, QDateTimeEdit {
    color: #172b3a;
    background: #ffffff;
    border: 1px solid #cbd8e2;
    border-radius: 6px;
    min-height: 34px;
    padding: 0 9px;
    selection-background-color: #0f766e;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus,
QDateTimeEdit:focus {
    border: 1px solid #0f8b80;
}
QComboBox::drop-down {
    border: 0;
    width: 26px;
}
QGroupBox {
    color: #28465a;
    background: #ffffff;
    border: 1px solid #dce5ed;
    border-radius: 9px;
    margin-top: 13px;
    padding: 12px 10px 10px 10px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
}
QTableWidget, QTableView, QListWidget {
    color: #20394a;
    background: #ffffff;
    alternate-background-color: #f6f9fb;
    border: 1px solid #dce5ed;
    border-radius: 7px;
    gridline-color: #e8eef2;
    selection-background-color: #d9efec;
    selection-color: #163f41;
}
QHeaderView::section {
    color: #39576b;
    background: #f0f5f8;
    border: 0;
    border-bottom: 1px solid #dce5ed;
    padding: 8px 9px;
    font-weight: 700;
}
QCheckBox {
    spacing: 7px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
QSlider::groove:horizontal {
    height: 5px;
    background: #dce5eb;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #0f8b80;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 15px;
    margin: -6px 0;
    background: #ffffff;
    border: 2px solid #0f766e;
    border-radius: 8px;
}
QStatusBar {
    color: #526879;
    background: #ffffff;
    border-top: 1px solid #e1e8ef;
}
QScrollBar:vertical {
    width: 10px;
    background: transparent;
    margin: 2px;
}
QScrollBar::handle:vertical {
    min-height: 24px;
    background: #c5d2dc;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #91a8b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    height: 0;
    background: transparent;
}
"""


def install_app_theme(app: QApplication) -> None:
    """Apply the shared palette and typography before creating application windows."""
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(APP_STYLESHEET)
