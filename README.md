# Oil Storage Tank Image Analysis

Satellite imagery and computer vision to estimate floating-roof tank levels.

> This is an estimation and review workflow, not a direct inventory measurement.
> Absolute volume requires facility-specific calibration/strapping tables and
> analyst validation. Do not use low-confidence observations as a trading signal.

**Exploratory computer vision for alternative data in energy research.**

Can visible tank boundaries and floating-roof shadows provide useful inputs for estimating oil inventories? This project explores that question using Python and OpenCV.

**Status:** image-analysis prototype. The current notebook detects candidate tank circles, shadow contours and lid edges. It does **not** yet calculate a validated tank fill percentage.

[Explore the notebook](estimate_fill_level.ipynb) · [Dependencies](requirements.txt)

## What is implemented

- Image loading, grayscale conversion and Gaussian smoothing.
- Canny edge detection and Hough circle detection for candidate tank boundaries.
- Contour filtering using circularity, radius and distance from the tank centre.
- Ranking candidate lid-edge contours and visualising them over the source image.
- Configurable detection parameters and intermediate plots for inspection.

**Tools:** Python, OpenCV, NumPy and Matplotlib. The notebook also imports PySolar and defines tank geometry, location and timestamp inputs for the intended estimation workflow.

## Install


```bash
python -m pip install -r requirements.txt
python -m pip install jupyterlab
python -m jupyterlab
```

Open `estimate_fill_level.ipynb` from the repository folder. Review `IMAGE_PATH` and the detection parameters before executing cells.

**Known notebook issue:** the cell beginning `## 6b. Detect Shadow Contours Inside Tank Circles` contains explanatory prose but is marked as Code. Change that cell to Markdown before running the notebook from top to bottom.

## Interpretation and limitations

Detected circles and contours are candidate image features, not confirmed tank measurements. Results depend on image resolution, perspective, contrast and manually tuned thresholds.

The geometry, timestamp, coordinates and pixel scale in the notebook are example configuration values; they should not be treated as verified metadata for the included image. A fill-level calculation, ground-truth comparison and uncertainty analysis are still needed before making inventory claims.

## Next research steps

1. Validate tank and lid-edge detections against manually labelled images.
2. Incorporate verified image metadata, camera geometry and pixel calibration.
3. Implement and test the conversion from shadow geometry to roof height and fill level.
4. Quantify errors across tanks, viewing angles and lighting conditions.

The intended application is alternative-data research for energy markets. The current output is an exploratory visual analysis.

## Free imagery and accuracy

The CLI uses Copernicus Sentinel-2 L2A imagery through the public Microsoft
Planetary Computer STAC API when commercial imagery is unavailable. No API key
is required. Sentinel-2 has
10 m pixels in its best visible bands, so the imagery supports regional
screening and trend review, not accurate tank-wall or floating-lid edge
mapping. OpenStreetMap tank geometries are used to centre the crop and should
be visually verified.

There is no openly licensed, systematic sub-metre satellite archive covering
EU storage tanks. Any workflow claiming survey-grade lid edges from free
Sentinel-2 imagery would be misleading; use licensed high-resolution imagery
if that precision becomes a hard requirement.

## Automated satellite estimate

The focused CLI resolves a depot name, finds nearby mapped storage tanks, and
returns a JSON fill estimate:

```bash
python estimate_satellite_fill.py "Immingham oil terminal" --provider auto
```

For a verified tank coordinate, bypass depot discovery and supply optional
dimensions directly:

```bash
python estimate_satellite_fill.py \
  --latitude 53.61 --longitude -0.19 \
  --diameter-m 80 --height-m 22 \
  --provider sentinel
```

The coordinate must identify the tank centre, not merely the depot or town.
The pipeline rejects imagery when the detected circular feature is not centred
and at the expected scale for the supplied tank diameter.

`auto` uses `TANK_IMAGERY_URL_TEMPLATE` when configured for a commercial
orthorectified tile provider, then falls back to Sentinel-2 through Planetary
Computer. The URL template receives `latitude`, `longitude`, `start`, and
`end`; credentials should be handled by the provider or proxy and never placed
in source control. Use `--tank-id` after discovery when a depot has multiple
tanks.

The output contains `fill_percentage`, `certainty` (`High`, `Medium`, or
`Low`), a numeric certainty score, imagery provenance, solar elevation, and
diagnostics. It also writes an `inspection_overlay` PNG by default, or to the
path supplied with `--overlay-path`. The overlay shows the detected tank circle
in cyan, all candidate horizontal edge lines in orange, and the selected
lid/shadow boundary in green so the analyst can visually inspect the mapping.
Sentinel-2 results are explicitly marked as fallback imagery and
receive a confidence penalty. Tank dimensions from OpenStreetMap or image
inference are approximate; use facility calibration and high-resolution
imagery for operational decisions.

## Runtime contract

The pipeline is deliberately conservative:

- A depot name is resolved through Nominatim, then nearby OSM storage tanks are
  queried through several Overpass endpoints.
- Sentinel-2 STAC search selects a recent scene, but the downloaded image is a
  coordinate-centred Web Mercator tile rather than an unbounded scene preview.
- The selected tank must be centred in the tile. If a verified diameter is
  supplied, the detected circle must also be within the expected pixel scale.
- Missing imagery, an unrecognisable roof, a misplaced circle, or a scale
  mismatch returns an explicit `unavailable` result instead of a guessed fill.
- Sentinel-2 is 10 m imagery. A successful result is therefore screening-level
  even when the geometric validation passes; commercial sub-metre imagery and
  facility calibration are required for operational use.

The image analysis shares one circular-roof detection between measurement,
validation, and overlay generation. This keeps the reported percentage and
the review image tied to the same detected feature.

## Development checks

Run the focused test suite before committing:

```bash
python -m unittest discover -v
python -m py_compile satellite_fill.py estimate_satellite_fill.py test_satellite_fill.py
```

