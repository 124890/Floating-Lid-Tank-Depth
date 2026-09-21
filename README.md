# Oil Storage Tank Image Analysis

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

## Repository guide

| File | Purpose |
| --- | --- |
| [estimate_fill_level.ipynb](estimate_fill_level.ipynb) | Exploratory image-processing workflow and saved visual outputs |
| [image.PNG](image.PNG) | Included example image |
| [requirements.txt](requirements.txt) | Python library dependencies |

## Explore locally

Clone or download this repository. In a Python 3.9+ environment, install the dependencies and a notebook interface:

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
