from pathlib import Path

from app.data.catalog import build_catalog
from app.data.loaders import load_filter, load_fluorophore


def test_catalog_groups_filter_aois(tmp_path: Path) -> None:
    folder = tmp_path / "filters"
    folder.mkdir()
    (folder / "filter_AF01-584_40_AOI_default.csv").write_text("wavelength_nm,AF01\n500,1\n", encoding="utf-8")
    (folder / "filter_AF01-584_40_AOI_01deg.csv").write_text("wavelength_nm,AF01\n500,1\n", encoding="utf-8")

    catalog = build_catalog(tmp_path)

    item = catalog.filters["AF01-584 40"]
    assert item.has_default_aoi
    assert item.aoi_values == (1,)
    assert item.default_aoi == 0
    assert len(item.local_files) == 2


def test_catalog_infers_dichroic_default_aoi(tmp_path: Path) -> None:
    folder = tmp_path / "filters"
    folder.mkdir()
    (folder / "filter_Di01-R488_AOI_default.csv").write_text("wavelength_nm,Di01\n500,1\n", encoding="utf-8")
    (folder / "filter_Di01-R488_AOI_45deg.csv").write_text("wavelength_nm,Di01\n500,1\n", encoding="utf-8")

    catalog = build_catalog(tmp_path)

    assert catalog.filters["Di01-R488"].default_aoi == 45


def test_catalog_accepts_source_prefixed_files(tmp_path: Path) -> None:
    filters = tmp_path / "filters"
    filters.mkdir()
    fluorophores = tmp_path / "fluorophores"
    fluorophores.mkdir()
    lights = tmp_path / "light_sources"
    lights.mkdir()
    filter_path = filters / "searchlight_filter_AF01-584_40_AOI_05deg.csv"
    fluor_path = fluorophores / "searchlight_fluorophore_GFP.csv"
    light_path = lights / "searchlight_light_source_LED_470.csv"
    filter_path.write_text("wavelength_nm,AF01\n500,1\n", encoding="utf-8")
    fluor_path.write_text("wavelength_nm,excitation,emission\n500,1,0\n", encoding="utf-8")
    light_path.write_text("wavelength_nm,intensity\n500,1\n", encoding="utf-8")

    catalog = build_catalog(tmp_path)

    assert catalog.filters["AF01-584 40"].aoi_values == (5,)
    assert catalog.fluorophores["GFP"].local_files == (fluor_path,)
    assert catalog.light_sources["LED 470"].local_files == (light_path,)


def test_catalog_merges_remote_light_source_punctuation_with_local_file(tmp_path: Path) -> None:
    folder = tmp_path / "light_sources"
    folder.mkdir()
    path = folder / "light_source_1041_Laser_DPSS_Synthetic.csv"
    path.write_text("wavelength_nm,1041 Laser DPSS (Synthetic)\n500,1\n", encoding="utf-8")

    catalog = build_catalog(tmp_path, {"light_sources": ["1041 Laser DPSS (Synthetic)"]})

    assert "1041 Laser DPSS (Synthetic)" in catalog.light_sources
    assert "1041 Laser DPSS Synthetic" not in catalog.light_sources
    assert catalog.light_sources["1041 Laser DPSS (Synthetic)"].local_files == (path,)


def test_load_filter_normalizes_percent_values(tmp_path: Path) -> None:
    path = tmp_path / "filter_Test_AOI_00deg.csv"
    path.write_text("wavelength_nm,Transmission\n500,50\n501,100\n", encoding="utf-8")

    spectra = load_filter(path)

    assert spectra.transmission is not None
    assert spectra.transmission.values == [0.5, 1.0]


def test_load_fluorophore_detects_excitation_and_emission(tmp_path: Path) -> None:
    path = tmp_path / "fluorophore_Test.csv"
    path.write_text("wavelength_nm,Test Abs,Test Em\n500,0,0\n510,10,20\n", encoding="utf-8")

    spectra = load_fluorophore(path)

    assert spectra.excitation is not None
    assert spectra.emission is not None
    assert spectra.excitation.values == [0.0, 1.0]
    assert spectra.emission.values == [0.0, 1.0]
