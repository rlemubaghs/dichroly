"""Matplotlib canvas wrapper used by the Qt interface."""

from __future__ import annotations

from itertools import cycle
from math import ceil
from pathlib import Path
import re

from app.data.spectra import Spectrum


FLUOROPHORE_GREY = "#8e8e93"
VISUALIZE_FILTER_COLOR = "#00a6a6"
LINE_COLORS = [
    "#0a84ff",
    "#ff9f0a",
    "#af52de",
    "#ff375f",
    "#5e5ce6",
    "#64d2ff",
    "#30d158",
    "#bf5af2",
]
FLUOROPHORE_KINDS = {"fluorophore_excitation", "fluorophore_emission"}
REFERENCE_LINE_KINDS = {*FLUOROPHORE_KINDS, "light_source"}
FIXED_REFERENCE_KINDS = {*REFERENCE_LINE_KINDS, "filter_visualize"}
RESULT_STYLES = {
    "result_excitation": "#0a84ff",
    "result_emission": "#ff375f",
    "result_light_source": "#ff9f0a",
    "result": "#5e5ce6",
}


class SpectraPlot:
    def __init__(self, *, height: int = 330) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

        self.figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(height)
        self.canvas.setMaximumHeight(height)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.canvas.wheelEvent = lambda event: event.ignore()  # type: ignore[method-assign]
        self.axes = self.figure.add_subplot(111)
        self.axes.set_position([0.08, 0.15, 0.88, 0.74])
        self.container = QWidget()
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)
        self.canvas_host = _canvas_with_save_button(
            self.figure,
            self.canvas,
            self._save_title,
            axes_getter=lambda: self.axes,
            inside_axes=True,
        )
        container_layout.addWidget(self.canvas_host)

        self.legend_scroll = QScrollArea()
        self.legend_scroll.setObjectName("PlotLegend")
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setMaximumHeight(96)
        self.legend_scroll.setFrameShape(QFrame.NoFrame)
        self.legend_body = QWidget()
        self.legend_layout = QGridLayout(self.legend_body)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setHorizontalSpacing(12)
        self.legend_layout.setVerticalSpacing(0)
        self.legend_scroll.setWidget(self.legend_body)
        self.legend_scroll.hide()
        container_layout.addWidget(self.legend_scroll)
        self._qt = Qt
        self._last_title = "plot"

    def widget(self):
        return self.container

    def plot(
        self,
        curves: list[Spectrum],
        *,
        title: str,
        x_range: tuple[int, int] = (300, 900),
        y_range: tuple[float, float] = (0.0, 1.0),
        aoi_gradient: bool = False,
        aoi_gradient_base_color: str = "#0a84ff",
        peak_result_colors: bool = False,
    ) -> None:
        self.axes.clear()
        self._last_title = title
        self.axes.set_position([0.08, 0.15, 0.88, 0.74])
        self.axes.set_title(title)
        self.axes.set_xlabel("Wavelength (nm)")
        self.axes.set_ylabel("Normalized intensity / fraction")
        self.axes.grid(True, alpha=0.22)
        color_cycle = cycle(LINE_COLORS)
        non_reference_curves = [curve for curve in curves if curve.kind not in FIXED_REFERENCE_KINDS]
        use_fixed_result_colors = len(non_reference_curves) <= 2
        aoi_colors = _aoi_gradient_colors(non_reference_curves, base_color=aoi_gradient_base_color) if aoi_gradient else {}
        legend_rows: list[tuple[str, str, str]] = []
        for curve in curves:
            if curve.kind in REFERENCE_LINE_KINDS:
                color = FLUOROPHORE_GREY
                linestyle = ":"
            elif curve.kind == "filter_visualize":
                color = VISUALIZE_FILTER_COLOR
                linestyle = "-"
            elif peak_result_colors and curve.kind in RESULT_STYLES:
                color = _peak_wavelength_color(curve)
                linestyle = "-"
            elif use_fixed_result_colors and curve.kind in RESULT_STYLES:
                color = RESULT_STYLES[curve.kind]
                linestyle = "-"
            elif curve.name in aoi_colors:
                color = aoi_colors[curve.name]
                linestyle = "-"
            else:
                color = next(color_cycle)
                linestyle = "-"
            self.axes.plot(
                curve.wavelengths,
                curve.values,
                color=color,
                linestyle=linestyle,
                linewidth=2.0 if curve.kind in REFERENCE_LINE_KINDS else 1.8,
                label=curve.name,
            )
            legend_rows.append((curve.name, color, linestyle))
        self._set_scroll_legend(legend_rows)
        self.axes.set_xlim(*x_range)
        self.axes.set_ylim(*y_range)
        self.canvas.draw_idle()
        if hasattr(self.canvas_host, "update_save_button_position"):
            self.canvas_host.update_save_button_position()

    def _save_title(self) -> str:
        return self._last_title

    def _set_scroll_legend(self, rows: list[tuple[str, str, str]]) -> None:
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not rows:
            self.legend_scroll.hide()
            return
        for index, (label, color, linestyle) in enumerate(rows):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            sample = QFrame()
            sample.setFixedWidth(28)
            sample.setFixedHeight(8)
            border_style = "dotted" if linestyle == ":" else "solid"
            sample.setStyleSheet(f"border: 0; border-top: 2px {border_style} {color}; background: transparent;")
            text = QLabel(label)
            text.setStyleSheet("font-size: 11px;")
            text.setTextInteractionFlags(self._qt.TextSelectableByMouse)
            row_layout.addWidget(sample)
            row_layout.addWidget(text, 1)
            self.legend_layout.addWidget(row, index // 3, index % 3)
        for column in range(3):
            self.legend_layout.setColumnStretch(column, 1)
        for index in range(len(rows), max(3, len(rows))):
            spacer = QWidget()
            self.legend_layout.addWidget(spacer, index // 3, index % 3)
        visible_rows = ceil(len(rows) / 3)
        height = min(96, max(22, visible_rows * 19 + 4))
        self.legend_scroll.setFixedHeight(height)
        self.legend_scroll.show()


def _aoi_gradient_colors(curves: list[Spectrum], *, base_color: str = "#0a84ff") -> dict[str, str]:
    aoi_values = {curve.name: _curve_aoi(curve.name) for curve in curves}
    numeric_values = [value for value in aoi_values.values() if value is not None]
    if not numeric_values:
        return {}

    low = min(numeric_values)
    high = max(numeric_values)
    base = _hex_to_rgb(base_color)
    start = _mix_rgb(base, (255, 255, 255), 0.72)
    end = _mix_rgb(base, (0, 0, 0), 0.34)
    colors: dict[str, str] = {}
    for name, value in aoi_values.items():
        if value is None:
            continue
        fraction = 0.5 if high == low else (value - low) / (high - low)
        rgb = tuple(round(left + (right - left) * fraction) for left, right in zip(start, end))
        colors[name] = "#{:02x}{:02x}{:02x}".format(*rgb)
    return colors


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) != 6:
        return (10, 132, 255)
    try:
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    except ValueError:
        return (10, 132, 255)


def _mix_rgb(left: tuple[int, int, int], right: tuple[int, int, int], fraction: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * fraction) for a, b in zip(left, right))


def _curve_aoi(name: str) -> int | None:
    match = re.search(r"AOI\s+(-?\d+)\s*deg", name)
    if not match:
        return None
    return int(match.group(1))


def _peak_wavelength_color(curve: Spectrum) -> str:
    if not curve.wavelengths or not curve.values:
        return RESULT_STYLES.get(curve.kind, "#5e5ce6")
    peak_index = max(range(len(curve.values)), key=lambda index: curve.values[index])
    return _wavelength_to_rgb(curve.wavelengths[peak_index])


def _wavelength_to_rgb(wavelength: float) -> str:
    wl = max(380.0, min(700.0, float(wavelength)))
    stops = [
        (380.0, (111, 66, 193)),
        (430.0, (75, 98, 255)),
        (488.0, (0, 132, 255)),
        (510.0, (0, 170, 120)),
        (555.0, (70, 190, 60)),
        (590.0, (255, 190, 0)),
        (620.0, (255, 110, 0)),
        (700.0, (220, 35, 45)),
    ]
    for (left_wl, left_rgb), (right_wl, right_rgb) in zip(stops, stops[1:]):
        if left_wl <= wl <= right_wl:
            fraction = (wl - left_wl) / (right_wl - left_wl)
            rgb = tuple(round(left + (right - left) * fraction) for left, right in zip(left_rgb, right_rgb))
            return "#{:02x}{:02x}{:02x}".format(*rgb)
    return "#{:02x}{:02x}{:02x}".format(*stops[-1][1])


class AoiAreaPlot:
    def __init__(self, *, height: int = 190) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        from PySide6.QtWidgets import QSizePolicy

        self.figure = Figure(figsize=(4, 4))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(height)
        self.canvas.setMaximumHeight(height)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.canvas.wheelEvent = lambda event: event.ignore()  # type: ignore[method-assign]
        self.axes = self.figure.add_subplot(111)
        self.axes.set_position([0.14, 0.16, 0.70, 0.74])
        self.percent_axes = None
        self.container = _canvas_with_save_button(
            self.figure,
            self.canvas,
            self._save_title,
            axes_getter=lambda: self.axes,
            inside_axes=True,
            save_corner="bottom-left",
        )
        self._last_title = "area_under_curve"

    def widget(self):
        return self.container

    def set_square_size(self, size: int) -> None:
        size = max(180, size)
        self.container.setMinimumWidth(size)
        self.container.setMaximumWidth(size)
        self.container.setMinimumHeight(size)
        self.container.setMaximumHeight(size)
        self.canvas.setMinimumWidth(size)
        self.canvas.setMaximumWidth(size)
        self.canvas.setMinimumHeight(size)
        self.canvas.setMaximumHeight(size)

    def plot(
        self,
        rows: list[tuple[str, int, str, float, float]],
        *,
        title: str = "Area under curve",
        percent_range: tuple[float, float] = (0.0, 100.0),
        percent_denominator: float | None = None,
    ) -> None:
        if self.percent_axes is not None:
            self.percent_axes.remove()
            self.percent_axes = None
        self.axes.clear()
        self._last_title = title
        self.axes.set_position([0.14, 0.16, 0.70, 0.74])
        self.axes.set_title(title)
        self.axes.set_xlabel("AOI / offset (deg)")
        self.axes.set_ylabel("Area")
        self.axes.grid(True, alpha=0.22)

        grouped: dict[str, list[tuple[int, float]]] = {}
        for _angle_text, angle_value, label, area, _percent in rows:
            grouped.setdefault(label, []).append((angle_value, area))

        color_cycle = cycle(LINE_COLORS)
        if rows and len(grouped) == len(rows):
            sorted_rows = sorted(rows, key=lambda row: row[1])
            xs = [row[1] for row in sorted_rows]
            ys = [row[3] for row in sorted_rows]
            self.axes.plot(xs, ys, color=next(color_cycle), marker="o", linewidth=1.8, markersize=4, label="Area")
            grouped = {"Area": list(zip(xs, ys))}
        else:
            for label, points in grouped.items():
                sorted_points = sorted(points, key=lambda point: point[0])
                xs = [point[0] for point in sorted_points]
                ys = [point[1] for point in sorted_points]
                self.axes.plot(xs, ys, color=next(color_cycle), marker="o", linewidth=1.8, markersize=4, label=label)

        denominator = percent_denominator
        if denominator is None:
            denominator = max((area for *_prefix, area, _percent in rows), default=0.0)
        self.percent_axes = self.axes.twinx()
        self.percent_axes.set_position([0.14, 0.16, 0.70, 0.74])
        self.percent_axes.set_ylabel("% of total area")
        self.percent_axes.set_ylim(*percent_range)
        if denominator > 0:
            percent_min, percent_max = percent_range
            self.axes.set_ylim(denominator * percent_min / 100.0, denominator * percent_max / 100.0)

        if grouped:
            self.axes.legend(loc="best", fontsize=8)
        self.canvas.draw_idle()
        if hasattr(self.container, "update_save_button_position"):
            self.container.update_save_button_position()

    def _save_title(self) -> str:
        return self._last_title


def _canvas_with_save_button(
    figure,
    canvas,
    title_getter,
    *,
    axes_getter=None,
    inside_axes: bool = False,
    save_corner: str = "top-right",
):  # noqa: ANN001
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    class CanvasHost(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.save_button = QPushButton("Save", self)
            self.save_button.setObjectName("PlotSave")
            self.save_button.setFixedSize(78, 34)
            self.save_button.setCursor(Qt.PointingHandCursor)
            self.save_button.setToolTip("Save graph as transparent PNG")
            self.save_button.clicked.connect(lambda: _save_figure_png(figure, title_getter()))

        def resizeEvent(self, event) -> None:  # noqa: ANN001
            super().resizeEvent(event)
            self.update_save_button_position()

        def update_save_button_position(self) -> None:
            if inside_axes and axes_getter is not None:
                axes = axes_getter()
                bbox = axes.get_position()
                canvas_width = max(1, canvas.width())
                canvas_height = max(1, canvas.height())
                axes_left = round(bbox.x0 * canvas_width)
                axes_right = round(bbox.x1 * canvas_width)
                axes_top = round((1.0 - bbox.y1) * canvas_height)
                axes_bottom = round((1.0 - bbox.y0) * canvas_height)
                if save_corner == "bottom-left":
                    x = max(0, axes_left + 10)
                    y = max(0, axes_bottom - self.save_button.height() - 10)
                else:
                    x = max(0, axes_right - self.save_button.width() - 10)
                    y = max(0, axes_top + 10)
            else:
                x = max(10, self.width() - self.save_button.width() - 10)
                y = 10
            self.save_button.move(x, y)
            self.save_button.raise_()

    host = CanvasHost()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(canvas)
    host.update_save_button_position()
    return host


def _save_figure_png(figure, title: str) -> None:  # noqa: ANN001
    from PySide6.QtWidgets import QFileDialog

    default_name = _safe_plot_filename(title)
    path_text, _selected_filter = QFileDialog.getSaveFileName(
        None,
        "Save graph",
        default_name,
        "PNG image (*.png)",
    )
    if not path_text:
        return
    path = Path(path_text)
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")

    patches = [figure.patch, *[axis.patch for axis in figure.axes]]
    old_alpha = [patch.get_alpha() for patch in patches]
    try:
        for patch in patches:
            patch.set_alpha(0)
        figure.savefig(path, dpi=300, transparent=True, facecolor="none", edgecolor="none", bbox_inches="tight")
    finally:
        for patch, alpha in zip(patches, old_alpha):
            patch.set_alpha(alpha)


def _safe_plot_filename(title: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._+-]+", "_", title.strip()).strip("._") or "plot"
    return f"{stem}.png"
