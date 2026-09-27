# Satellite imagery pipeline for oil-storage research

A Python command-line prototype that connects tank discovery, satellite imagery, computer vision and reviewable JSON output.

**Status:** research prototype. The reported `fill_percentage` is an uncalibrated image-gradient heuristic. It has not been validated against measured tank levels. The project demonstrates an integration and image-analysis workflow.

[Quick start](#quick-start) · [Architecture](#architecture) · [Tests](#tests) · [Limitations](#limitations)

## What the project does

Given a depot name or tank coordinates, the pipeline:

1. Resolves a depot using Nominatim and discovers nearby mapped storage tanks through OpenStreetMap Overpass.
2. Searches Sentinel-2 imagery through Microsoft Planetary Computer, or uses a configured commercial imagery URL template.
3. Detects a candidate circular roof with OpenCV and computes an exploratory image-gradient proxy.
4. Checks the detected feature's position and, where metadata permits, approximate scale.
5. Produces JSON with imagery provenance, diagnostics and heuristic quality indicators, plus an image overlay for review.

The implementation separates network providers from the estimator so image analysis can be exercised with local fixtures.

## Quick start

Use Python 3.10 or later from the repository root:

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python estimate_satellite_fill.py --help
```

Run discovery and imagery retrieval:

```bash
python estimate_satellite_fill.py "Immingham oil terminal" --provider sentinel
```

This command makes requests to external services. Coverage, service availability, image resolution and feature detection can prevent a result. By default the CLI chooses the first discovered tank; use `--tank-id` to select a known OSM candidate.

For a verified tank centre, supply both coordinates:

```bash
python estimate_satellite_fill.py \
  --latitude YOUR_TANK_LATITUDE --longitude YOUR_TANK_LONGITUDE \
  --diameter-m YOUR_TANK_DIAMETER --height-m YOUR_TANK_HEIGHT \
  --provider sentinel --overlay-path inspection.png
```

Replace the capitalised placeholders with numeric measurements. A depot or town coordinate is not sufficient to identify an individual tank. The default search window is 30 days; change it with `--days`.

## Architecture

| File | Responsibility |
| --- | --- |
| [estimate_satellite_fill.py](estimate_satellite_fill.py) | CLI arguments, provider selection, error handling and JSON output |
| [satellite_fill.py](satellite_fill.py) | Tank discovery, imagery adapters, circle detection, heuristic measurement and overlay generation |
| [test_satellite_fill.py](test_satellite_fill.py) | Unit tests using synthetic images and mocked provider responses |
| [requirements.txt](requirements.txt) | OpenCV, NumPy, PySolar and requests dependencies |

`TankCandidate`, `ImageryScene` and `ShadowMeasurement` hold the main inputs and outputs. `estimate_scene` assembles the result and applies position and scale checks.

The CLI supports `sentinel`, `commercial` and `auto`. In `auto` mode it tries the configured commercial adapter first, then Sentinel-2 when that adapter returns no scenes. A provider request exception exits with an unavailable result.

## Output and diagnostics

Successful output includes:

- `tank` and `imagery`: candidate metadata and imagery provenance.
- `fill_percentage`: the exploratory proxy output.
- `certainty` and `certainty_score`: heuristic image-quality indicators, not calibrated probabilities or confidence intervals.
- `diagnostics`, `solar_elevation_degrees` and `target_validation`: review information.
- `inspection_overlay`: path and geometry for the generated review image.

The overlay uses cyan for the detected circle, orange for candidate horizontal edges and green for the selected boundary. If no candidate edge is found, the green line is inferred from the proxy. Its presence alone does not establish that a physical lid boundary was detected.

Handled discovery, provider and measurement failures produce an `unavailable` JSON result and a non-zero exit. Some invalid selections, including no discovered tanks, exit with a text message.

## Tests

```bash
python -m unittest discover -v
python -m py_compile satellite_fill.py estimate_satellite_fill.py test_satellite_fill.py
```

The seven unit tests cover quality-label thresholds, bounded outputs on a synthetic roof, the coarse-imagery penalty, overlay creation, scale rejection, commercial crop metadata and a mocked Sentinel tile request. These checks exercise software behaviour; they do not establish real-world estimation accuracy.

## Imagery configuration

`--provider auto` uses `TANK_IMAGERY_URL_TEMPLATE` when configured. The template accepts `latitude`, `longitude`, `start`, `end` and `bbox` placeholders. Keep credentials in your environment or provider proxy, outside source control.

The commercial adapter currently assumes 0.5 m resolution and uses the end of the search window as the observation time. A production integration would need the actual resolution, acquisition time and georeferencing from the provider.

The Sentinel adapter requests the Web Mercator tile containing the coordinate. It does not re-centre that tile around the tank, while the estimator currently uses the image centre as its target. This mismatch needs correcting before relying on tank identity checks.

## Limitations

- The fill proxy uses image gradients with fixed coefficients. Solar elevation is recorded and affects the quality penalty; it is not used in a calibrated shadow-to-height model.
- Sentinel-2's 10 m imagery is too coarse for precise floating-roof edge measurement. Resampling a display tile does not create additional spatial detail.
- Missing tank dimensions are inferred. Mapped tanks may have incomplete dimensions or unsuitable roof types.
- Position and scale checks reduce some mismatches but do not prove the detected feature belongs to the intended tank.
- Dependencies are currently unpinned. External-service behaviour and compatibility may change.
- There is no measured accuracy benchmark, operational deployment or trading-performance claim in this repository.

## Next development priorities

Obtain labelled high-resolution imagery with verified acquisition metadata and tank measurements. Correct the coordinate-to-pixel mapping, replace the heuristic with a physically justified estimator, and evaluate errors on held-out tanks and dates. Calibrate uncertainty and expand failure-case tests before considering operational use.
