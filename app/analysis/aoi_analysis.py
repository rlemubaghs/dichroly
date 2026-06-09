"""Multi-AOI filter analysis."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.calculations import filter_curve_for_mode
from app.data.spectra import FilterSpectra, Spectrum, default_wavelength_axis


@dataclass(frozen=True)
class AoiCurve:
    filter_name: str
    aoi: int
    spectrum: Spectrum
    warning: str | None = None


def requested_aoi_values(start: int, end: int, step: int, *, default_orientation: int | None = None) -> list[int]:
    if step <= 0:
        raise ValueError("step size must be greater than zero")
    start = max(0, start)
    if default_orientation == 0:
        start = max(0, start)
    if end < start:
        raise ValueError("end angle must be greater than or equal to start angle")
    return list(range(start, end + 1, step))


def requested_relative_aoi_values(current: int, span: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("step size must be greater than zero")
    if span < 0:
        raise ValueError("span must be greater than or equal to zero")
    start = max(0, current - span)
    end = current + span
    return list(range(start, end + 1, step))


def requested_relative_offsets(current_values: list[int], span: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("step size must be greater than zero")
    if span < 0:
        raise ValueError("span must be greater than or equal to zero")
    lowest_offset = -span
    if current_values:
        lowest_offset = max(lowest_offset, -min(current_values))
    return list(range(lowest_offset, span + 1, step))


def build_aoi_curves(
    spectra_by_aoi: dict[int, FilterSpectra],
    *,
    filter_name: str,
    aoi_values: list[int],
    mode: str,
    axis: list[float] | None = None,
) -> tuple[list[AoiCurve], list[str]]:
    axis = axis or default_wavelength_axis()
    curves: list[AoiCurve] = []
    warnings: list[str] = []
    for aoi in aoi_values:
        filter_spectra = spectra_by_aoi.get(aoi)
        if filter_spectra is None:
            interpolated = interpolate_missing_aoi(spectra_by_aoi, aoi, mode, axis)
            if interpolated is None:
                warnings.append(f"{filter_name}: AOI {aoi} deg is missing and could not be interpolated.")
                continue
            curves.append(AoiCurve(filter_name, aoi, interpolated, "interpolated between nearby AOI files"))
            continue
        curve, assumption = filter_curve_for_mode(filter_spectra, mode)
        if curve is None:
            warnings.append(f"{filter_name}: AOI {aoi} deg has no usable {mode} curve.")
            continue
        if assumption:
            warnings.append(assumption)
        curves.append(AoiCurve(filter_name, aoi, Spectrum(f"{filter_name} {aoi} deg", axis, curve.interpolate(axis), curve.kind, curve.source_path)))
    return curves, warnings


def interpolate_missing_aoi(
    spectra_by_aoi: dict[int, FilterSpectra],
    target_aoi: int,
    mode: str,
    axis: list[float],
) -> Spectrum | None:
    lower_values = sorted(aoi for aoi in spectra_by_aoi if aoi < target_aoi)
    upper_values = sorted((aoi for aoi in spectra_by_aoi if aoi > target_aoi), reverse=True)
    if not lower_values or not upper_values:
        return None
    lower_aoi = lower_values[-1]
    upper_aoi = upper_values[-1]
    lower_curve, _ = filter_curve_for_mode(spectra_by_aoi[lower_aoi], mode)
    upper_curve, _ = filter_curve_for_mode(spectra_by_aoi[upper_aoi], mode)
    if lower_curve is None or upper_curve is None or upper_aoi == lower_aoi:
        return None
    fraction = (target_aoi - lower_aoi) / (upper_aoi - lower_aoi)
    lower = lower_curve.interpolate(axis)
    upper = upper_curve.interpolate(axis)
    values = [lo + fraction * (hi - lo) for lo, hi in zip(lower, upper)]
    return Spectrum(f"AOI {target_aoi} deg interpolated", axis, values, lower_curve.kind, lower_curve.source_path)
