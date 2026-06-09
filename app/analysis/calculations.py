"""Spectral combination calculations."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data.spectra import FilterSpectra, FluorophoreSpectra, Spectrum, default_wavelength_axis


@dataclass(frozen=True)
class SelectedFilter:
    name: str
    spectra: FilterSpectra | None
    mode: str = "transmission"
    aoi: int | None = None

    @property
    def aoi_label(self) -> str:
        return "default" if self.aoi is None else f"{self.aoi} deg"


@dataclass(frozen=True)
class CalculationResult:
    axis: list[float]
    curves: list[Spectrum]
    final_curves: list[Spectrum]
    warnings: list[str] = field(default_factory=list)


def calculate_spectral_result(
    *,
    light_source: Spectrum | list[Spectrum] | None,
    filters: list[SelectedFilter],
    fluorophore: FluorophoreSpectra | None,
    axis: list[float] | None = None,
) -> CalculationResult:
    axis = axis or default_wavelength_axis()
    warnings: list[str] = []
    curves: list[Spectrum] = []

    light_sources = _as_light_source_list(light_source)
    if light_sources:
        interpolated_sources = [source.interpolate(axis) for source in light_sources]
        light_values = [sum(values) for values in zip(*interpolated_sources)]
        for source, values in zip(light_sources, interpolated_sources):
            curves.append(Spectrum(source.name, axis, values, "light_source", source.source_path))
    else:
        light_values = [1.0 for _ in axis]

    combined_filter = [1.0 for _ in axis]
    for selected in filters:
        if selected.mode.lower() in {"excluded", "visualize"}:
            continue
        if selected.spectra is None:
            warnings.append(f"{selected.name} has not been downloaded yet. Please run the downloader first.")
            continue
        curve, assumption = filter_curve_for_mode(selected.spectra, selected.mode)
        if curve is None:
            warnings.append(f"{selected.name} has no usable {selected.mode} data.")
            continue
        values = curve.interpolate(axis)
        curves.append(Spectrum(f"{selected.name} {selected.mode} AOI {selected.aoi_label}", axis, values, curve.kind, curve.source_path))
        combined_filter = [left * right for left, right in zip(combined_filter, values)]
        if assumption:
            warnings.append(assumption)

    final_curves: list[Spectrum] = []
    throughput = [left * right for left, right in zip(light_values, combined_filter)]

    if fluorophore is None:
        final_curves.append(Spectrum("Combined illumination throughput", axis, throughput, "result"))
        return CalculationResult(axis, curves, final_curves, warnings)

    if light_sources:
        final_curves.append(
            Spectrum(
                "Light source through optical path",
                axis,
                throughput,
                "result_light_source",
            )
        )

    if fluorophore.excitation:
        excitation = fluorophore.excitation.interpolate(axis)
        curves.append(Spectrum(fluorophore.excitation.name, axis, excitation, "fluorophore_excitation", fluorophore.excitation.source_path))
        final_curves.append(
            Spectrum(
                "Excitation reaching tissue",
                axis,
                [filt * ex for filt, ex in zip(combined_filter, excitation)],
                "result_excitation",
            )
        )
    else:
        warnings.append(f"{fluorophore.name} does not include an excitation spectrum.")

    if fluorophore.emission:
        emission = fluorophore.emission.interpolate(axis)
        curves.append(Spectrum(fluorophore.emission.name, axis, emission, "fluorophore_emission", fluorophore.emission.source_path))
        final_curves.append(
            Spectrum(
                "Emission returning through optical path",
                axis,
                [em * filt for em, filt in zip(emission, combined_filter)],
                "result_emission",
            )
        )
    else:
        warnings.append(f"{fluorophore.name} does not include an emission spectrum.")

    return CalculationResult(axis, curves, final_curves, warnings)


def _as_light_source_list(light_source: Spectrum | list[Spectrum] | None) -> list[Spectrum]:
    if light_source is None:
        return []
    if isinstance(light_source, list):
        return light_source
    return [light_source]


def filter_curve_for_mode(filter_spectra: FilterSpectra, mode: str) -> tuple[Spectrum | None, str | None]:
    mode = mode.lower()
    if mode == "excluded":
        return None, None
    if mode == "visualize":
        return filter_spectra.transmission, None
    if mode == "reflection":
        if filter_spectra.reflection is not None:
            return filter_spectra.reflection, None
        if filter_spectra.transmission is not None:
            transmission = filter_spectra.transmission
            reflected = [1.0 - value for value in transmission.values]
            assumption = f"{filter_spectra.name}: reflection estimated as 1 - transmission."
            return (
                Spectrum(
                    f"{filter_spectra.name} estimated reflection",
                    transmission.wavelengths,
                    reflected,
                    "filter_reflection_estimated",
                    transmission.source_path,
                    [assumption],
                ),
                assumption,
            )
        return None, None
    return filter_spectra.transmission, None
