"""Application stylesheet."""

from __future__ import annotations

from pathlib import Path


def build_app_stylesheet() -> str:
    chevron_path = (Path(__file__).resolve().parent / "assets" / "chevron-down.svg").as_posix()
    return """
QMainWindow, QWidget {
    background: #ffffff;
    color: #1d1d1f;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}
QScrollArea, QScrollArea QWidget, QScrollArea > QWidget > QWidget {
    background: #ffffff;
    border: 0;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px 2px 4px 2px;
}
QScrollBar::handle:vertical {
    background: rgba(60, 60, 67, 0.28);
    border-radius: 4px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(60, 60, 67, 0.42);
}
QScrollBar::handle:vertical:pressed {
    background: rgba(60, 60, 67, 0.55);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    border: 0;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px 4px 2px 4px;
}
QScrollBar::handle:horizontal {
    background: rgba(60, 60, 67, 0.28);
    border-radius: 4px;
    min-width: 36px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(60, 60, 67, 0.42);
}
QScrollBar::handle:horizontal:pressed {
    background: rgba(60, 60, 67, 0.55);
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
    border: 0;
    width: 0;
}
QFrame#Panel {
    background: #ffffff;
    border: 1px solid #dedee3;
    border-radius: 14px;
}
QFrame#ToolbarPanel {
    background: #ffffff;
    border: 1px solid #dedee3;
    border-radius: 14px;
}
QFrame#InlinePanel {
    background: #ffffff;
    border: 1px solid #dedee3;
    border-radius: 10px;
}
QFrame#Divider {
    color: #dedee3;
    background: #dedee3;
    border: 0;
    max-height: 1px;
}
FilterRow#Panel {
    border-radius: 10px;
}
QLabel#Title {
    font-size: 24px;
    font-weight: 700;
}
QLabel#Logo {
    font-size: 22px;
    font-weight: 750;
    color: #1d1d1f;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 650;
}
QLabel#Warning {
    color: #1d1d1f;
}
QLabel#SourceTag {
    color: #6e6e73;
    font-size: 11px;
}
QComboBox, QSpinBox, QLineEdit {
    background: #ffffff;
    border: 1px solid #d1d1d6;
    border-radius: 9px;
    padding: 6px 10px;
    min-height: 24px;
}
QComboBox {
    padding: 6px 30px 6px 11px;
}
QComboBox#CompactCombo {
    min-height: 22px;
    padding: 4px 26px 4px 9px;
    border-radius: 8px;
}
QLineEdit#CompactField {
    min-height: 22px;
    padding: 4px 9px;
    border-radius: 8px;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
    border-color: #b8b8bf;
    background: #fbfbfd;
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
    border-color: #8ab4f8;
}
QLineEdit:disabled {
    color: #8e8e93;
    background: #fbfbfd;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: 0;
    background: transparent;
}
QComboBox::down-arrow {
    image: url("__CHEVRON_PATH__");
    width: 12px;
    height: 8px;
    margin-right: 9px;
}
QComboBox#CompactCombo::drop-down {
    width: 24px;
}
QComboBox#CompactCombo::down-arrow {
    margin-right: 7px;
}
QComboBox QAbstractItemView {
    background: transparent;
    border: 1px solid #d1d1d6;
    border-radius: 12px;
    padding: 1px;
    margin: 0;
    outline: 0;
    selection-background-color: #ffffff;
    selection-color: #1d1d1f;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 5px 10px;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item:selected {
    background: #ffffff;
    color: #1d1d1f;
}
QListView#ModePopup, QListView#FlatComboPopup {
    background: transparent;
    border: 1px solid #d1d1d6;
    border-radius: 12px;
    padding: 1px;
    margin: 0;
    outline: 0;
    selection-background-color: #ffffff;
    selection-color: #1d1d1f;
}
QListView#ModePopup::viewport, QListView#FlatComboPopup::viewport {
    background: transparent;
    border: 0;
    margin: 0;
}
QListView#ModePopup::item, QListView#FlatComboPopup::item {
    background: #ffffff;
    min-height: 28px;
    padding: 7px 14px;
    border-radius: 0;
}
QListView#ModePopup::item:first, QListView#FlatComboPopup::item:first {
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QListView#ModePopup::item:last, QListView#FlatComboPopup::item:last {
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QListView#ModePopup::item:selected, QListView#FlatComboPopup::item:selected {
    background: #ffffff;
    color: #1d1d1f;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #d1d1d6;
    border-radius: 8px;
    padding: 4px;
}
QListWidget::item {
    border-radius: 6px;
    padding: 4px 6px;
}
QListWidget::item:selected {
    background: #e8f2ff;
    color: #1d1d1f;
}
QTableWidget#SummaryTable {
    background: #ffffff;
    border: 1px solid #d1d1d6;
    border-radius: 10px;
    gridline-color: #ececf0;
    selection-background-color: transparent;
    selection-color: #1d1d1f;
}
QTableWidget#SummaryTable::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background: #f5f5f7;
    border: 0;
    border-bottom: 1px solid #dedee3;
    padding: 5px 6px;
    font-weight: 650;
}
QCheckBox#PlotToggle, QRadioButton#PlotToggle {
    spacing: 6px;
    padding: 0;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d1d6;
    border-radius: 9px;
    padding: 7px 12px;
}
QPushButton:hover { background: #f0f0f2; }
QPushButton#Primary {
    background: #0a84ff;
    border-color: #0a84ff;
    color: white;
    font-weight: 650;
    padding: 9px 18px;
}
QPushButton#PlotSave {
    background: rgba(10, 132, 255, 0.16);
    border: 1px solid rgba(10, 132, 255, 0.20);
    color: rgba(255, 255, 255, 0.72);
    font-weight: 650;
    padding: 7px 12px;
}
QPushButton#PlotSave:hover {
    background: #0a84ff;
    border-color: #0a84ff;
    color: white;
}
QPushButton#Danger {
    color: #b42318;
}
QPushButton#GhostRemove {
    background: transparent;
    border-color: transparent;
}
QTabWidget::pane {
    border: 0;
    border-radius: 0;
    background: white;
}
QScrollArea#PlotLegend {
    background: #ffffff;
    border: 0;
}
QTabBar::tab {
    background: #f5f5f7;
    border-radius: 8px;
    padding: 7px 14px;
    margin: 4px;
    min-width: 180px;
}
QTabBar::tab:selected {
    background: white;
    border: 1px solid #d1d1d6;
}
""".replace("__CHEVRON_PATH__", chevron_path)


APP_STYLESHEET = build_app_stylesheet()
