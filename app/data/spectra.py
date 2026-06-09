"""Spectral data structures and interpolation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Spectrum:
    name: str
    wavelengths: list[float]
    values: list[float]
    kind: str = "unknown"
    source_path: str | None = None
    assumptions: list[str] = field(default_factory=list)

    def normalized(self, *, clamp: bool = True) -> "Spectrum":
        values = normalize_fraction_values(self.values, clamp=clamp)
        return Spectrum(
            name=self.name,
            wavelengths=list(self.wavelengths),
            values=values,
            kind=self.kind,
            source_path=self.source_path,
            assumptions=list(self.assumptions),
        )

    def interpolate(self, axis: Iterable[float], *, fill: float = 0.0) -> list[float]:
        return interpolate_values(self.wavelengths, self.values, list(axis), fill=fill)


@dataclass(frozen=True)
class FluorophoreSpectra:
    name: str
    excitation: Spectrum | None
    emission: Spectrum | None
    source_path: str


@dataclass(frozen=True)
class FilterSpectra:
    name: str
    aoi: int | None
    transmission: Spectrum | None
    reflection: Spectrum | None
    source_path: str


def normalize_fraction_values(values: Iterable[float], *, clamp: bool = True) -> list[float]:
    cleaned = [0.0 if value is None else float(value) for value in values]
    finite = [value for value in cleaned if value == value]
    if finite and max(abs(value) for value in finite) > 1.5:
        cleaned = [value / 100.0 for value in cleaned]
    if clamp:
        cleaned = [min(1.0, max(0.0, value)) for value in cleaned]
    return cleaned


def normalize_peak(values: Iterable[float]) -> list[float]:
    cleaned = [max(0.0, float(value)) for value in values]
    peak = max(cleaned, default=0.0)
    if peak <= 0:
        return cleaned
    return [value / peak for value in cleaned]


def interpolate_values(
    source_wavelengths: list[float],
    source_values: list[float],
    target_wavelengths: list[float],
    *,
    fill: float = 0.0,
) -> list[float]:
    if not source_wavelengths or not source_values:
        return [fill for _ in target_wavelengths]

    pairs = sorted(zip(source_wavelengths, source_values), key=lambda item: item[0])
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    result: list[float] = []
    index = 0
    last = len(xs) - 1

    for target in target_wavelengths:
        if target < xs[0] or target > xs[-1]:
            result.append(fill)
            continue
        while index < last - 1 and xs[index + 1] < target:
            index += 1
        x0, x1 = xs[index], xs[index + 1] if index < last else xs[index]
        y0, y1 = ys[index], ys[index + 1] if index < last else ys[index]
        if x1 == x0:
            result.append(y0)
        else:
            fraction = (target - x0) / (x1 - x0)
            result.append(y0 + fraction * (y1 - y0))
    return result


def default_wavelength_axis(start: int = 300, end: int = 900, step: int = 1) -> list[float]:
    if step <= 0:
        raise ValueError("step must be greater than zero")
    return [float(value) for value in range(start, end + 1, step)]

