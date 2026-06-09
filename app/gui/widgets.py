"""Reusable Qt widgets."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy


class Panel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")


class FilterRow(Panel):
    changed = Signal()
    committed = Signal()
    aoi_changed = Signal()
    aoi_committed = Signal()
    removed = Signal(object)

    def __init__(self, filter_names: list[str], *, removable: bool = True) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        self.filter_combo = QComboBox()
        self.filter_combo.setEditable(True)
        self.filter_combo.addItems([""] + filter_names)
        self.filter_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("CompactCombo")
        self.mode_combo.addItems(["transmission", "reflection", "visualize", "excluded"])
        self.mode_combo.setFixedWidth(132)

        self.aoi_edit = QLineEdit("0")
        self.aoi_edit.setObjectName("CompactField")
        self.aoi_edit.setFixedWidth(70)
        self._aoi_filter_name = ""
        self._default_aoi = 0

        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("Danger")
        self.remove_button.setFixedWidth(78)
        layout.addWidget(self.filter_combo, 3)
        layout.addWidget(self.mode_combo, 1)
        layout.addWidget(self.aoi_edit, 1)
        layout.addWidget(self.remove_button)

        self.filter_combo.currentTextChanged.connect(lambda _text: self.changed.emit())
        self.mode_combo.currentTextChanged.connect(lambda _text: self.changed.emit())
        self.aoi_edit.textChanged.connect(lambda _text: self.aoi_changed.emit())
        self.aoi_edit.editingFinished.connect(self.aoi_committed.emit)
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        if self.filter_combo.lineEdit():
            self.filter_combo.lineEdit().returnPressed.connect(self.committed.emit)

    def selected_filter(self) -> str:
        return self.filter_combo.currentText().strip()

    def selected_mode(self) -> str:
        return self.mode_combo.currentText().strip()

    def selected_aoi(self) -> int | None:
        text = self.aoi_edit.text().strip()
        if not text:
            self.aoi_edit.setText(str(self._default_aoi))
            return self._default_aoi
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            self.aoi_edit.setText(str(self._default_aoi))
            return self._default_aoi
        value = int(digits)
        self.aoi_edit.setText(str(value))
        return value

    def set_default_aoi(self, filter_name: str, default_aoi: int | None) -> None:
        resolved = 0 if default_aoi is None else int(default_aoi)
        if self._aoi_filter_name == filter_name and self._default_aoi == resolved:
            return
        self._aoi_filter_name = filter_name
        self._default_aoi = resolved
        self.aoi_edit.blockSignals(True)
        self.aoi_edit.setText(str(resolved))
        self.aoi_edit.blockSignals(False)
