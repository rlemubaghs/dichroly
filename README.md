# Dichroly

Dichroly is a Python desktop app for exploring spectral combinations of light sources, optical filters, and fluorophores. 

## Install

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python -m app.main
```

By default, Dichroly reads and writes spectral CSVs in `data/`:

```text
data/
  fluorophores/
  filters/
  light_sources/
```

Use a different cache folder with:

```bash
python -m app.main --data-root /path/to/data
```

## Data

CSV filenames should include a source prefix:

```text
searchlight_fluorophore_<name>.csv
searchlight_light_source_<name>.csv
searchlight_filter_<name>_AOI_default.csv
searchlight_filter_<name>_AOI_05deg.csv
```

## Manual data format

Use a source prefix at the start of the filename so files can be filtered by origin. For manually created files, choose a short source name such as "manual", "lab", or "vendor".

Fluorophores:

```text
manual_fluorophore_my_Fluorophore.csv
```

Light sources:

```text
manual_light_source_my_LED.csv
```

Filters:

```text
manual_filter_My_Filter_AOI_default.csv
manual_filter_My_Filter_AOI_00deg.csv
manual_filter_My_Filter_AOI_45deg.csv
```

Use plain CSV text with a header row. The first column must be wavelength in nm.
Dichroly recognizes headers such as:

```text
wavelength_nm
wavelength
lambda
nm
```

Values may be fractions from 0 to 1 or percentages from 0 to 100. Percent-like filter values are converted to fractions internally.

CSV example:

```csv
wavelength_nm,transmission
400,0.01
450,0.82
500,0.91
```

Optional filter columns:

```text
transmission
reflection
```

If reflection is missing and the app needs reflection mode, it estimates reflection as 1 - transmission.

Fluorophore CSV example

```csv
wavelength_nm,excitation,emission
400,0.10,0.00
450,1.00,0.05
500,0.35,0.70
550,0.02,1.00
```

Recognized fluorophore columns include excitation, excitation_norm, emission, and emission_norm.

Light source CSV example:

```csv
wavelength_nm,intensity
430,0.10
450,1.00
470,0.35
```

Recognized light source columns include intensity, power, output, spectrum, and relative_intensity.

## App Tabs

### Explorer

- Select one light source, one fluorophore, and any number of filters.
- Choose each filter's mode: `transmission`, `reflection`, `visualize`, or `excluded`.
- Enter AOI values directly.
- Plot selected spectra live.
- Calculate final curves for excitation, emission, and light-source throughput.

### AOI Analysis

- Uses each filter's current AOI +/- range and step.
- Shows one AOI comparison plot per included filter.
- Shows calculated result curves for AOI combinations.
- Displays area-under-curve tables and plots per included filter.

### Downloads

- Download the requested AOI files into `data/filters/`.

## Calculations

Spectra are interpolated onto a shared wavelength axis. Filter percentages are converted to fractions, invalid values are clipped where appropriate, and light-source/fluorophore curves are normalized.

Filter stack:

```text
combined_filter = filter_1 * filter_2 * ...
```

Transmission mode uses transmission data. Reflection mode uses explicit reflection data when present; otherwise it estimates reflection as:

```text
reflection = 1 - transmission
```

Explorer calculated curves:

```text
excitation = combined_filter * fluorophore_excitation
emission = combined_filter * fluorophore_emission
light_source = combined_filter * selected_light_source
```

## Data Exporter

`data_exporter` downloads spectral CSV files into the main `data/` cache. It is written so more data sources can be added later; the currently implemented sources are:

- `searchlight`: IDEX SearchLight at https://searchlight.idex-hs.com

### Install

From the `data_exporter` folder:

```bash
cd data_exporter
pip install -r requirements.txt
python -m playwright install chromium
```

### Run

Use the convenience script:

```bash
./export_all_data.sh
```

The script runs all supported categories and, for filters, performs an AOI sweep. By default:

```text
AOI sweep: +/- 30 degrees, step 1 degree
```

You can change the default sweep with environment variables:

```bash
AOI_SWEEP_DEGREES=15 AOI_SWEEP_STEP=5 ./export_all_data.sh
```

Common options:

```bash
./export_all_data.sh --headed       visible Chromium window for debugging
./export_all_data.sh --limit 3      only downloads 3 filters
./export_all_data.sh --overwrite    overwrites existing CSV files
```

### Direct Commands

Run commands from inside `data_exporter/`:

```bash
python -m data_exporter.exporter --all --source searchlight
python -m data_exporter.exporter --fluorophores --source searchlight
python -m data_exporter.exporter --filters --source searchlight
python -m data_exporter.exporter --light-sources --source searchlight
python -m data_exporter.exporter --filters --source searchlight --aoi-sweep 30 1
```

Useful flags:

```text
--headed                show Chromium
--limit N               export only the first N discovered items per category
--overwrite             re-download files that already exist
--timeout-ms N          Playwright timeout
--retries N             retry count per item/AOI after the first attempt
--source searchlight    source prefix for output filenames
```

### Output

CSV files are saved in the main project data cache:

```text
../data/fluorophores/
../data/filters/
../data/light_sources/
```

Filenames include the source prefix:

```text
searchlight_fluorophore_<name>.csv
searchlight_light_source_<name>.csv
searchlight_filter_<name>_AOI_default.csv
searchlight_filter_<name>_AOI_00deg.csv
```

### AOI Sweep

For filters, the exporter first downloads the default SearchLight orientation. It then downloads absolute AOI values around the inferred/default filter angle using the following rules:

- AOI values are absolute angles.
- AOI values never go below 0.
- With the default `--aoi-sweep 30 1`, a filter centered at 0 exports 0..30.
- With the default `--aoi-sweep 30 1`, a filter centered at 10 exports 0..40.
- With the default `--aoi-sweep 30 1`, a filter centered at 45 exports 15..75.
- Dichroic-style filters such as `Di01-R405/488/594` and `FF495-Di03` are treated as standard `45` degree AOI filters.

### Notes

The exporter uses Playwright to drive SearchLight and download one plotted spectrum at a time. It also removes the SearchLight cookie overlay when needed, because that overlay can block automated clicks in headless Chromium.

Run tests from this folder with:

```bash
python -m pytest
```
