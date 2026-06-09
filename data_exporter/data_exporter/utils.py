"""Utility helpers for the SearchLight exporter."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Iterable


def safe_filename(value: str, max_length: int = 120) -> str:
    value = value.strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9._+-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    if not value:
        return "unnamed"
    return value[:max_length].rstrip("._") or "unnamed"


def calculate_aoi_values(
    default_aoi: int | float,
    sweep_degrees: int = 30,
    step: int = 1,
) -> list[int]:
    if step <= 0:
        raise ValueError("step must be greater than 0")
    if sweep_degrees < 0:
        raise ValueError("sweep_degrees must be 0 or greater")
    if default_aoi < 0:
        raise ValueError("default_aoi must be 0 or greater")

    rounded_default = int(round(default_aoi))
    start = max(0, rounded_default - sweep_degrees)
    end = rounded_default + sweep_degrees
    return list(range(start, end + 1, step))


def infer_standard_filter_aoi(filter_name: str) -> int | None:
    normalized = filter_name.strip()
    if re.match(r"^Di\d+", normalized, re.IGNORECASE):
        return 45
    if re.search(r"(?:^|[-_])Di\d+", normalized, re.IGNORECASE):
        return 45
    return None


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def looks_like_csv(text: str) -> bool:
    sample = text.strip()
    if not sample:
        return False
    if "," not in sample and "\t" not in sample:
        return False
    try:
        dialect = csv.Sniffer().sniff(sample[:2048], delimiters=",\t;")
    except csv.Error:
        return False
    first_line = sample.splitlines()[0]
    return dialect.delimiter in first_line


def searchlight_payload_to_csv(payload: bytes, suggested_name: str = "") -> str:
    spectra: list[tuple[str, dict[str, str]]] = []

    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.namelist():
                if member.endswith("/") or not member.lower().endswith(".txt"):
                    continue
                text = archive.read(member).decode("utf-8-sig", errors="replace")
                label = safe_filename(Path(member).stem)
                spectra.append((label, parse_searchlight_spectrum_text(text)))
    else:
        text = payload.decode("utf-8-sig", errors="replace")
        label = safe_filename(Path(suggested_name).stem or "spectrum")
        spectra.append((label, parse_searchlight_spectrum_text(text)))

    spectra = [(label, values) for label, values in spectra if values]
    if not spectra:
        raise ValueError("Downloaded payload did not contain spectral wavelength/value rows")

    wavelengths = sorted(
        {wavelength for _, values in spectra for wavelength in values},
        key=lambda value: float(value),
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["wavelength_nm", *[label for label, _ in spectra]])
    for wavelength in wavelengths:
        writer.writerow([wavelength, *[values.get(wavelength, "") for _, values in spectra]])
    return output.getvalue()


def sanitize_csv_headers(csv_text: str) -> str:
    sample = csv_text.strip()
    if not sample:
        return csv_text
    try:
        dialect = csv.Sniffer().sniff(sample[:2048], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel

    input_buffer = io.StringIO(csv_text)
    reader = csv.reader(input_buffer, dialect=dialect)
    rows = list(reader)
    if not rows:
        return csv_text

    headers = rows[0]
    normalized_headers: list[str] = []
    for index, header in enumerate(headers):
        normalized = re.sub(r"[^a-z0-9]+", "", header.lower())
        if index == 0 or "wavelength" in normalized or normalized in {"lambda", "nm"}:
            normalized_headers.append("wavelength_nm")
        else:
            normalized_headers.append(safe_filename(header or f"spectrum_{index}"))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(normalized_headers)
    writer.writerows(rows[1:])
    return output.getvalue()


def parse_searchlight_spectrum_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("%", "#")):
            continue
        parts = re.split(r"[\t,; ]+", line)
        if len(parts) < 2:
            continue
        try:
            float(parts[0])
            float(parts[1])
        except ValueError:
            continue
        values[parts[0]] = parts[1]
    return values
