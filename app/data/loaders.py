"""CSV spectral loading."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from app.data.catalog import parse_filter_filename
from app.data.spectra import FilterSpectra, FluorophoreSpectra, Spectrum, normalize_fraction_values, normalize_peak


def load_csv_columns(path: Path) -> dict[str, list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        columns: dict[str, list[float]] = {name: [] for name in (reader.fieldnames or [])}
        for row in reader:
            for name in columns:
                value = (row.get(name) or "").strip()
                try:
                    columns[name].append(float(value))
                except ValueError:
                    columns[name].append(float("nan"))
    return columns


def load_light_source(path: Path, name: str | None = None) -> Spectrum:
    columns = load_csv_columns(path)
    wavelength_key = _find_wavelength_column(columns)
    value_key = _first_data_column(columns, exclude={wavelength_key})
    values = normalize_peak(columns[value_key])
    return Spectrum(name or _clean_label(value_key), columns[wavelength_key], values, "light_source", str(path))


def load_filter(path: Path, name: str | None = None, aoi: int | None = None) -> FilterSpectra:
    columns = load_csv_columns(path)
    wavelength_key = _find_wavelength_column(columns)
    local_name, local_aoi = parse_filter_filename(path)
    resolved_name = name or local_name
    resolved_aoi = aoi if aoi is not None else local_aoi

    transmission_key = _column_by_keywords(columns, ("trans", "through", "pass"))
    reflection_key = _column_by_keywords(columns, ("reflect", "refl"))
    data_keys = [key for key in columns if key != wavelength_key]
    if transmission_key is None and reflection_key is None and data_keys:
        transmission_key = data_keys[0]

    transmission = None
    reflection = None
    if transmission_key:
        transmission = Spectrum(
            f"{resolved_name} T",
            columns[wavelength_key],
            normalize_fraction_values(columns[transmission_key]),
            "filter_transmission",
            str(path),
        )
    if reflection_key:
        reflection = Spectrum(
            f"{resolved_name} R",
            columns[wavelength_key],
            normalize_fraction_values(columns[reflection_key]),
            "filter_reflection",
            str(path),
        )
    return FilterSpectra(resolved_name, resolved_aoi, transmission, reflection, str(path))


def load_fluorophore(path: Path, name: str | None = None) -> FluorophoreSpectra:
    columns = load_csv_columns(path)
    wavelength_key = _find_wavelength_column(columns)
    excitation_key = _column_by_keywords(columns, ("abs", "exc", "ex"))
    emission_key = _column_by_keywords(columns, ("em", "emit"))
    data_keys = [key for key in columns if key != wavelength_key]

    if excitation_key is None and data_keys:
        excitation_key = data_keys[0]
    if emission_key is None and len(data_keys) > 1:
        emission_key = data_keys[1]

    resolved_name = name or _name_from_path(path, "fluorophore_")
    excitation = (
        Spectrum(
            f"{resolved_name} excitation",
            columns[wavelength_key],
            normalize_peak(columns[excitation_key]),
            "fluorophore_excitation",
            str(path),
        )
        if excitation_key
        else None
    )
    emission = (
        Spectrum(
            f"{resolved_name} emission",
            columns[wavelength_key],
            normalize_peak(columns[emission_key]),
            "fluorophore_emission",
            str(path),
        )
        if emission_key
        else None
    )
    return FluorophoreSpectra(resolved_name, excitation, emission, str(path))


def _find_wavelength_column(columns: dict[str, list[float]]) -> str:
    for key in columns:
        normalized = _normalize_key(key)
        if "wavelength" in normalized or normalized in {"lambda", "nm"}:
            return key
    return next(iter(columns))


def _first_data_column(columns: dict[str, list[float]], *, exclude: set[str]) -> str:
    for key in columns:
        if key not in exclude:
            return key
    raise ValueError("CSV does not contain a spectral value column")


def _column_by_keywords(columns: dict[str, list[float]], keywords: tuple[str, ...]) -> str | None:
    for key in columns:
        normalized = _normalize_key(key)
        if any(keyword in normalized for keyword in keywords):
            return key
    return None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _name_from_path(path: Path, prefix: str) -> str:
    stem = path.stem
    if stem.startswith(prefix):
        stem = stem[len(prefix) :]
    return stem.replace("_", " ")
