import pytest

try:
    from data_exporter.exporter import CATEGORIES, SearchLightExporter
    from data_exporter.utils import (
        calculate_aoi_values,
        infer_standard_filter_aoi,
        safe_filename,
        sanitize_csv_headers,
        searchlight_payload_to_csv,
    )
except ModuleNotFoundError:
    from data_exporter.data_exporter.exporter import CATEGORIES, SearchLightExporter
    from data_exporter.data_exporter.utils import (
        calculate_aoi_values,
        infer_standard_filter_aoi,
        safe_filename,
        sanitize_csv_headers,
        searchlight_payload_to_csv,
    )


def test_calculate_aoi_values_default_zero() -> None:
    assert calculate_aoi_values(0) == list(range(0, 31))


def test_calculate_aoi_values_default_less_than_sweep() -> None:
    assert calculate_aoi_values(10) == list(range(0, 41))


def test_calculate_aoi_values_default_at_or_above_sweep() -> None:
    assert calculate_aoi_values(45) == list(range(15, 76))


def test_infer_standard_filter_aoi_for_dichroics() -> None:
    assert infer_standard_filter_aoi("Di01-R405/488/594") == 45
    assert infer_standard_filter_aoi("FF495-Di03") == 45
    assert infer_standard_filter_aoi("AF01-504/24") is None


def test_calculate_aoi_values_custom_step() -> None:
    assert calculate_aoi_values(10, sweep_degrees=5, step=2) == [5, 7, 9, 11, 13, 15]


def test_calculate_aoi_values_rejects_negative_default() -> None:
    with pytest.raises(ValueError):
        calculate_aoi_values(-1)


def test_safe_filename() -> None:
    assert safe_filename("FF495-Di03 / AOI 30 deg") == "FF495-Di03_AOI_30_deg"


def test_extract_static_category_list_stops_at_next_heading() -> None:
    body_text = """
    Fluorophores
    1. GFP
    2. mCherry
    Filters
    1. FF495-Di03
    Light Sources
    1. LED_470nm
    """

    assert SearchLightExporter._extract_static_category_list(body_text, "Fluorophores") == [
        "GFP",
        "mCherry",
    ]


def test_searchlight_payload_to_csv_from_text() -> None:
    payload = b"% Example\n# Metadata\n200.0\t0\n200.1\t42\n"

    assert searchlight_payload_to_csv(payload, "Example - Abs.txt") == (
        "wavelength_nm,Example_-_Abs\r\n"
        "200.0,0\r\n"
        "200.1,42\r\n"
    )


def test_sanitize_csv_headers() -> None:
    assert sanitize_csv_headers("Wavelength (nm),Alexa Fluor 594 - Abs\n500,1\n") == (
        "wavelength_nm,Alexa_Fluor_594_-_Abs\r\n"
        "500,1\r\n"
    )


def test_filter_expected_paths_for_dichroic_range() -> None:
    exporter = SearchLightExporter(sweep_degrees=1, sweep_step=1)

    names = [
        path.name
        for path in exporter._filter_expected_paths(
            CATEGORIES["filters"],
            "Di01-R405/488/594",
            45,
        )
    ]

    assert names == [
        "searchlight_filter_Di01-R405_488_594_AOI_default.csv",
        "searchlight_filter_Di01-R405_488_594_AOI_44deg.csv",
        "searchlight_filter_Di01-R405_488_594_AOI_45deg.csv",
        "searchlight_filter_Di01-R405_488_594_AOI_46deg.csv",
    ]
