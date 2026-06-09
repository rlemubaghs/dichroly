from app.analysis.aoi_analysis import build_aoi_curves, requested_aoi_values
from app.analysis.calculations import SelectedFilter, calculate_spectral_result
from app.data.spectra import FilterSpectra, FluorophoreSpectra, Spectrum


def test_filter_stack_with_light_source() -> None:
    axis = [500.0, 501.0]
    light = Spectrum("Light", axis, [0.5, 1.0])
    transmission = Spectrum("Filter T", axis, [0.5, 0.2])
    selected_filter = SelectedFilter("Filter", FilterSpectra("Filter", 0, transmission, None, "filter.csv"), "transmission", 0)

    result = calculate_spectral_result(light_source=light, filters=[selected_filter], fluorophore=None, axis=axis)

    assert result.final_curves[0].values == [0.25, 0.2]


def test_multiple_light_sources_are_additive() -> None:
    axis = [500.0]
    result = calculate_spectral_result(
        light_source=[Spectrum("A", axis, [0.2]), Spectrum("B", axis, [0.3])],
        filters=[],
        fluorophore=None,
        axis=axis,
    )

    assert result.final_curves[0].values == [0.5]


def test_reflection_falls_back_to_one_minus_transmission() -> None:
    axis = [500.0]
    transmission = Spectrum("Filter T", axis, [0.25])
    selected_filter = SelectedFilter("Filter", FilterSpectra("Filter", 0, transmission, None, "filter.csv"), "reflection", 0)

    result = calculate_spectral_result(light_source=None, filters=[selected_filter], fluorophore=None, axis=axis)

    assert result.final_curves[0].values == [0.75]
    assert "reflection estimated" in result.warnings[0]


def test_fluorophore_excitation_and_emission_results() -> None:
    axis = [500.0]
    fluor = FluorophoreSpectra(
        "Fluor",
        Spectrum("Exc", axis, [0.5]),
        Spectrum("Em", axis, [0.75]),
        "fluor.csv",
    )
    result = calculate_spectral_result(light_source=None, filters=[], fluorophore=fluor, axis=axis)

    assert [curve.name for curve in result.final_curves] == [
        "Excitation reaching tissue",
        "Emission returning through optical path",
    ]
    assert result.final_curves[0].values == [0.5]
    assert result.final_curves[1].values == [0.75]


def test_fluorophore_excitation_is_independent_of_light_source() -> None:
    axis = [500.0]
    light = Spectrum("Light", axis, [0.2])
    transmission = Spectrum("Filter T", axis, [0.5])
    selected_filter = SelectedFilter("Filter", FilterSpectra("Filter", 0, transmission, None, "filter.csv"), "transmission", 0)
    fluor = FluorophoreSpectra(
        "Fluor",
        Spectrum("Exc", axis, [0.8]),
        Spectrum("Em", axis, [0.6]),
        "fluor.csv",
    )

    result = calculate_spectral_result(light_source=light, filters=[selected_filter], fluorophore=fluor, axis=axis)

    assert [curve.kind for curve in result.final_curves] == ["result_light_source", "result_excitation", "result_emission"]
    assert result.final_curves[0].values == [0.1]
    assert result.final_curves[1].values == [0.4]
    assert result.final_curves[2].values == [0.3]


def test_requested_aoi_values_clamps_negative_start() -> None:
    assert requested_aoi_values(-10, 2, 1, default_orientation=0) == [0, 1, 2]


def test_aoi_interpolation_between_available_files() -> None:
    axis = [500.0]
    low = FilterSpectra("Filter", 0, Spectrum("T0", axis, [0.0]), None, "0.csv")
    high = FilterSpectra("Filter", 10, Spectrum("T10", axis, [1.0]), None, "10.csv")

    curves, warnings = build_aoi_curves({0: low, 10: high}, filter_name="Filter", aoi_values=[5], mode="transmission", axis=axis)

    assert warnings == []
    assert curves[0].spectrum.values == [0.5]
    assert curves[0].warning == "interpolated between nearby AOI files"
