"""Build a local catalog from downloaded CSV files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CatalogItem:
    name: str
    category: str
    local_files: tuple[Path, ...] = ()
    available_remote: bool = False
    sources: tuple[str, ...] = ()
    aoi_values: tuple[int, ...] = ()
    has_default_aoi: bool = False
    default_aoi: int | None = None

    @property
    def is_local(self) -> bool:
        return bool(self.local_files)

    @property
    def source_label(self) -> str:
        if self.is_local and self.available_remote:
            return "Local CSV + SearchLight online"
        if self.is_local:
            return "Local CSV"
        if self.available_remote:
            return "SearchLight online"
        return "Unknown"


@dataclass
class Catalog:
    fluorophores: dict[str, CatalogItem] = field(default_factory=dict)
    filters: dict[str, CatalogItem] = field(default_factory=dict)
    light_sources: dict[str, CatalogItem] = field(default_factory=dict)
    source_message: str = "Using local cache."

    def category(self, key: str) -> dict[str, CatalogItem]:
        return {
            "fluorophores": self.fluorophores,
            "filters": self.filters,
            "light_sources": self.light_sources,
        }[key]

    def find(self, key: str, name: str) -> CatalogItem | None:
        items = self.category(key)
        found_name = _find_catalog_name(items, name)
        return items.get(found_name) if found_name else None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_download_root() -> Path:
    root = project_root()
    for candidate in (root / "data", legacy_data_exporter_data_root()):
        if candidate.exists():
            return candidate
    return root / "data"


def default_data_root() -> Path:
    return project_root() / "data"


def legacy_data_exporter_data_root() -> Path:
    return project_root() / "data_exporter" / "data"


def build_catalog(download_root: Path, remote_options: dict[str, list[str]] | None = None) -> Catalog:
    remote_options = remote_options or {}
    catalog = Catalog()
    _merge_local(catalog, "fluorophores", _scan_simple(download_root / "fluorophores", "fluorophore_"))
    _merge_local(catalog, "light_sources", _scan_simple(download_root / "light_sources", "light_source_"))
    _merge_local(catalog, "filters", _scan_filters(download_root / "filters"))

    for category, names in remote_options.items():
        target = catalog.category(category)
        for name in names:
            existing_name = _find_catalog_name(target, name)
            item = target.get(existing_name) if existing_name else None
            if item:
                if existing_name and existing_name != name:
                    target.pop(existing_name)
                target[name] = CatalogItem(
                    name=name,
                    category=item.category,
                    local_files=item.local_files,
                    available_remote=True,
                    sources=_merge_sources(item.sources, ("searchlight",)),
                    aoi_values=item.aoi_values,
                    has_default_aoi=item.has_default_aoi,
                    default_aoi=item.default_aoi,
                )
            else:
                target[name] = CatalogItem(name=name, category=category, available_remote=True, sources=("searchlight",))
    return catalog


def _merge_local(catalog: Catalog, category: str, items: dict[str, CatalogItem]) -> None:
    target = catalog.category(category)
    target.update(items)


def _find_catalog_name(items: dict[str, CatalogItem], candidate: str) -> str | None:
    if candidate in items:
        return candidate
    candidate_key = _canonical_catalog_key(candidate)
    for name in items:
        if _canonical_catalog_key(name) == candidate_key:
            return name
    return None


def _merge_sources(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left, *right)))


def _scan_simple(folder: Path, prefix: str) -> dict[str, CatalogItem]:
    items: dict[str, CatalogItem] = {}
    if not folder.exists():
        return items
    for path in sorted(folder.glob("*.csv")):
        name = _display_name_from_stem(_strip_source_prefix(path.stem), prefix)
        existing = items.get(name)
        files = tuple(sorted(((existing.local_files if existing else ()) + (path,))))
        items[name] = CatalogItem(name=name, category=folder.name, local_files=files, sources=("local",))
    return items


def _scan_filters(folder: Path) -> dict[str, CatalogItem]:
    grouped: dict[str, list[Path]] = {}
    if not folder.exists():
        return {}
    for path in sorted(folder.glob("*.csv")):
        name, _ = parse_filter_filename(path)
        grouped.setdefault(name, []).append(path)

    items: dict[str, CatalogItem] = {}
    for name, files in grouped.items():
        aois = sorted(aoi for file in files for aoi in [parse_filter_filename(file)[1]] if aoi is not None)
        has_default = any("_AOI_default" in file.stem for file in files)
        items[name] = CatalogItem(
            name=name,
            category="filters",
            local_files=tuple(sorted(files)),
            sources=("local",),
            aoi_values=tuple(aois),
            has_default_aoi=has_default,
            default_aoi=_infer_default_filter_aoi(name, aois, has_default),
        )
    return items


def parse_filter_filename(path: Path) -> tuple[str, int | None]:
    stem = _strip_source_prefix(path.stem)
    if stem.startswith("filter_"):
        stem = stem[len("filter_") :]
    aoi: int | None = None
    match = re.search(r"_AOI_(default|(\d+)deg)$", stem)
    if match:
        if match.group(2) is not None:
            aoi = int(match.group(2))
        stem = stem[: match.start()]
    return _display_name_from_stem(stem, ""), aoi


def safe_name(value: str) -> str:
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[^A-Za-z0-9._+-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    return value


def _canonical_catalog_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _infer_default_filter_aoi(name: str, aoi_values: list[int], has_default: bool) -> int | None:
    if re.match(r"^Di\d+", name, re.IGNORECASE) or re.search(r"(?:^|[-_ ])Di\d+", name, re.IGNORECASE):
        return 45
    if not has_default:
        return None
    if not aoi_values:
        return 0
    return max(0, max(aoi_values) - 30)


def _display_name_from_stem(stem: str, prefix: str) -> str:
    if prefix and stem.startswith(prefix):
        stem = stem[len(prefix) :]
    return stem.replace("_", " ").strip()


def _strip_source_prefix(stem: str) -> str:
    if stem.startswith(("filter_", "fluorophore_", "light_source_")):
        return stem
    match = re.match(r"^[A-Za-z0-9+-]+_((?:filter|fluorophore|light_source)_.+)$", stem)
    if match:
        return match.group(1)
    return stem
