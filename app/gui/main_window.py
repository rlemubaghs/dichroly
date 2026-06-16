"""Main PySide6 window. Front end is not my strength. For GUI bugs blame Claude, for other bugs blame me."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path
import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QFrame,
    QProxyStyle,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.analysis.aoi_analysis import requested_aoi_values, requested_relative_aoi_values
from app.analysis.calculations import SelectedFilter, calculate_spectral_result, filter_curve_for_mode
from app.data.catalog import Catalog, build_catalog, default_data_root, project_root, safe_name
from app.data.downloader import download_filter_configuration, download_single_item
from app.data.loaders import load_filter, load_fluorophore, load_light_source
from app.data.searchlight_client import fetch_searchlight_options
from app.data.spectra import Spectrum, interpolate_values
from app.gui.styles import APP_STYLESHEET
from app.gui.widgets import FilterRow, Panel
from app.plotting.plots import AoiAreaPlot, AoiHeatmapPlot, LINE_COLORS, SpectraPlot, VISUALIZE_FILTER_COLOR


@dataclass
class HeatmapSet:
    title_label: QLabel
    control_widget: QWidget
    plot_widget: QWidget
    x_combo: QComboBox
    y_combo: QComboBox
    percent_min: QLineEdit
    percent_max: QLineEdit
    auto_percent_check: QCheckBox
    plot: AoiHeatmapPlot


class ComboItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):  # noqa: ANN001
        size = super().sizeHint(option, index)
        return QSize(size.width(), 38)


class NonNativeComboPopupStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: ANN001
        if hint == QStyle.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class MainWindow(QMainWindow):
    def __init__(self, *, download_root: Path) -> None:
        super().__init__()
        self.download_root = download_root
        self.remote_options, message = fetch_searchlight_options()
        self.catalog = build_catalog(download_root, self.remote_options)
        self.catalog.source_message = message
        self.filter_rows: list[FilterRow] = []
        self.last_result_curves: list[Spectrum] = []
        self.aoi_result_curves: list[Spectrum] = []
        self.aoi_comparison_curves: dict[str, list[Spectrum]] = {}
        self.aoi_comparison_titles: dict[str, str] = {}
        self.aoi_filter_plots: dict[str, SpectraPlot] = {}
        self.aoi_filter_ranges: dict[str, tuple[int, int]] = {}
        self.aoi_auc_filter_names: list[str] = []
        self.aoi_auc_filter_entries: list[tuple[str, str]] = []
        self.aoi_auc_widgets: dict[str, tuple[Panel, QTableWidget, AoiAreaPlot]] = {}
        self.aoi_heatmap_filter_data: dict[str, dict] = {}
        self.unknown_online_queries: set[tuple[str, str]] = set()
        self.status_buffers: dict[QLabel, list[str]] = {}
        self.explorer_result_visible = False
        self.aoi_analysis_visible = False

        self.setWindowTitle("Dichroly")
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._refresh_live_plot()
        self._refresh_result_plot()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        logo = QLabel("Dichroly")
        logo.setObjectName("Logo")
        header.addWidget(logo)
        header.addStretch(1)
        save_inputs = QPushButton("Save inputs")
        save_inputs.clicked.connect(self._save_inputs)
        load_inputs = QPushButton("Load inputs")
        load_inputs.clicked.connect(self._load_inputs)
        header.addWidget(save_inputs)
        header.addWidget(load_inputs)
        layout.addLayout(header)

        self.global_status_label = QLabel("")
        self.global_status_label.setObjectName("Warning")
        self.global_status_label.setWordWrap(True)
        self.global_status_label.setFixedHeight(34)
        self.global_status_label.setMinimumWidth(460)
        self.global_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.warning_label = self.global_status_label
        self.aoi_warning_label = self.global_status_label

        tabs = QTabWidget()
        tabs.tabBar().setExpanding(True)
        tabs.addTab(self._build_explorer_tab(), "Explorer")
        tabs.addTab(self._build_aoi_tab(), "AOI Analysis")
        tabs.addTab(self._build_download_tab(), "Downloads")
        layout.addWidget(tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.global_status_label)
        layout.addLayout(footer)
        self.setCentralWidget(root)

    def _build_explorer_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        selection_panel = Panel()
        selection_layout = QVBoxLayout(selection_panel)
        selection_layout.setContentsMargins(16, 16, 16, 16)
        selection_layout.setSpacing(10)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self.light_combo = QComboBox()
        self.light_combo.setEditable(True)
        _populate_source_combo(self.light_combo, self.catalog, "light_sources", placeholder="Uniform illumination")
        self.light_combo.currentTextChanged.connect(lambda _text: self._on_explorer_selection_changed())
        if self.light_combo.lineEdit():
            self.light_combo.lineEdit().returnPressed.connect(lambda: self._on_combo_committed("light_sources", self.light_combo))
        grid.addWidget(_control_group("Light source", self.light_combo), 0, 0)

        self.fluor_combo = QComboBox()
        self.fluor_combo.setEditable(True)
        _populate_source_combo(self.fluor_combo, self.catalog, "fluorophores", placeholder="No fluorophore")
        self.fluor_combo.currentTextChanged.connect(lambda _text: self._on_explorer_selection_changed())
        if self.fluor_combo.lineEdit():
            self.fluor_combo.lineEdit().returnPressed.connect(lambda: self._on_combo_committed("fluorophores", self.fluor_combo))
        grid.addWidget(_control_group("Fluorophore", self.fluor_combo), 0, 1)
        selection_layout.addLayout(grid)

        filter_header = QHBoxLayout()
        filter_header.addWidget(_section_label("Filters"))
        add_filter = QPushButton("Add filter")
        add_filter.clicked.connect(lambda: self._add_filter_row(removable=True))
        filter_header.addWidget(add_filter, alignment=Qt.AlignRight)
        selection_layout.addLayout(filter_header)
        self.filter_rows_layout = QVBoxLayout()
        selection_layout.addLayout(self.filter_rows_layout)
        self.plot_start = _range_edit("300", width=48)
        self.plot_start.editingFinished.connect(self._on_explorer_plot_range_changed)
        self.plot_end = _range_edit("900", width=48)
        self.plot_end.editingFinished.connect(self._on_explorer_plot_range_changed)
        self.y_min = _range_edit("0", width=42)
        self.y_min.editingFinished.connect(self._on_explorer_plot_range_changed)
        self.y_max = _range_edit("1", width=42)
        self.y_max.editingFinished.connect(self._on_explorer_plot_range_changed)
        self.auc_percent_min = _range_edit("0", width=42)
        self.auc_percent_min.editingFinished.connect(self._on_explorer_plot_range_changed)
        self.auc_percent_max = _range_edit("100", width=42)
        self.auc_percent_max.editingFinished.connect(self._on_explorer_plot_range_changed)
        selection_layout.addWidget(
            _plot_range_row(self.plot_start, self.plot_end, self.y_min, self.y_max, self.auc_percent_min, self.auc_percent_max)
        )
        layout.addWidget(selection_panel)

        result_controls = Panel()
        result_controls.setObjectName("ToolbarPanel")
        result_controls_layout = QHBoxLayout(result_controls)
        result_controls_layout.setContentsMargins(12, 8, 12, 8)
        result_controls_layout.setSpacing(7)
        result_controls_layout.addWidget(_section_label("Result"))
        self.show_excitation_check = QCheckBox("Excitation")
        self.show_excitation_check.setObjectName("PlotToggle")
        self.show_excitation_check.setChecked(True)
        self.show_emission_check = QCheckBox("Emission")
        self.show_emission_check.setObjectName("PlotToggle")
        self.show_emission_check.setChecked(True)
        self.show_light_source_check = QCheckBox("Light source")
        self.show_light_source_check.setObjectName("PlotToggle")
        self.show_light_source_check.setChecked(True)
        self.show_excitation_check.toggled.connect(self._refresh_result_plot)
        self.show_emission_check.toggled.connect(self._refresh_result_plot)
        self.show_light_source_check.toggled.connect(self._refresh_result_plot)
        result_controls_layout.addWidget(self.show_excitation_check)
        result_controls_layout.addWidget(self.show_emission_check)
        result_controls_layout.addWidget(self.show_light_source_check)
        result_controls_layout.addStretch(1)

        self.live_plot = SpectraPlot()
        self.result_plot = SpectraPlot()

        calculate_row = QHBoxLayout()
        calculate = QPushButton("Calculate")
        calculate.setObjectName("Primary")
        calculate.setMinimumSize(128, 38)
        calculate.clicked.connect(self._calculate)
        calculate_row.addWidget(calculate)
        calculate_row.addStretch(1)
        layout.addLayout(calculate_row)
        layout.addSpacing(8)
        layout.addWidget(_divider())
        layout.addSpacing(8)

        layout.addWidget(self.live_plot.widget())
        self.explorer_result_divider_top = _divider()
        layout.addSpacing(8)
        layout.addWidget(self.explorer_result_divider_top)
        layout.addSpacing(8)
        self.explorer_result_controls = result_controls
        layout.addWidget(result_controls)
        self.explorer_result_widget = self.result_plot.widget()
        layout.addWidget(self.explorer_result_widget)
        layout.addStretch(1)
        self._add_filter_row(removable=True)
        self._set_explorer_result_visible(False)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _build_aoi_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        selection_panel = Panel()
        selection_layout = QVBoxLayout(selection_panel)
        selection_layout.setContentsMargins(16, 16, 16, 16)
        selection_layout.setSpacing(10)
        selection_layout.addWidget(_section_label("Light source"))
        self.aoi_light_rows_layout = QVBoxLayout()
        selection_layout.addLayout(self.aoi_light_rows_layout)
        selection_layout.addWidget(_section_label("Fluorophore"))
        self.aoi_fluor_rows_layout = QVBoxLayout()
        selection_layout.addLayout(self.aoi_fluor_rows_layout)
        selection_layout.addWidget(_section_label("Filters"))
        self.aoi_filter_rows_layout = QVBoxLayout()
        selection_layout.addLayout(self.aoi_filter_rows_layout)
        self.aoi_plot_start = _range_edit("300", width=48)
        self.aoi_plot_start.editingFinished.connect(self._on_aoi_plot_range_changed)
        self.aoi_plot_end = _range_edit("900", width=48)
        self.aoi_plot_end.editingFinished.connect(self._on_aoi_plot_range_changed)
        self.aoi_y_min = _range_edit("0", width=42)
        self.aoi_y_min.editingFinished.connect(self._on_aoi_plot_range_changed)
        self.aoi_y_max = _range_edit("1", width=42)
        self.aoi_y_max.editingFinished.connect(self._on_aoi_plot_range_changed)
        self.aoi_auc_percent_min = _range_edit("0", width=42)
        self.aoi_auc_percent_min.editingFinished.connect(self._on_aoi_plot_range_changed)
        self.aoi_auc_percent_max = _range_edit("100", width=42)
        self.aoi_auc_percent_max.editingFinished.connect(self._on_aoi_plot_range_changed)
        selection_layout.addWidget(
            _plot_range_row(
                self.aoi_plot_start,
                self.aoi_plot_end,
                self.aoi_y_min,
                self.aoi_y_max,
                self.aoi_auc_percent_min,
                self.aoi_auc_percent_max,
            )
        )

        aoi_result_controls = Panel()
        aoi_result_controls.setObjectName("ToolbarPanel")
        aoi_result_controls_layout = QHBoxLayout(aoi_result_controls)
        aoi_result_controls_layout.setContentsMargins(12, 8, 12, 8)
        aoi_result_controls_layout.setSpacing(7)
        aoi_result_controls_layout.addWidget(_section_label("Result"))
        self.aoi_show_excitation_check = QRadioButton("Excitation")
        self.aoi_show_excitation_check.setObjectName("PlotToggle")
        self.aoi_show_emission_check = QRadioButton("Emission")
        self.aoi_show_emission_check.setObjectName("PlotToggle")
        self.aoi_show_light_source_check = QRadioButton("Light source")
        self.aoi_show_light_source_check.setObjectName("PlotToggle")
        self.aoi_show_emission_check.setChecked(True)
        self.aoi_show_excitation_check.toggled.connect(self._refresh_aoi_result_plot)
        self.aoi_show_emission_check.toggled.connect(self._refresh_aoi_result_plot)
        self.aoi_show_light_source_check.toggled.connect(self._refresh_aoi_result_plot)
        aoi_result_controls_layout.addWidget(self.aoi_show_excitation_check)
        aoi_result_controls_layout.addWidget(self.aoi_show_emission_check)
        aoi_result_controls_layout.addWidget(self.aoi_show_light_source_check)
        aoi_result_controls_layout.addStretch(1)
        self.aoi_result_controls = aoi_result_controls
        selection_layout.addWidget(aoi_result_controls)

        heatmap_options = Panel()
        heatmap_options.setObjectName("InlinePanel")
        heatmap_options_layout = QVBoxLayout(heatmap_options)
        heatmap_options_layout.setContentsMargins(12, 10, 12, 10)
        heatmap_options_layout.setSpacing(8)
        heatmap_header = QHBoxLayout()
        heatmap_header.addWidget(_section_label("Heatmap"))
        add_heatmap = QPushButton("Add heatmap")
        add_heatmap.clicked.connect(self._add_aoi_heatmap_set)
        heatmap_header.addWidget(add_heatmap, alignment=Qt.AlignRight)
        heatmap_options_layout.addLayout(heatmap_header)
        self.aoi_heatmap_sets: list[HeatmapSet] = []
        self.aoi_heatmap_controls_layout = QVBoxLayout()
        self.aoi_heatmap_controls_layout.setSpacing(7)
        heatmap_options_layout.addLayout(self.aoi_heatmap_controls_layout)
        selection_layout.addWidget(heatmap_options)
        layout.addWidget(selection_panel)

        run_row = QHBoxLayout()
        run = QPushButton("Run analysis")
        run.setObjectName("Primary")
        run.setMinimumSize(128, 38)
        run.clicked.connect(self._run_aoi_analysis)
        run_row.addWidget(run)
        run_row.addStretch(1)
        layout.addLayout(run_row)
        layout.addSpacing(8)
        layout.addWidget(_divider())
        layout.addSpacing(8)

        self.aoi_plots_container = QWidget()
        self.aoi_plots_layout = QVBoxLayout(self.aoi_plots_container)
        self.aoi_plots_layout.setContentsMargins(0, 0, 0, 0)
        self.aoi_plots_layout.setSpacing(14)
        layout.addWidget(self.aoi_plots_container)
        self.aoi_result_divider_top = _divider()
        layout.addSpacing(8)
        layout.addWidget(self.aoi_result_divider_top)
        layout.addSpacing(8)

        self.aoi_result_plot = SpectraPlot()
        self.aoi_result_widget = self.aoi_result_plot.widget()
        layout.addWidget(self.aoi_result_widget)
        self.aoi_area_divider_top = _divider()
        layout.addSpacing(8)
        layout.addWidget(self.aoi_area_divider_top)
        layout.addSpacing(8)

        self.aoi_area_panel = QWidget()
        self.aoi_area_layout = QVBoxLayout(self.aoi_area_panel)
        self.aoi_area_layout.setContentsMargins(0, 0, 0, 0)
        self.aoi_area_layout.setSpacing(14)
        layout.addWidget(self.aoi_area_panel)
        self.aoi_heatmap_divider_top = _divider()
        layout.addSpacing(8)
        layout.addWidget(self.aoi_heatmap_divider_top)
        layout.addSpacing(8)

        self.aoi_heatmap_panel = Panel()
        heatmap_layout = QVBoxLayout(self.aoi_heatmap_panel)
        heatmap_layout.setContentsMargins(12, 12, 12, 12)
        heatmap_layout.setSpacing(12)
        heatmap_layout.addWidget(_section_label("Filter heatmap"))
        self.aoi_heatmap_body_layout = QGridLayout()
        self.aoi_heatmap_body_layout.setHorizontalSpacing(18)
        self.aoi_heatmap_body_layout.setVerticalSpacing(18)
        self.aoi_heatmap_body_layout.setColumnStretch(0, 1)
        self.aoi_heatmap_body_layout.setColumnStretch(1, 1)
        heatmap_layout.addLayout(self.aoi_heatmap_body_layout)
        layout.addWidget(self.aoi_heatmap_panel)
        layout.addStretch(1)
        self._add_aoi_heatmap_set()
        self._sync_aoi_selection_mirror()
        self._refresh_aoi_plots()
        self._resize_aoi_auc_summary()
        self._set_aoi_analysis_visible(False)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _build_download_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        panel = Panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        panel_layout.addWidget(_section_label("Filter"))
        self.download_filter_combo = QComboBox()
        self.download_filter_combo.setEditable(True)
        _populate_source_combo(self.download_filter_combo, self.catalog, "filters", placeholder="")
        panel_layout.addWidget(self.download_filter_combo)

        range_layout = QHBoxLayout()
        range_layout.setSpacing(7)
        range_layout.addWidget(_section_label("AOI range"))
        self.download_aoi_start = _range_edit("0", width=48)
        self.download_aoi_end = _range_edit("30", width=48)
        self.download_aoi_step = _range_edit("5", width=48)
        range_layout.addWidget(QLabel("Start"))
        range_layout.addWidget(self.download_aoi_start)
        range_layout.addWidget(QLabel("End"))
        range_layout.addWidget(self.download_aoi_end)
        range_layout.addWidget(QLabel("Step"))
        range_layout.addWidget(self.download_aoi_step)
        range_layout.addStretch(1)
        panel_layout.addLayout(range_layout)

        layout.addWidget(panel)

        download_row = QHBoxLayout()
        download_button = QPushButton("Download filter")
        download_button.setObjectName("Primary")
        download_button.setMinimumSize(140, 38)
        download_button.clicked.connect(self._download_filter_aoi_range)
        download_row.addWidget(download_button)
        download_row.addStretch(1)
        layout.addLayout(download_row)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _add_filter_row(self, *, removable: bool) -> None:
        row = FilterRow([], removable=removable)
        _populate_source_combo(row.filter_combo, self.catalog, "filters", placeholder="")
        row.committed.connect(lambda combo=row.filter_combo: self._on_combo_committed("filters", combo))
        row.changed.connect(lambda: self._on_filter_row_changed(allow_download=False))
        row.committed.connect(lambda: self._on_filter_row_changed(allow_download=True))
        row.aoi_changed.connect(lambda: self._on_explorer_selection_changed(allow_download=False))
        row.aoi_committed.connect(lambda: self._on_filter_row_changed(allow_download=True))
        row.removed.connect(self._remove_filter_row)
        self.filter_rows.append(row)
        self.filter_rows_layout.addWidget(row)
        self._on_filter_row_changed(allow_download=False)

    def _remove_filter_row(self, row: FilterRow) -> None:
        self.filter_rows.remove(row)
        row.deleteLater()
        self._on_explorer_selection_changed(allow_download=False)

    def _on_filter_row_changed(self, *, allow_download: bool = True) -> None:
        for row in self.filter_rows:
            item = self.catalog.find("filters", row.selected_filter())
            if item:
                row.set_default_aoi(item.name, item.default_aoi)
        self._on_explorer_selection_changed(allow_download=allow_download)

    def _on_explorer_selection_changed(self, *, allow_download: bool = True) -> None:
        self._set_explorer_result_visible(False)
        self._set_aoi_analysis_visible(False)
        self._refresh_live_plot(allow_download=allow_download)
        self._sync_aoi_selection_mirror()

    def _on_combo_committed(self, category_key: str, combo: QComboBox) -> None:
        text = combo.currentText().strip()
        if not text or text in {"Uniform illumination", "No fluorophore"}:
            return
        if self.catalog.find(category_key, text):
            return
        query_key = (category_key, _canonical_lookup_key(text))
        if query_key in self.unknown_online_queries:
            self._set_status(self.warning_label, [f"{text} is not available locally or on SearchLight."])
            return

        self._set_status(self.warning_label, [f"Searching SearchLight for {text}. Please wait."])
        QApplication.processEvents()
        remote_options, message = fetch_searchlight_options()
        if remote_options:
            self.remote_options = _merge_remote_options(self.remote_options, remote_options)
            self.catalog = build_catalog(self.download_root, self.remote_options)
            self._refresh_catalog_choices()
        else:
            self._set_status(self.warning_label, [f"{text} is not in the local/preloaded list. {message}"])
            return
        if self.catalog.find(category_key, text):
            self._set_status(self.warning_label, [message])
            combo.setCurrentText(self.catalog.find(category_key, text).name)
            return

        self.unknown_online_queries.add(query_key)
        self._set_status(self.warning_label, [f"{text} is not available locally or on SearchLight."])

    def _sync_aoi_selection_mirror(self) -> None:
        if not hasattr(self, "aoi_filter_rows_layout"):
            return

        _clear_layout(self.aoi_light_rows_layout)
        light_name = self.light_combo.currentText().strip() or "Uniform illumination"
        light_item = self.catalog.find("light_sources", light_name)
        self.aoi_light_rows_layout.addWidget(_mirror_row(light_name, source_item=light_item))

        _clear_layout(self.aoi_fluor_rows_layout)
        fluor_name = self.fluor_combo.currentText().strip() or "No fluorophore"
        fluor_item = self.catalog.find("fluorophores", fluor_name)
        self.aoi_fluor_rows_layout.addWidget(_mirror_row(fluor_name, source_item=fluor_item))

        _clear_layout(self.aoi_filter_rows_layout)
        mirrored = False
        active_filter_keys = set()
        for row in self.filter_rows:
            name = row.selected_filter()
            if not name:
                continue
            mirrored = True
            key = _row_key(row)
            active_filter_keys.add(key)
            self.aoi_filter_rows_layout.addWidget(self._aoi_filter_control_row(row, key))
        for key in list(self.aoi_filter_ranges):
            if key not in active_filter_keys:
                self.aoi_filter_ranges.pop(key, None)
        if not mirrored:
            self.aoi_filter_rows_layout.addWidget(QLabel("No filters selected"))
        self._sync_aoi_heatmap_filter_choices()
        self._sync_aoi_comparison_plots()
        self._refresh_aoi_plots()

    def _sync_aoi_heatmap_filter_choices(self) -> None:
        if not hasattr(self, "aoi_heatmap_sets"):
            return
        rows = _included_filter_rows(self.filter_rows)
        choices = [(_row_key(row), f"{row.selected_filter()} ({row.selected_mode()})") for row in rows]
        for index, heatmap in enumerate(self.aoi_heatmap_sets):
            preferred_x = index * 2
            preferred_y = index * 2 + 1
            _populate_key_combo(heatmap.x_combo, choices, preferred_index=preferred_x)
            _populate_key_combo(heatmap.y_combo, choices, preferred_index=preferred_y, avoid_key=heatmap.x_combo.currentData())
        self._refresh_aoi_heatmap()

    def _add_aoi_heatmap_set(self) -> None:
        if not hasattr(self, "aoi_heatmap_controls_layout") or not hasattr(self, "aoi_heatmap_body_layout"):
            return
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)

        row_layout = QHBoxLayout()
        row_layout.setSpacing(7)
        title_label = QLabel("Filter heatmap")
        row_layout.addWidget(title_label)
        x_combo = QComboBox()
        x_combo.setFixedWidth(300)
        y_combo = QComboBox()
        y_combo.setFixedWidth(300)
        x_combo.currentIndexChanged.connect(lambda _index: self._refresh_aoi_heatmap())
        y_combo.currentIndexChanged.connect(lambda _index: self._refresh_aoi_heatmap())
        row_layout.addWidget(QLabel("X"))
        row_layout.addWidget(x_combo)
        row_layout.addWidget(QLabel("Y"))
        row_layout.addWidget(y_combo)
        remove_button = QPushButton("Remove")
        remove_button.setObjectName("Danger")
        remove_button.setFixedWidth(78)
        row_layout.addStretch(1)
        row_layout.addWidget(remove_button)
        control_layout.addLayout(row_layout)

        range_layout = QHBoxLayout()
        range_layout.setSpacing(7)
        percent_min = _range_edit("0", width=42)
        percent_max = _range_edit("100", width=42)
        auto_percent_check = QCheckBox("Auto plot")
        auto_percent_check.setChecked(True)
        for edit in (percent_min, percent_max):
            edit.editingFinished.connect(self._refresh_aoi_heatmap)
        auto_percent_check.toggled.connect(lambda _checked: self._on_heatmap_auto_percent_changed())
        range_layout.addWidget(auto_percent_check)
        range_layout.addSpacing(14)
        range_layout.addWidget(QLabel("Plot %"))
        range_layout.addWidget(percent_min)
        range_layout.addWidget(QLabel("to"))
        range_layout.addWidget(percent_max)
        range_layout.addStretch(1)
        control_layout.addLayout(range_layout)
        self.aoi_heatmap_controls_layout.addWidget(control_widget)
        percent_min.setEnabled(False)
        percent_max.setEnabled(False)

        slot = QWidget()
        slot_layout = QVBoxLayout(slot)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        slot_layout.setSpacing(8)
        plot = AoiHeatmapPlot()
        slot_layout.addWidget(plot.widget(), alignment=Qt.AlignHCenter)
        heatmap = HeatmapSet(
            title_label=title_label,
            control_widget=control_widget,
            plot_widget=slot,
            x_combo=x_combo,
            y_combo=y_combo,
            percent_min=percent_min,
            percent_max=percent_max,
            auto_percent_check=auto_percent_check,
            plot=plot,
        )
        remove_button.clicked.connect(lambda _checked=False, item=heatmap: self._remove_aoi_heatmap_set(item))
        self.aoi_heatmap_sets.append(heatmap)
        self._reflow_aoi_heatmap_plots()
        self._sync_aoi_heatmap_filter_choices()

    def _remove_aoi_heatmap_set(self, heatmap: HeatmapSet) -> None:
        if heatmap not in self.aoi_heatmap_sets:
            return
        self.aoi_heatmap_sets.remove(heatmap)
        self.aoi_heatmap_controls_layout.removeWidget(heatmap.control_widget)
        self.aoi_heatmap_body_layout.removeWidget(heatmap.plot_widget)
        heatmap.control_widget.deleteLater()
        heatmap.plot_widget.deleteLater()
        self._renumber_aoi_heatmaps()
        self._reflow_aoi_heatmap_plots()
        self._refresh_aoi_heatmap()

    def _renumber_aoi_heatmaps(self) -> None:
        for heatmap in self.aoi_heatmap_sets:
            heatmap.title_label.setText("Filter heatmap")

    def _reflow_aoi_heatmap_plots(self) -> None:
        for index, heatmap in enumerate(self.aoi_heatmap_sets):
            self.aoi_heatmap_body_layout.removeWidget(heatmap.plot_widget)
            self.aoi_heatmap_body_layout.addWidget(heatmap.plot_widget, index // 2, index % 2)

    def _on_heatmap_auto_percent_changed(self) -> None:
        for heatmap in self.aoi_heatmap_sets:
            manual = not heatmap.auto_percent_check.isChecked()
            heatmap.percent_min.setEnabled(manual)
            heatmap.percent_max.setEnabled(manual)
        self._refresh_aoi_heatmap()

    def _aoi_filter_control_row(self, row: FilterRow, key: str) -> Panel:
        panel = Panel()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        item = self.catalog.find("filters", row.selected_filter())
        layout.addWidget(_source_name_widget(row.selected_filter(), item), 3)
        layout.addWidget(QLabel(row.selected_mode()), 1)
        layout.addWidget(QLabel(f"AOI {row.selected_aoi()} deg"), 1)
        layout.addWidget(QLabel("+/-"))
        span_value, step_value = self.aoi_filter_ranges.get(key, (15, 5))
        span = _range_edit(str(span_value), width=42)
        step = _range_edit(str(step_value), width=42)
        span.editingFinished.connect(lambda edit=span, row_key=key: self._set_aoi_filter_span(row_key, _bounded_int_edit_value(edit, 15, 0, 89)))
        step.editingFinished.connect(lambda edit=step, row_key=key: self._set_aoi_filter_step(row_key, _bounded_int_edit_value(edit, 5, 1, 30)))
        self.aoi_filter_ranges[key] = (span_value, step_value)
        layout.addWidget(span)
        layout.addWidget(QLabel("Step"))
        layout.addWidget(step)
        return panel

    def _set_aoi_filter_span(self, key: str, value: int) -> None:
        _old_span, step = self.aoi_filter_ranges.get(key, (15, 5))
        self.aoi_filter_ranges[key] = (value, step)
        self._set_aoi_analysis_visible(False)
        self._refresh_aoi_titles()

    def _set_aoi_filter_step(self, key: str, value: int) -> None:
        span, _old_step = self.aoi_filter_ranges.get(key, (15, 5))
        self.aoi_filter_ranges[key] = (span, value)
        self._set_aoi_analysis_visible(False)
        self._refresh_aoi_titles()

    def _refresh_aoi_titles(self) -> None:
        self._sync_aoi_comparison_plots()
        self._refresh_aoi_plots()

    def _sync_aoi_comparison_plots(self) -> None:
        if not hasattr(self, "aoi_plots_layout"):
            return
        active: dict[str, str] = {}
        for row in self.filter_rows:
            name = row.selected_filter()
            if not name or row.selected_mode() in {"excluded", "visualize"}:
                continue
            key = _row_key(row)
            span, step = self._aoi_range_for_row(row)
            active[key] = f"AOI comparison: {name} {row.selected_mode()} around {row.selected_aoi()} deg (+/- {span}, step {step})"

        for key in list(self.aoi_filter_plots):
            if key in active:
                continue
            plot = self.aoi_filter_plots.pop(key)
            widget = plot.widget()
            self.aoi_plots_layout.removeWidget(widget)
            widget.deleteLater()
            self.aoi_comparison_curves.pop(key, None)
            self.aoi_comparison_titles.pop(key, None)

        for key, title in active.items():
            if self.aoi_comparison_titles.get(key) != title:
                self.aoi_comparison_curves.pop(key, None)
            self.aoi_comparison_titles[key] = title
            if key in self.aoi_filter_plots:
                continue
            plot = SpectraPlot()
            self.aoi_filter_plots[key] = plot
            self.aoi_plots_layout.addWidget(plot.widget())

    def _refresh_live_plot(self, *, allow_download: bool = True) -> None:
        if not hasattr(self, "warning_label") or not hasattr(self, "live_plot"):
            return
        warnings: list[str] = []
        curves = []
        lights = self._load_selected_lights(warnings)
        curves.extend(lights)
        fluor = self._load_selected_fluorophore(warnings)
        if fluor:
            if fluor.excitation:
                curves.append(fluor.excitation)
            if fluor.emission:
                curves.append(fluor.emission)
        for selected in self._selected_filters(warnings, allow_download=allow_download, include_visualize=True):
            if selected.mode == "excluded":
                continue
            if selected.spectra:
                curve, assumption = filter_curve_for_mode(selected.spectra, selected.mode)
                if curve:
                    curves.append(
                        Spectrum(
                            f"{selected.name} {selected.mode} AOI {selected.aoi_label}",
                            curve.wavelengths,
                            curve.values,
                            "filter_visualize" if selected.mode == "visualize" else curve.kind,
                            curve.source_path,
                            curve.assumptions,
                        )
                    )
                if assumption:
                    warnings.append(assumption)
        self._set_status(self.warning_label, warnings)
        self.live_plot.plot(curves, title="Selected filters", x_range=self._plot_range(), y_range=self._y_range())

    def _calculate(self) -> None:
        warnings: list[str] = []
        result = calculate_spectral_result(
            light_source=self._load_selected_lights(warnings),
            filters=self._selected_filters(warnings),
            fluorophore=self._load_selected_fluorophore(warnings),
        )
        all_warnings = list(dict.fromkeys(warnings + result.warnings))
        self._set_status(self.warning_label, all_warnings)
        self.last_result_curves = result.final_curves
        self._set_explorer_result_visible(True)
        self._refresh_result_plot()

    def _refresh_result_plot(self) -> None:
        if not hasattr(self, "result_plot"):
            return
        visible_curves = []
        for curve in self.last_result_curves:
            if curve.kind == "result_excitation" and not self.show_excitation_check.isChecked():
                continue
            if curve.kind == "result_emission" and not self.show_emission_check.isChecked():
                continue
            if curve.kind == "result_light_source" and not self.show_light_source_check.isChecked():
                continue
            visible_curves.append(curve)
        visible_curves.extend(self._light_source_reference_curves())
        visible_curves.extend(self._fluorophore_reference_curves())
        self.result_plot.plot(
            visible_curves,
            title="Result",
            x_range=self._plot_range(),
            y_range=self._y_range(),
            peak_result_colors=True,
        )

    def _refresh_explorer_plots(self) -> None:
        self._sync_aoi_plot_range_from_explorer()
        self._refresh_live_plot()
        self._refresh_result_plot()
        self._refresh_aoi_plots()
        self._refresh_aoi_heatmap()

    def _set_explorer_result_visible(self, visible: bool) -> None:
        self.explorer_result_visible = visible
        for attr in ("explorer_result_divider_top", "explorer_result_controls", "explorer_result_widget"):
            if hasattr(self, attr):
                getattr(self, attr).setVisible(visible)

    def _set_aoi_analysis_visible(self, visible: bool) -> None:
        self.aoi_analysis_visible = visible
        for attr in (
            "aoi_plots_container",
            "aoi_result_divider_top",
            "aoi_result_widget",
            "aoi_area_divider_top",
            "aoi_area_panel",
            "aoi_heatmap_divider_top",
            "aoi_heatmap_panel",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setVisible(visible)

    def _on_explorer_plot_range_changed(self) -> None:
        self._sync_aoi_plot_range_from_explorer()
        self._refresh_explorer_plots()

    def _on_aoi_plot_range_changed(self) -> None:
        self._sync_explorer_plot_range_from_aoi()
        self._refresh_explorer_plots()

    def _sync_aoi_plot_range_from_explorer(self) -> None:
        if not hasattr(self, "aoi_plot_start"):
            return
        _copy_range_text(self.plot_start, self.aoi_plot_start)
        _copy_range_text(self.plot_end, self.aoi_plot_end)
        _copy_range_text(self.y_min, self.aoi_y_min)
        _copy_range_text(self.y_max, self.aoi_y_max)
        _copy_range_text(self.auc_percent_min, self.aoi_auc_percent_min)
        _copy_range_text(self.auc_percent_max, self.aoi_auc_percent_max)

    def _sync_explorer_plot_range_from_aoi(self) -> None:
        if not hasattr(self, "aoi_plot_start"):
            return
        _copy_range_text(self.aoi_plot_start, self.plot_start)
        _copy_range_text(self.aoi_plot_end, self.plot_end)
        _copy_range_text(self.aoi_y_min, self.y_min)
        _copy_range_text(self.aoi_y_max, self.y_max)
        _copy_range_text(self.aoi_auc_percent_min, self.auc_percent_min)
        _copy_range_text(self.aoi_auc_percent_max, self.auc_percent_max)

    def _refresh_catalog_choices(self) -> None:
        if hasattr(self, "light_combo"):
            _populate_source_combo(self.light_combo, self.catalog, "light_sources", placeholder="Uniform illumination", preserve_text=True)
        if hasattr(self, "fluor_combo"):
            _populate_source_combo(self.fluor_combo, self.catalog, "fluorophores", placeholder="No fluorophore", preserve_text=True)
        for row in getattr(self, "filter_rows", []):
            _populate_source_combo(row.filter_combo, self.catalog, "filters", placeholder="", preserve_text=True)
        if hasattr(self, "download_filter_combo"):
            _populate_source_combo(self.download_filter_combo, self.catalog, "filters", placeholder="", preserve_text=True)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._resize_aoi_auc_summary()

    def _set_status(self, label: QLabel, messages: list[str]) -> None:
        unique_messages = list(dict.fromkeys(message for message in messages if message))
        if not unique_messages:
            self.status_buffers[label] = []
            label.setText("")
            return
        self.status_buffers[label] = []
        for message in unique_messages:
            self._append_status(label, message)

    def _append_status(self, label: QLabel, message: str) -> None:
        if not message:
            return
        buffer = self.status_buffers.setdefault(label, [])
        if len(buffer) >= 2:
            buffer.clear()
        buffer.append(message)
        label.setText("\n".join(buffer))

    def _plot_range(self) -> tuple[int, int]:
        if not hasattr(self, "plot_start") or not hasattr(self, "plot_end"):
            return (300, 900)
        start = _range_value(self.plot_start, 300)
        end = _range_value(self.plot_end, 900)
        if start == end:
            end = start + 1
        return (min(start, end), max(start, end))

    def _y_range(self) -> tuple[float, float]:
        if not hasattr(self, "y_min") or not hasattr(self, "y_max"):
            return (0.0, 1.0)
        start = _float_range_value(self.y_min, 0.0)
        end = _float_range_value(self.y_max, 1.0)
        if start == end:
            end = start + 1.0
        return (min(start, end), max(start, end))

    def _aoi_plot_range(self) -> tuple[int, int]:
        if not hasattr(self, "aoi_plot_start") or not hasattr(self, "aoi_plot_end"):
            return (300, 900)
        start = _range_value(self.aoi_plot_start, 300)
        end = _range_value(self.aoi_plot_end, 900)
        if start == end:
            end = start + 1
        return (min(start, end), max(start, end))

    def _aoi_y_range(self) -> tuple[float, float]:
        if not hasattr(self, "aoi_y_min") or not hasattr(self, "aoi_y_max"):
            return (0.0, 1.0)
        start = _float_range_value(self.aoi_y_min, 0.0)
        end = _float_range_value(self.aoi_y_max, 1.0)
        if start == end:
            end = start + 1.0
        return (min(start, end), max(start, end))

    def _aoi_auc_percent_range(self) -> tuple[float, float]:
        if not hasattr(self, "aoi_auc_percent_min") or not hasattr(self, "aoi_auc_percent_max"):
            return (0.0, 100.0)
        start = _float_range_value(self.aoi_auc_percent_min, 0.0)
        end = _float_range_value(self.aoi_auc_percent_max, 100.0)
        if start == end:
            end = start + 1.0
        return (min(start, end), max(start, end))

    def _refresh_aoi_plots(self) -> None:
        if hasattr(self, "aoi_filter_plots"):
            reference_curves = self._aoi_reference_curves()
            explorer_filter_colors = self._explorer_filter_colors()
            for key, plot in self.aoi_filter_plots.items():
                plot.plot(
                    self.aoi_comparison_curves.get(key, []) + reference_curves,
                    title=self.aoi_comparison_titles.get(key, "AOI comparison"),
                    x_range=self._aoi_plot_range(),
                    y_range=self._aoi_y_range(),
                    aoi_gradient=True,
                    aoi_gradient_base_color=explorer_filter_colors.get(key, LINE_COLORS[0]),
                )
        self._refresh_aoi_result_plot()

    def _explorer_filter_colors(self) -> dict[str, str]:
        colors: dict[str, str] = {}
        color_index = 0
        for row in self.filter_rows:
            name = row.selected_filter()
            mode = row.selected_mode()
            if not name or mode == "excluded":
                continue
            key = _row_key(row)
            if mode == "visualize":
                colors[key] = VISUALIZE_FILTER_COLOR
                continue
            colors[key] = LINE_COLORS[color_index % len(LINE_COLORS)]
            color_index += 1
        return colors

    def _aoi_reference_curves(self) -> list[Spectrum]:
        curves = []
        curves.extend(self._aoi_visualize_filter_curves())
        curves.extend(self._light_source_reference_curves())
        curves.extend(self._fluorophore_reference_curves())
        return curves

    def _light_source_reference_curves(self) -> list[Spectrum]:
        name = self.light_combo.currentText().strip()
        if not name or name == "Uniform illumination":
            return []
        item = self.catalog.find("light_sources", name)
        if not item or not item.local_files:
            return []
        try:
            return [load_light_source(item.local_files[0], name)]
        except Exception:
            return []

    def _fluorophore_reference_curves(self) -> list[Spectrum]:
        curves = []
        fluorophore = self._load_selected_fluorophore_local()
        if fluorophore is None:
            return curves
        if fluorophore.excitation:
            curves.append(fluorophore.excitation)
        if fluorophore.emission:
            curves.append(fluorophore.emission)
        return curves

    def _aoi_visualize_filter_curves(
        self,
        warnings: list[str] | None = None,
        *,
        allow_download: bool = False,
    ) -> list[Spectrum]:
        curves: list[Spectrum] = []
        for row in self.filter_rows:
            name = row.selected_filter()
            if not name or row.selected_mode() != "visualize":
                continue
            aoi = row.selected_aoi()
            item = self.catalog.find("filters", name)
            path = _choose_filter_file(item.local_files, aoi) if item and item.local_files else None
            if path is None:
                if allow_download and warnings is not None:
                    path = self._download_missing_filter(name, aoi, warnings, status_label=self.aoi_warning_label)
                if path is None:
                    continue
            spectra = load_filter(path, name=name, aoi=aoi)
            curve, assumption = filter_curve_for_mode(spectra, "visualize")
            if curve is None:
                if warnings is not None:
                    warnings.append(f"{name}: AOI {aoi} deg has no usable visualization curve.")
                continue
            if assumption and warnings is not None:
                warnings.append(assumption)
            curves.append(
                Spectrum(
                    _filter_aoi_label(name, aoi),
                    curve.wavelengths,
                    curve.values,
                    "filter_visualize",
                    curve.source_path,
                    curve.assumptions,
                )
            )
        return curves

    def _refresh_aoi_result_plot(self) -> None:
        if not hasattr(self, "aoi_result_plot"):
            return
        visible_curves = self._visible_aoi_result_curves()
        visible_curves.extend(self._light_source_reference_curves())
        visible_curves.extend(self._fluorophore_reference_curves())
        self.aoi_result_plot.plot(
            visible_curves,
            title="Result",
            x_range=self._aoi_plot_range(),
            y_range=self._aoi_y_range(),
        )
        self._refresh_aoi_auc_summary(visible_curves)

    def _visible_aoi_result_curves(self) -> list[Spectrum]:
        visible_curves = []
        for curve in self.aoi_result_curves:
            if curve.kind == "result_excitation" and not self.aoi_show_excitation_check.isChecked():
                continue
            if curve.kind == "result_emission" and not self.aoi_show_emission_check.isChecked():
                continue
            if curve.kind == "result_light_source" and not self.aoi_show_light_source_check.isChecked():
                continue
            visible_curves.append(curve)
        return visible_curves

    def _refresh_aoi_auc_summary(self, curves: list[Spectrum]) -> None:
        if not hasattr(self, "aoi_area_layout"):
            return
        _ = curves
        entries = self.aoi_auc_filter_entries or _included_filter_entries(self.filter_rows)
        self._sync_aoi_auc_widgets(entries)
        self._resize_aoi_auc_summary()
        weight_curve = self._aoi_auc_weight_curve()
        for key, name in entries:
            _panel, table, plot = self.aoi_auc_widgets[key]
            baseline_area = _no_filter_auc(self._aoi_plot_range(), weight_curve)
            rows = _aoi_auc_rows(
                self.aoi_comparison_curves.get(key, []),
                self._aoi_plot_range(),
                baseline_area=baseline_area,
                weight_curve=weight_curve,
            )
            _fill_auc_table(table, rows)
            plot.plot(
                rows,
                title=f"{name} area under curve",
                percent_range=self._aoi_auc_percent_range(),
                percent_denominator=baseline_area,
            )

    def _aoi_auc_weight_curve(self) -> Spectrum | None:
        if self.aoi_show_light_source_check.isChecked():
            return self._load_selected_light_source_local()
        fluorophore = self._load_selected_fluorophore_local()
        if fluorophore is None:
            return None
        if self.aoi_show_excitation_check.isChecked():
            return fluorophore.excitation
        if self.aoi_show_emission_check.isChecked():
            return fluorophore.emission
        return None

    def _sync_aoi_auc_widgets(self, entries: list[tuple[str, str]]) -> None:
        active = {key for key, _name in entries}
        for key in list(self.aoi_auc_widgets):
            if key in active:
                continue
            panel, _table, _plot = self.aoi_auc_widgets.pop(key)
            self.aoi_area_layout.removeWidget(panel)
            panel.deleteLater()
        for key, name in entries:
            if key in self.aoi_auc_widgets:
                continue
            panel, table, plot = _aoi_auc_panel(name)
            self.aoi_auc_widgets[key] = (panel, table, plot)
            self.aoi_area_layout.addWidget(panel)

    def _resize_aoi_auc_summary(self) -> None:
        if not hasattr(self, "aoi_area_panel"):
            return
        width = self.aoi_area_panel.width()
        if width < 600:
            width = max(self.width() - 90, 900)
        table_width = max(220, int(width * 0.40))
        plot_width = max(180, int(width * 0.50))
        for _panel, table, plot in self.aoi_auc_widgets.values():
            table.setFixedWidth(table_width)
            table.setFixedHeight(plot_width)
            plot.set_square_size(plot_width)

    def _aoi_range_for_row(self, row: FilterRow) -> tuple[int, int]:
        return self.aoi_filter_ranges.get(_row_key(row), (15, 5))

    def _save_inputs(self) -> None:
        path_text, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Dichroly inputs",
            str(project_root() / "dichroly_inputs.json"),
            "JSON files (*.json)",
        )
        if not path_text:
            return
        payload = self._input_state()
        try:
            Path(path_text).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._set_status(self.warning_label, [f"Saved inputs to {Path(path_text).name}."])
        except OSError as exc:
            self._set_status(self.warning_label, [f"Could not save inputs: {exc}"])

    def _load_inputs(self) -> None:
        path_text, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load Dichroly inputs",
            str(project_root()),
            "JSON files (*.json)",
        )
        if not path_text:
            return
        try:
            payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._set_status(self.warning_label, [f"Could not load inputs: {exc}"])
            return
        self._apply_input_state(payload)
        self._set_status(self.warning_label, [f"Loaded inputs from {Path(path_text).name}."])

    def _download_filter_aoi_range(self) -> None:
        name = self.download_filter_combo.currentText().strip()
        if not name:
            self._set_status(self.warning_label, ["Select a filter to download."])
            return
        start = _bounded_int_edit_value(self.download_aoi_start, 0, 0, 89)
        end = _bounded_int_edit_value(self.download_aoi_end, 30, 0, 89)
        step = _bounded_int_edit_value(self.download_aoi_step, 5, 1, 30)
        try:
            aoi_values = requested_aoi_values(start, end, step, default_orientation=0)
        except ValueError as exc:
            self._set_status(self.warning_label, [str(exc)])
            return

        warnings: list[str] = []
        downloaded = 0
        for index, aoi in enumerate(aoi_values, start=1):
            self._set_status(
                self.warning_label,
                [f"Downloading {name} AOI {aoi} deg ({index}/{len(aoi_values)}). Please wait."],
            )
            QApplication.processEvents()
            try:
                download_filter_configuration(self.download_root, name, aoi)
            except Exception as exc:
                warnings.append(f"AOI {aoi} deg failed: {exc}")
                continue
            downloaded += 1

        self.download_root = default_data_root()
        self.catalog = build_catalog(self.download_root, self.remote_options)
        self._refresh_catalog_choices()
        summary = f"{name}: downloaded {downloaded}/{len(aoi_values)} AOI file(s)."
        self._set_status(self.warning_label, [summary] + warnings)

    def _input_state(self) -> dict:
        filters = []
        for row in self.filter_rows:
            span, step = self._aoi_range_for_row(row)
            filters.append(
                {
                    "name": row.selected_filter(),
                    "mode": row.selected_mode(),
                    "aoi": row.aoi_edit.text().strip(),
                    "aoi_span": span,
                    "aoi_step": step,
                }
            )
        return {
            "light_source": self.light_combo.currentText(),
            "fluorophore": self.fluor_combo.currentText(),
            "filters": filters,
            "plot_range": {
                "x_start": self.plot_start.text(),
                "x_end": self.plot_end.text(),
                "y_min": self.y_min.text(),
                "y_max": self.y_max.text(),
                "auc_percent_min": self.auc_percent_min.text(),
                "auc_percent_max": self.auc_percent_max.text(),
            },
            "aoi_defaults": {
                "span": 15,
                "step": 5,
            },
            "explorer_result": {
                "excitation": self.show_excitation_check.isChecked(),
                "emission": self.show_emission_check.isChecked(),
                "light_source": self.show_light_source_check.isChecked(),
            },
            "aoi_result": self._aoi_result_mode(),
            "heatmaps": self._heatmap_input_state(),
        }

    def _aoi_result_mode(self) -> str:
        if self.aoi_show_light_source_check.isChecked():
            return "light_source"
        if self.aoi_show_emission_check.isChecked():
            return "emission"
        return "excitation"

    def _apply_input_state(self, payload: dict) -> None:
        _set_combo_catalog_text(
            self.light_combo,
            self.catalog,
            "light_sources",
            str(payload.get("light_source", "Uniform illumination")),
            placeholder="Uniform illumination",
        )
        _set_combo_catalog_text(
            self.fluor_combo,
            self.catalog,
            "fluorophores",
            str(payload.get("fluorophore", "No fluorophore")),
            placeholder="No fluorophore",
        )

        self.filter_rows.clear()
        self.aoi_filter_ranges = {}
        _clear_layout(self.filter_rows_layout)

        filters = payload.get("filters", [])
        if not filters:
            filters = [{"name": "", "mode": "transmission", "aoi": "0"}]
        for saved in filters:
            self._add_filter_row(removable=True)
            row = self.filter_rows[-1]
            _set_combo_catalog_text(
                row.filter_combo,
                self.catalog,
                "filters",
                str(saved.get("name", "")),
                placeholder="",
            )
            row.mode_combo.setCurrentText(str(saved.get("mode", "transmission")))
            row.aoi_edit.setText(str(saved.get("aoi", "0")))
            self.aoi_filter_ranges[_row_key(row)] = (
                int(saved.get("aoi_span", 15)),
                int(saved.get("aoi_step", 5)),
            )

        ranges = payload.get("plot_range", {})
        self.plot_start.setText(str(ranges.get("x_start", "300")))
        self.plot_end.setText(str(ranges.get("x_end", "900")))
        self.y_min.setText(str(ranges.get("y_min", "0")))
        self.y_max.setText(str(ranges.get("y_max", "1")))
        self.auc_percent_min.setText(str(ranges.get("auc_percent_min", "0")))
        self.auc_percent_max.setText(str(ranges.get("auc_percent_max", "100")))
        self._sync_aoi_plot_range_from_explorer()

        explorer_result = payload.get("explorer_result", {})
        self.show_excitation_check.setChecked(bool(explorer_result.get("excitation", True)))
        self.show_emission_check.setChecked(bool(explorer_result.get("emission", True)))
        self.show_light_source_check.setChecked(bool(explorer_result.get("light_source", True)))
        aoi_result = _normalize_aoi_result_mode(payload.get("aoi_result", "emission"))
        if aoi_result == "light_source":
            self.aoi_show_light_source_check.setChecked(True)
        elif aoi_result == "emission":
            self.aoi_show_emission_check.setChecked(True)
        else:
            self.aoi_show_excitation_check.setChecked(True)
        self._on_explorer_selection_changed(allow_download=False)
        self._apply_heatmap_input_state(payload.get("heatmaps", []))
        self._refresh_explorer_plots()

    def _heatmap_input_state(self) -> list[dict]:
        if not hasattr(self, "aoi_heatmap_sets"):
            return []
        included_keys = [key for key, _name in _included_filter_entries(self.filter_rows)]
        heatmaps = []
        for heatmap in self.aoi_heatmap_sets:
            x_key = heatmap.x_combo.currentData()
            y_key = heatmap.y_combo.currentData()
            heatmaps.append(
                {
                    "x_index": included_keys.index(x_key) if x_key in included_keys else 0,
                    "y_index": included_keys.index(y_key) if y_key in included_keys else 1,
                    "auto_percent": heatmap.auto_percent_check.isChecked(),
                    "percent_min": heatmap.percent_min.text(),
                    "percent_max": heatmap.percent_max.text(),
                }
            )
        return heatmaps

    def _apply_heatmap_input_state(self, saved_heatmaps: object) -> None:
        if not hasattr(self, "aoi_heatmap_sets"):
            return
        while self.aoi_heatmap_sets:
            self._remove_aoi_heatmap_set(self.aoi_heatmap_sets[0])
        heatmaps = saved_heatmaps if isinstance(saved_heatmaps, list) and saved_heatmaps else [{}]
        for saved in heatmaps:
            if not isinstance(saved, dict):
                saved = {}
            self._add_aoi_heatmap_set()
            heatmap = self.aoi_heatmap_sets[-1]
            x_index = _safe_int(saved.get("x_index"), 0)
            y_index = _safe_int(saved.get("y_index"), 1)
            if heatmap.x_combo.count():
                heatmap.x_combo.setCurrentIndex(min(max(0, x_index), heatmap.x_combo.count() - 1))
            if heatmap.y_combo.count():
                heatmap.y_combo.setCurrentIndex(min(max(0, y_index), heatmap.y_combo.count() - 1))
            heatmap.auto_percent_check.setChecked(bool(saved.get("auto_percent", True)))
            heatmap.percent_min.setText(str(saved.get("percent_min", "0")))
            heatmap.percent_max.setText(str(saved.get("percent_max", "100")))
        self._on_heatmap_auto_percent_changed()

    def _run_aoi_analysis(self) -> None:
        comparison_curves: dict[str, list[Spectrum]] = {}
        filter_options: list[list[SelectedFilter]] = []
        filter_option_rows: list[FilterRow] = []
        heatmap_filter_data: dict[str, dict] = {}
        warnings: list[str] = []
        selected_rows = _included_filter_rows(self.filter_rows)
        if not selected_rows:
            self.aoi_auc_filter_names = []
            self.aoi_auc_filter_entries = []
            self.aoi_heatmap_filter_data = {}
            self._refresh_aoi_heatmap()
            self._set_status(self.aoi_warning_label, ["Select one or more included filters in Explorer."])
            return
        self.aoi_auc_filter_names = [row.selected_filter() for row in selected_rows]
        self.aoi_auc_filter_entries = [(_row_key(row), row.selected_filter()) for row in selected_rows]

        for row in selected_rows:
            key = _row_key(row)
            name = row.selected_filter()
            mode = row.selected_mode()
            current_aoi = row.selected_aoi() or 0
            span, step = self._aoi_range_for_row(row)
            comparison_curves[key] = []
            self.aoi_comparison_titles[key] = f"AOI comparison: {name} {mode} around {current_aoi} deg (+/- {span}, step {step})"
            item = self.catalog.find("filters", name)
            if item is None:
                warnings.append(f"{name} is not in the SearchLight filter catalog.")
                continue
            try:
                aoi_values = requested_relative_aoi_values(current_aoi, span, step)
            except ValueError as exc:
                warnings.append(str(exc))
                continue
            spectra_by_aoi: dict[int, object] = {}
            options_for_filter: list[SelectedFilter] = []
            heatmap_curves: dict[int, Spectrum] = {}
            for aoi in aoi_values:
                item = self.catalog.find("filters", name)
                path = _choose_filter_file(item.local_files, aoi) if item and item.local_files else None
                if path is None:
                    path = self._download_missing_filter(name, aoi, warnings, status_label=self.aoi_warning_label)
                    if path is None:
                        continue
                spectra = load_filter(path, name=name, aoi=aoi)
                spectra_by_aoi[aoi] = spectra
                curve, assumption = filter_curve_for_mode(spectra, mode)
                if curve is None:
                    warnings.append(f"{name}: AOI {aoi} deg has no usable {mode} curve.")
                    continue
                if assumption:
                    warnings.append(assumption)
                heatmap_curves[aoi] = Spectrum(
                    _filter_aoi_label(name, aoi, current_aoi),
                    curve.wavelengths,
                    curve.values,
                    curve.kind,
                    curve.source_path,
                    curve.assumptions,
                )
                comparison_curves[key].append(
                    Spectrum(
                        _filter_aoi_label(name, aoi, current_aoi),
                        curve.wavelengths,
                        curve.values,
                        curve.kind,
                        curve.source_path,
                        curve.assumptions,
                    )
                )
            for aoi in aoi_values:
                spectra = spectra_by_aoi.get(aoi)
                if spectra is not None:
                    options_for_filter.append(SelectedFilter(name, spectra, mode, aoi))
            if options_for_filter:
                filter_options.append(options_for_filter)
                filter_option_rows.append(row)
            if heatmap_curves:
                heatmap_filter_data[key] = {
                    "name": name,
                    "mode": mode,
                    "aoi_values": list(heatmap_curves),
                    "curves": heatmap_curves,
                }
        self.aoi_comparison_curves = comparison_curves
        self.aoi_heatmap_filter_data = heatmap_filter_data
        self._aoi_visualize_filter_curves(warnings, allow_download=True)
        light_sources = self._load_selected_lights(warnings)
        fluorophore = self._load_selected_fluorophore(warnings)
        self.aoi_result_curves = []
        combinations = list(product(*filter_options)) if filter_options else []
        for combo_index, combo in enumerate(combinations, start=1):
            result = calculate_spectral_result(
                light_source=light_sources,
                filters=list(combo),
                fluorophore=fluorophore,
            )
            warnings.extend(result.warnings)
            combo_label = _filter_combo_label(combo, filter_option_rows)
            for curve in result.final_curves:
                self.aoi_result_curves.append(
                    Spectrum(
                        f"{combo_index}: {combo_label}",
                        curve.wavelengths,
                        curve.values,
                        curve.kind,
                        curve.source_path,
                        curve.assumptions,
                    )
                )
        self._set_status(self.aoi_warning_label, list(dict.fromkeys(warnings)))
        self._set_aoi_analysis_visible(True)
        self._refresh_aoi_plots()
        self._refresh_aoi_heatmap()

    def _refresh_aoi_heatmap(self) -> None:
        if not hasattr(self, "aoi_heatmap_sets"):
            return
        for heatmap in self.aoi_heatmap_sets:
            x_key = heatmap.x_combo.currentData()
            y_key = heatmap.y_combo.currentData()
            x_data = self.aoi_heatmap_filter_data.get(x_key)
            y_data = self.aoi_heatmap_filter_data.get(y_key)
            if not x_data or not y_data:
                heatmap.plot.clear()
                continue

            x_values = sorted(x_data["curves"])
            y_values = sorted(y_data["curves"])
            weight_curve = self._aoi_auc_weight_curve()
            baseline_area = _no_filter_auc(self._aoi_plot_range(), weight_curve)
            grid = [
                [
                    _combined_filter_area(
                        x_data["curves"][x_aoi],
                        y_data["curves"][y_aoi],
                        self._aoi_plot_range(),
                        weight_curve,
                    )
                    / baseline_area
                    * 100.0
                    if baseline_area > 0
                    else 0.0
                    for x_aoi in x_values
                ]
                for y_aoi in y_values
            ]
            heatmap.plot.plot(
                x_values,
                y_values,
                grid,
                title="Filter heatmap",
                x_label=f"{x_data['name']} {x_data['mode']} AOI (deg)",
                y_label=f"{y_data['name']} {y_data['mode']} AOI (deg)",
                value_range=self._aoi_heatmap_percent_range(heatmap),
                value_label="% of total area",
            )

    def _aoi_heatmap_percent_range(self, heatmap: HeatmapSet) -> tuple[float, float] | None:
        if heatmap.auto_percent_check.isChecked():
            return None
        start = _float_range_value(heatmap.percent_min, 0.0)
        end = _float_range_value(heatmap.percent_max, 100.0)
        if start == end:
            end = start + 1.0
        return (min(start, end), max(start, end))

    def _load_selected_lights(self, warnings: list[str]):
        name = self.light_combo.currentText().strip()
        if not name or name == "Uniform illumination":
            return []
        item = self.catalog.find("light_sources", name)
        if not item or not item.local_files:
            path = self._download_missing_item("light_sources", name, warnings)
            if path is None:
                return []
            return [load_light_source(path, name)]
        return [load_light_source(item.local_files[0], name)]

    def _load_selected_fluorophore(self, warnings: list[str]):
        name = self.fluor_combo.currentText().strip()
        if not name or name == "No fluorophore":
            return None
        item = self.catalog.find("fluorophores", name)
        if not item or not item.local_files:
            path = self._download_missing_item("fluorophores", name, warnings)
            if path is None:
                return None
            return load_fluorophore(path, name)
        return load_fluorophore(item.local_files[0], name)

    def _load_selected_fluorophore_local(self):
        name = self.fluor_combo.currentText().strip()
        if not name or name == "No fluorophore":
            return None
        item = self.catalog.find("fluorophores", name)
        if not item or not item.local_files:
            return None
        try:
            return load_fluorophore(item.local_files[0], name)
        except Exception:
            return None

    def _load_selected_light_source_local(self) -> Spectrum | None:
        name = self.light_combo.currentText().strip()
        if not name or name == "Uniform illumination":
            return None
        item = self.catalog.find("light_sources", name)
        if not item or not item.local_files:
            return None
        try:
            return load_light_source(item.local_files[0], name)
        except Exception:
            return None

    def _selected_filters(
        self,
        warnings: list[str],
        *,
        allow_download: bool = True,
        include_visualize: bool = False,
    ) -> list[SelectedFilter]:
        selected: list[SelectedFilter] = []
        for row in self.filter_rows:
            name = row.selected_filter()
            if not name:
                continue
            mode = row.selected_mode()
            if mode == "excluded" or (mode == "visualize" and not include_visualize):
                continue
            aoi = row.selected_aoi()
            item = self.catalog.find("filters", name)
            path = _choose_filter_file(item.local_files, aoi) if item and item.local_files else None
            if path is None:
                if not allow_download:
                    warnings.append(f"{name} AOI {aoi} deg is not downloaded yet. Press Enter or leave the AOI field to download it.")
                    selected.append(SelectedFilter(name, None, mode, aoi))
                    continue
                path = self._download_missing_filter(name, aoi, warnings)
                if path is None:
                    selected.append(SelectedFilter(name, None, mode, aoi))
                    continue
            selected.append(SelectedFilter(name, load_filter(path, name=name, aoi=aoi), mode, aoi))
        return selected

    def _download_missing_filter(
        self,
        name: str,
        aoi: int | None,
        warnings: list[str],
        *,
        status_label: QLabel | None = None,
    ) -> Path | None:
        status_label = status_label or self.warning_label
        item = self.catalog.find("filters", name)
        if item is None:
            warnings.append(f"{name} is not in the SearchLight filter catalog.")
            return None
        aoi_label = f"AOI {aoi if aoi is not None else item.default_aoi or 0} deg"
        message = f"{name} {aoi_label} is not downloaded. Downloading it now; please wait."
        warnings.append(message)
        self._set_status(status_label, warnings)
        QApplication.processEvents()
        try:
            path = download_filter_configuration(self.download_root, name, aoi)
        except Exception as exc:
            warnings.append(f"{name}: download failed. {exc}")
            return None
        self.download_root = default_data_root()
        self.catalog = build_catalog(self.download_root, self.remote_options)
        self._refresh_catalog_choices()
        warnings.append(f"{name}: downloaded {aoi_label}.")
        return path

    def _download_missing_item(self, category_key: str, name: str, warnings: list[str]) -> Path | None:
        item = self.catalog.find(category_key, name)
        label = {
            "fluorophores": "fluorophore",
            "light_sources": "light source",
        }[category_key]
        if item is None:
            warnings.append(f"{name} is not in the SearchLight {label} catalog.")
            return None
        message = f"{name} {label} is not downloaded. Downloading it now; please wait."
        warnings.append(message)
        self._set_status(self.warning_label, warnings)
        QApplication.processEvents()
        try:
            path = download_single_item(self.download_root, category_key, name)
        except Exception as exc:
            warnings.append(f"{name}: download failed. {exc}")
            return None
        self.download_root = default_data_root()
        self.catalog = build_catalog(self.download_root, self.remote_options)
        self._refresh_catalog_choices()
        warnings.append(f"{name}: downloaded {label}.")
        return path


def _choose_filter_file(files: tuple[Path, ...], aoi: int | None) -> Path | None:
    if aoi is None:
        for path in files:
            if "_AOI_default" in path.stem:
                return path
        return files[0] if files else None
    suffix = f"_AOI_{aoi:02d}deg"
    for path in files:
        if path.stem.endswith(suffix):
            return path
    return None


def _row_key(row: FilterRow) -> str:
    return str(id(row))


def _aoi_auc_rows(
    curves: list[Spectrum],
    x_range: tuple[int, int],
    *,
    baseline_area: float | None = None,
    weight_curve: Spectrum | None = None,
) -> list[tuple[str, int, str, float, float]]:
    raw_rows = []
    for curve in curves:
        angle = _curve_angle(curve)
        if angle is None:
            continue
        angle_text, angle_value = angle
        raw_rows.append((angle_text, angle_value, _curve_label_without_angle(curve.name), _area_under_curve(curve, x_range, weight_curve)))
    denominator = baseline_area if baseline_area is not None else max((row[3] for row in raw_rows), default=0.0)
    rows = [
        (angle_text, angle_value, label, area, area / denominator * 100.0 if denominator > 0 else 0.0)
        for angle_text, angle_value, label, area in raw_rows
    ]
    return sorted(rows, key=lambda row: (row[1], row[2]))


def _aoi_auc_rows_for_filter(
    curves: list[Spectrum],
    x_range: tuple[int, int],
    filter_name: str,
    weight_curve: Spectrum | None = None,
) -> list[tuple[str, int, str, float, float]]:
    raw_rows = []
    for curve in curves:
        match = _curve_filter_angle(curve.name, filter_name)
        if match is None:
            continue
        angle_text, angle_value = match
        raw_rows.append((angle_text, angle_value, _curve_context_without_filter(curve.name, filter_name), _area_under_curve(curve, x_range, weight_curve)))
    peak = max((row[3] for row in raw_rows), default=0.0)
    rows = [
        (angle_text, angle_value, label, area, area / peak * 100.0 if peak > 0 else 0.0)
        for angle_text, angle_value, label, area in raw_rows
    ]
    return sorted(rows, key=lambda row: (row[1], row[2]))


def _curve_filter_angle(name: str, filter_name: str) -> tuple[str, int] | None:
    pattern = rf"{re.escape(filter_name)}\s+AOI\s+(-?\d+)\s*deg(?:\s+\(([+-]\d+)\))?"
    match = re.search(pattern, name)
    if not match:
        return None
    aoi = int(match.group(1))
    offset_text = match.group(2)
    if offset_text is None:
        return (f"{aoi} deg", aoi)
    offset = int(offset_text)
    return (f"{aoi} deg ({offset:+d})", aoi)


def _curve_context_without_filter(name: str, filter_name: str) -> str:
    numbered_match = re.match(r"\d+:\s*(.+)$", name)
    combo_label = numbered_match.group(1).strip() if numbered_match else name.strip()
    parts = [part.strip() for part in combo_label.split(", ")]
    remaining = [part for part in parts if not re.search(rf"^{re.escape(filter_name)}\s+AOI\s+", part)]
    return ", ".join(remaining) if remaining else "Area"


def _curve_angle(curve: Spectrum) -> tuple[str, int] | None:
    combo_match = re.search(r"Combo\s+(\d+):", curve.name)
    if combo_match:
        value = int(combo_match.group(1))
        return (str(value), value)
    numbered_match = re.match(r"(\d+):", curve.name)
    if numbered_match:
        value = int(numbered_match.group(1))
        return (str(value), value)
    offset_match = re.search(r"Offset\s+([+-]?\d+)\s*deg", curve.name)
    if offset_match:
        value = int(offset_match.group(1))
        return (f"{value:+d} deg", value)
    aoi_match = re.search(r"AOI\s+(-?\d+)\s*deg", curve.name)
    if aoi_match:
        value = int(aoi_match.group(1))
        return (f"{value} deg", value)
    return None


def _curve_label_without_angle(name: str) -> str:
    combo_match = re.match(r"Combo\s+\d+:\s*(.+)$", name)
    if combo_match:
        return combo_match.group(1).strip()
    numbered_match = re.match(r"\d+:\s*(.+)$", name)
    if numbered_match:
        return numbered_match.group(1).strip()
    without_offset = re.sub(r"\s+Offset\s+[+-]?\d+\s*deg(?:\s+\(.*\))?\s*$", "", name)
    return re.sub(r"\s+AOI\s+-?\d+\s*deg(?:\s+\([+-]?\d+\))?\s*$", "", without_offset).strip()


def _filter_aoi_label(name: str, aoi: int | None, reference_aoi: int | None = None) -> str:
    if aoi is None:
        return f"{name} AOI default"
    label = f"{name} AOI {aoi} deg"
    if reference_aoi is not None:
        offset = aoi - reference_aoi
        label += f" ({offset:+d})"
    return label


def _filter_combo_label(filters: tuple[SelectedFilter, ...], rows: list[FilterRow]) -> str:
    labels = []
    for selected, row in zip(filters, rows):
        labels.append(_filter_aoi_label(selected.name, selected.aoi, row.selected_aoi() or 0))
    return ", ".join(labels)


def _area_under_curve(curve: Spectrum, x_range: tuple[int, int], weight_curve: Spectrum | None = None) -> float:
    start, end = x_range
    if not curve.wavelengths or not curve.values:
        return 0.0

    interior = [wavelength for wavelength in curve.wavelengths if start < wavelength < end]
    if weight_curve is not None:
        interior.extend(wavelength for wavelength in weight_curve.wavelengths if start < wavelength < end)
    axis = sorted({float(start), float(end), *interior})
    values = interpolate_values(curve.wavelengths, curve.values, axis)
    if weight_curve is not None:
        weights = interpolate_values(weight_curve.wavelengths, weight_curve.values, axis)
        values = [value * weight for value, weight in zip(values, weights)]
    area = 0.0
    for left_x, right_x, left_y, right_y in zip(axis, axis[1:], values, values[1:]):
        area += (right_x - left_x) * (left_y + right_y) / 2.0
    return area


def _combined_filter_area(
    left_curve: Spectrum,
    right_curve: Spectrum,
    x_range: tuple[int, int],
    weight_curve: Spectrum | None = None,
) -> float:
    start, end = x_range
    if not left_curve.wavelengths or not right_curve.wavelengths:
        return 0.0
    interior = [wavelength for wavelength in left_curve.wavelengths if start < wavelength < end]
    interior.extend(wavelength for wavelength in right_curve.wavelengths if start < wavelength < end)
    axis = sorted({float(start), float(end), *interior})
    left_values = interpolate_values(left_curve.wavelengths, left_curve.values, axis)
    right_values = interpolate_values(right_curve.wavelengths, right_curve.values, axis)
    combined = Spectrum("Combined filter throughput", axis, [left * right for left, right in zip(left_values, right_values)], "filter")
    return _area_under_curve(combined, x_range, weight_curve)


def _no_filter_auc(x_range: tuple[int, int], weight_curve: Spectrum | None = None) -> float:
    if weight_curve is not None:
        unit_filter = Spectrum("No filter", [x_range[0], x_range[1]], [1.0, 1.0], "filter_transmission")
        return _area_under_curve(unit_filter, x_range, weight_curve)
    start, end = x_range
    return float(max(0, end - start))


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _included_filter_names(rows: list[FilterRow]) -> list[str]:
    names = [
        row.selected_filter()
        for row in rows
        if row.selected_filter() and row.selected_mode() not in {"excluded", "visualize"}
    ]
    return list(dict.fromkeys(names))


def _included_filter_rows(rows: list[FilterRow]) -> list[FilterRow]:
    return [
        row
        for row in rows
        if row.selected_filter() and row.selected_mode() in {"transmission", "reflection"}
    ]


def _included_filter_entries(rows: list[FilterRow]) -> list[tuple[str, str]]:
    return [
        (_row_key(row), row.selected_filter())
        for row in _included_filter_rows(rows)
    ]


def _populate_key_combo(
    combo: QComboBox,
    choices: list[tuple[str, str]],
    *,
    preferred_index: int = 0,
    avoid_key: str | None = None,
) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for key, label in choices:
        combo.addItem(label, key)
    keys = [key for key, _label in choices]
    if current in keys:
        combo.setCurrentIndex(keys.index(current))
    elif choices:
        index = min(max(0, preferred_index), len(choices) - 1)
        if avoid_key is not None and keys[index] == avoid_key and len(choices) > 1:
            index = next((candidate for candidate, key in enumerate(keys) if key != avoid_key), index)
        combo.setCurrentIndex(index)
    _install_flat_combo_view(combo)
    combo.blockSignals(False)


def _populate_source_combo(
    combo: QComboBox,
    catalog: Catalog,
    category_key: str,
    *,
    placeholder: str,
    preserve_text: bool = False,
) -> None:
    current = combo.currentText() if preserve_text else placeholder
    current = _catalog_name_or_placeholder(catalog, category_key, current, placeholder)
    combo.blockSignals(True)
    combo.clear()
    if placeholder:
        combo.addItem(placeholder)
    elif placeholder == "":
        combo.addItem("")

    for name, item in sorted(catalog.category(category_key).items()):
        combo.addItem(_source_icon(item), name)
        index = combo.count() - 1
        combo.setItemData(index, item.source_label, Qt.ToolTipRole)
        combo.setItemData(index, item.source_label, Qt.AccessibleDescriptionRole)

    _set_combo_catalog_text(combo, catalog, category_key, current, placeholder=placeholder)
    _install_flat_combo_view(combo)
    combo.blockSignals(False)
    completer = QCompleter([combo.itemText(index) for index in range(combo.count()) if combo.itemText(index)], combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)


def _install_flat_combo_view(combo: QComboBox) -> None:
    popup_style = NonNativeComboPopupStyle()
    combo.setStyle(popup_style)
    combo._dichroly_popup_style = popup_style  # type: ignore[attr-defined]
    view = QListView()
    view.setObjectName("FlatComboPopup")
    view.setFrameShape(QFrame.NoFrame)
    view.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    view.setAttribute(Qt.WA_StyledBackground, True)
    view.setAttribute(Qt.WA_TranslucentBackground, True)
    view.setContentsMargins(1, 1, 1, 1)
    view.setWordWrap(False)
    view.setTextElideMode(Qt.ElideRight)
    view.setUniformItemSizes(True)
    view.setSpacing(0)
    view.setMaximumHeight(306)
    view.setItemDelegate(ComboItemDelegate(view))
    view.viewport().setAutoFillBackground(False)
    view.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
    view.viewport().setContentsMargins(1, 1, 1, 1)
    view.viewport().setStyleSheet("background: transparent; border: 0;")
    combo.setView(view)
    combo.setMaxVisibleItems(8)


def _set_combo_catalog_text(
    combo: QComboBox,
    catalog: Catalog,
    category_key: str,
    value: str,
    *,
    placeholder: str,
) -> None:
    resolved = _catalog_name_or_placeholder(catalog, category_key, value, placeholder)
    index = combo.findText(resolved, Qt.MatchFixedString)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(resolved)


def _catalog_name_or_placeholder(catalog: Catalog, category_key: str, value: str, placeholder: str) -> str:
    text = value.strip()
    if not text:
        return placeholder
    if placeholder and text == placeholder:
        return placeholder
    item = catalog.find(category_key, text)
    return item.name if item else text


def _source_icon(item) -> QIcon:  # noqa: ANN001
    if item.is_local:
        return _badge_icon(QColor("#34c759"))
    if item.available_remote:
        return _badge_icon(QColor("#0a84ff"))
    return _badge_icon(QColor("#8e8e93"))


def _badge_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.transparent)
    painter = None
    try:
        from PySide6.QtGui import QPainter

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 10, 10, 5, 5)
    finally:
        if painter is not None:
            painter.end()
    return QIcon(pixmap)


def _merge_remote_options(
    current: dict[str, list[str]],
    incoming: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = {key: list(values) for key, values in current.items()}
    for key, values in incoming.items():
        existing = merged.setdefault(key, [])
        known = {_canonical_lookup_key(value) for value in existing}
        for value in values:
            canonical = _canonical_lookup_key(value)
            if canonical not in known:
                existing.append(value)
                known.add(canonical)
    return merged


def _canonical_lookup_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _source_name_widget(name: str, item) -> QWidget:  # noqa: ANN001
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    if item is not None:
        badge = QLabel()
        badge.setPixmap(_source_icon(item).pixmap(14, 14))
        badge.setToolTip(item.source_label)
        layout.addWidget(badge)
    name_label = QLabel(name)
    if item is not None:
        name_label.setToolTip(item.source_label)
    layout.addWidget(name_label, 1)
    return widget


def _aoi_auc_panel(title: str) -> tuple[Panel, QTableWidget, AoiAreaPlot]:
    panel = Panel()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    layout.addWidget(_section_label(title))

    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(14)
    table = _new_auc_table()
    plot = AoiAreaPlot(height=190)
    body.addWidget(_table_export_host(table, title))
    body.addWidget(plot.widget())
    layout.addLayout(body)
    return panel, table, plot


def _new_auc_table() -> QTableWidget:
    table = QTableWidget(0, 4)
    table.setObjectName("SummaryTable")
    table.setHorizontalHeaderLabels(["Angle", "Curve", "Area", "%"])
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
    return table


def _table_export_host(table: QTableWidget, title: str) -> QWidget:
    class TableHost(QWidget):
        def __init__(self) -> None:
            super().__init__()
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(table)
            self.export_button = QPushButton("Save", self)
            self.export_button.setObjectName("PlotSave")
            self.export_button.setFixedSize(78, 34)
            self.export_button.setCursor(Qt.PointingHandCursor)
            self.export_button.setToolTip("Export table as CSV")
            self.export_button.clicked.connect(lambda: _export_table_csv(table, title))
            self.export_button.raise_()

        def resizeEvent(self, event) -> None:  # noqa: ANN001
            super().resizeEvent(event)
            self.export_button.move(
                10,
                max(10, self.height() - self.export_button.height() - 10),
            )
            self.export_button.raise_()

    host = TableHost()
    host.export_button.move(10, 10)
    return host


def _export_table_csv(table: QTableWidget, title: str) -> None:
    path_text, _selected_filter = QFileDialog.getSaveFileName(
        None,
        "Export table",
        f"{safe_name(title)}_auc.csv",
        "CSV file (*.csv)",
    )
    if not path_text:
        return
    path = Path(path_text)
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")

    headers = [
        table.horizontalHeaderItem(column).text() if table.horizontalHeaderItem(column) else f"Column {column + 1}"
        for column in range(table.columnCount())
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in range(table.rowCount()):
            writer.writerow(
                [
                    table.item(row, column).text() if table.item(row, column) else ""
                    for column in range(table.columnCount())
                ]
            )


def _fill_auc_table(table: QTableWidget, rows: list[tuple[str, int, str, float, float]]) -> None:
    table.setRowCount(len(rows))
    for row_index, (angle_text, _angle_value, label, area, percent) in enumerate(rows):
        aoi_item = QTableWidgetItem(angle_text)
        label_item = QTableWidgetItem(label)
        area_item = QTableWidgetItem(f"{area:.6g}")
        percent_item = QTableWidgetItem(f"{percent:.1f}%")
        aoi_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        area_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row_index, 0, aoi_item)
        table.setItem(row_index, 1, label_item)
        table.setItem(row_index, 2, area_item)
        table.setItem(row_index, 3, percent_item)


def _mirror_row(primary: str, secondary: str | None = None, tertiary: str | None = None, *, source_item=None) -> Panel:  # noqa: ANN001
    row = Panel()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(10, 7, 10, 7)
    row_layout.setSpacing(8)
    row_layout.addWidget(_source_name_widget(primary, source_item), 3)
    if secondary is not None:
        row_layout.addWidget(QLabel(secondary), 1)
    if tertiary is not None:
        row_layout.addWidget(QLabel(tertiary), 1)
    return row


def _control_group(title: str, widget: QWidget) -> QFrame:
    panel = QFrame()
    panel.setObjectName("InlinePanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    layout.addWidget(_section_label(title))
    layout.addWidget(widget)
    return panel


def _plot_range_row(
    x_start: QLineEdit,
    x_end: QLineEdit,
    y_min: QLineEdit,
    y_max: QLineEdit,
    auc_percent_min: QLineEdit,
    auc_percent_max: QLineEdit,
) -> QFrame:
    panel = QFrame()
    panel.setObjectName("InlinePanel")
    layout = QHBoxLayout(panel)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(7)
    layout.addWidget(_section_label("Plot range"))
    layout.addWidget(QLabel("X"))
    layout.addWidget(x_start)
    layout.addWidget(QLabel("-"))
    layout.addWidget(x_end)
    layout.addSpacing(10)
    layout.addWidget(QLabel("Y"))
    layout.addWidget(y_min)
    layout.addWidget(QLabel("-"))
    layout.addWidget(y_max)
    layout.addSpacing(10)
    layout.addWidget(QLabel("AUC %"))
    layout.addWidget(auc_percent_min)
    layout.addWidget(QLabel("-"))
    layout.addWidget(auc_percent_max)
    layout.addStretch(1)
    return panel


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    return line


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def _range_edit(value: str, *, width: int) -> QLineEdit:
    edit = QLineEdit(value)
    edit.setFixedWidth(width)
    edit.setAlignment(Qt.AlignRight)
    return edit


def _copy_range_text(source: QLineEdit, target: QLineEdit) -> None:
    target.blockSignals(True)
    target.setText(source.text())
    target.blockSignals(False)


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return fallback


def _normalize_aoi_result_mode(value: object) -> str:
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"light", "light_source", "source", "result_light_source"}:
        return "light_source"
    if text in {"excitation", "result_excitation"}:
        return "excitation"
    return "emission"


def _range_value(edit: QLineEdit, fallback: int) -> int:
    text = edit.text().strip()
    if not text:
        edit.setText(str(fallback))
        return fallback
    try:
        return int(float(text))
    except ValueError:
        edit.setText(str(fallback))
        return fallback


def _float_range_value(edit: QLineEdit, fallback: float) -> float:
    text = edit.text().strip()
    if not text:
        edit.setText(f"{fallback:g}")
        return fallback
    try:
        return float(text)
    except ValueError:
        edit.setText(f"{fallback:g}")
        return fallback


def _bounded_int_edit_value(edit: QLineEdit, fallback: int, minimum: int, maximum: int) -> int:
    value = _range_value(edit, fallback)
    value = min(maximum, max(minimum, value))
    edit.setText(str(value))
    return value
