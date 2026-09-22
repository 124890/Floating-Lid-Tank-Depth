"""Depot discovery, imagery selection, and floating-lid shadow estimation.

The module deliberately keeps network access behind small provider functions so
the image estimator can be tested with local fixtures and used with licensed
imagery without changing the measurement code.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
from pysolar.solar import get_altitude

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)


@dataclass(frozen=True)
class TankCandidate:
    identifier: str
    latitude: float
    longitude: float
    diameter_m: float | None
    height_m: float | None
    source: str


@dataclass(frozen=True)
class ImageryScene:
    image_url: str
    observed_at: datetime
    resolution_m: float
    provider: str
    cloud_fraction: float | None
    fallback: bool
    scene_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ShadowMeasurement:
    lid_fraction: float
    lid_height_m: float
    solar_elevation_degrees: float
    quality_score: float
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class OverlayDetections:
    tank_circle: tuple[int, int, int]
    candidate_edges: tuple[tuple[int, int, int, int], ...]
    selected_boundary: tuple[int, int, int, int]

def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("latitude/longitude are outside valid ranges")


def discover_tanks(
    depot: str,
    *,
    geocoder_url: str = "https://nominatim.openstreetmap.org/search",
    overpass_url: str | None = None,
    timeout_seconds: int = 20,
) -> list[TankCandidate]:
    """Resolve a depot and return nearby mapped storage tanks.

    OSM geometry is useful for discovery and scale, but its dimensions are
    treated as estimates and never presented as survey-grade metadata.
    """

    headers = {"User-Agent": "floating-lid-tank-depth/1.0"}
    geocode = requests.get(
        geocoder_url,
        params={"q": depot, "format": "jsonv2", "limit": 1},
        headers=headers,
        timeout=timeout_seconds,
    )
    geocode.raise_for_status()
    locations = geocode.json()
    if not locations:
        raise LookupError(f"No location found for depot: {depot}")
    latitude = float(locations[0]["lat"])
    longitude = float(locations[0]["lon"])
    query = f"""
    [out:json][timeout:25];
    (
      way(around:3000,{latitude},{longitude})["man_made"="storage_tank"];
      way(around:3000,{latitude},{longitude})["industrial"="oil_tank"];
      node(around:3000,{latitude},{longitude})["man_made"="storage_tank"];
    );
    out center tags;
    """
    endpoints = (overpass_url,) if overpass_url else OVERPASS_ENDPOINTS
    response = None
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            candidate_response = requests.get(
                endpoint, params={"data": query}, headers=headers, timeout=timeout_seconds
            )
            candidate_response.raise_for_status()
            response = candidate_response
            break
        except requests.RequestException as error:
            errors.append(f"{endpoint}: {error}")
    if response is None:
        raise requests.RequestException(
            "All Overpass endpoints failed: " + "; ".join(errors)
        )
    candidates: list[TankCandidate] = []
    for element in response.json().get("elements", []):
        center = element.get("center", element)
        if "lat" not in center or "lon" not in center:
            continue
        tags = element.get("tags", {})
        diameter = _positive_float(tags.get("diameter"))
        if diameter is None:
            diameter = _positive_float(tags.get("building:diameter"))
        height = _positive_float(tags.get("height"))
        candidates.append(
            TankCandidate(
                identifier=f"osm-{element['type']}-{element['id']}",
                latitude=float(center["lat"]),
                longitude=float(center["lon"]),
                diameter_m=diameter,
                height_m=height,
                source="openstreetmap",
            )
        )
    return candidates


def _positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).split()[0])
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class PlanetaryComputerProvider:
    """Sentinel-2 STAC search returning preview assets.

    Sentinel-2 previews are intentionally marked as fallback/coarse imagery.
    They are suitable for screening and trend review, not precise lid mapping.
    """

    stac_url = "https://planetarycomputer.microsoft.com/api/stac/v1/search"

    def __init__(
        self,
        *,
        timeout_seconds: int = 30,
        zoom: int = 16,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.zoom = zoom

    def search(
        self, latitude: float, longitude: float, start: datetime, end: datetime
    ) -> list[ImageryScene]:
        _validate_coordinates(latitude, longitude)
        response = requests.post(
            self.stac_url,
            json={
                "collections": ["sentinel-2-l2a"],
                "intersects": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "datetime": f"{start.isoformat()}/{end.isoformat()}",
                "limit": 10,
                "query": {"eo:cloud_cover": {"lt": 60}},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        scenes: list[ImageryScene] = []
        for feature in response.json().get("features", []):
            assets = feature.get("assets", {})
            preview = assets.get("rendered_preview") or assets.get("thumbnail")
            if not preview or "href" not in preview:
                continue
            scene_id = str(feature.get("id", ""))
            tile_x, tile_y = _web_mercator_tile(latitude, longitude, self.zoom)
            bbox = _tile_bbox(tile_x, tile_y, self.zoom)
            preview_url = _tile_url(
                scene_id=scene_id,
                tile_x=tile_x,
                tile_y=tile_y,
                zoom=self.zoom,
                fallback_url=preview["href"],
            )
            observed_at = datetime.fromisoformat(
                feature["properties"]["datetime"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            scenes.append(
                ImageryScene(
                    image_url=preview_url,
                    observed_at=observed_at,
                    resolution_m=10.0,
                    provider="sentinel-2-planetary-computer",
                    cloud_fraction=float(
                        feature.get("properties", {}).get("eo:cloud_cover", 100)
                    )
                    / 100,
                    fallback=True,
                    scene_id=scene_id or None,
                    bbox=bbox,
                )
            )
        return scenes


class CommercialTileProvider:
    """Adapter for providers exposing a URL template for orthorectified tiles."""

    def __init__(
        self,
        *,
        url_template: str | None = None,
        resolution_m: float = 0.5,
        provider_name: str = "commercial",
    ) -> None:
        self.url_template = url_template or os.getenv("TANK_IMAGERY_URL_TEMPLATE")
        self.resolution_m = resolution_m
        self.provider_name = provider_name

    def search(
        self, latitude: float, longitude: float, start: datetime, end: datetime
    ) -> list[ImageryScene]:
        _validate_coordinates(latitude, longitude)
        if not self.url_template:
            return []
        bbox = _meter_bbox(latitude, longitude, 300)
        return [
            ImageryScene(
                image_url=self.url_template.format(
                    latitude=latitude,
                    longitude=longitude,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    bbox=",".join(str(value) for value in bbox),
                ),
                observed_at=end,
                resolution_m=self.resolution_m,
                provider=self.provider_name,
                cloud_fraction=None,
                fallback=False,
                bbox=bbox,
            )
        ]


def download_image(scene: ImageryScene, *, timeout_seconds: int = 60) -> np.ndarray:
    response = requests.get(scene.image_url, timeout=timeout_seconds)
    response.raise_for_status()
    image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Imagery is not a readable raster: {scene.image_url}")
    return image


def _meter_bbox(
    latitude: float, longitude: float, half_width_m: float
) -> tuple[float, float, float, float]:
    if half_width_m <= 0:
        raise ValueError("half_width_m must be positive")
    lat_delta = half_width_m / 111_320
    lon_delta = half_width_m / (111_320 * max(0.1, math.cos(math.radians(latitude))))
    return (
        longitude - lon_delta,
        latitude - lat_delta,
        longitude + lon_delta,
        latitude + lat_delta,
    )


def _web_mercator_tile(latitude: float, longitude: float, zoom: int) -> tuple[int, int]:
    """Return the XYZ tile containing a WGS84 coordinate."""

    n = 2**zoom
    x = int((longitude + 180) / 360 * n)
    y = int(
        (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * n
    )
    return x, y


def _tile_bbox(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    n = 2**zoom
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(
        math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    )
    return west, south, east, north


def _tile_url(
    *,
    scene_id: str,
    tile_x: int,
    tile_y: int,
    zoom: int,
    fallback_url: str,
) -> str:
    if not scene_id:
        return fallback_url
    return (
        # The tile endpoint is used instead of the STAC preview asset because
        # the preview endpoint may ignore a requested crop bounding box.
        "https://planetarycomputer.microsoft.com/api/data/v1/item/tiles/"
        f"WebMercatorQuad/{zoom}/{tile_x}/{tile_y}.png"
        f"?collection=sentinel-2-l2a&item={scene_id}"
        "&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png"
    )


def estimate_lid_shadow(
    image: np.ndarray,
    *,
    observed_at: datetime,
    latitude: float,
    longitude: float,
    tank_diameter_m: float | None = None,
    tank_height_m: float | None = None,
    resolution_m: float = 0.5,
    inferred_dimensions: bool = False,
    target_center_px: tuple[float, float] | None = None,
    detected_circle: tuple[float, float, float] | None = None,
) -> ShadowMeasurement:
    """Estimate fill from the visible roof/shadow boundary.

    This is conservative: the result is unavailable when a stable circular
    roof cannot be found or when the sun is too low for reliable shadows.
    """

    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image must be a BGR colour image")
    observed_at = observed_at.astimezone(timezone.utc)
    solar_elevation = float(get_altitude(latitude, longitude, observed_at))
    diagnostics: list[str] = []
    if solar_elevation <= 10:
        diagnostics.append("solar elevation is too low for reliable shadow geometry")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    circle = detected_circle or _find_tank_circle(image, target_center_px)
    x, y, radius = circle
    measured_diameter = 2 * radius * resolution_m
    diameter = tank_diameter_m or measured_diameter
    if diameter <= 0:
        raise ValueError("tank diameter must be positive")
    inferred = inferred_dimensions or tank_diameter_m is None
    if tank_height_m is None:
        tank_height_m = diameter * 0.35
        inferred = True
    if tank_height_m <= 0:
        raise ValueError("tank height must be positive")

    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.circle(mask, (int(x), int(y)), max(2, int(radius * 0.9)), 255, -1)
    roi = gray[mask > 0]
    contrast = float(np.percentile(roi, 90) - np.percentile(roi, 10))
    edge_density = float(np.count_nonzero(cv2.Canny(gray, 40, 120)[mask > 0])) / max(
        1, roi.size
    )
    # A floating roof's visible radial shadow is a first-order height proxy.
    radial_gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0))
    shadow_fraction = float(np.percentile(radial_gradient[mask > 0], 65)) / 255
    lid_fraction = float(np.clip(0.15 + shadow_fraction * 1.7, 0, 1))
    quality = float(np.clip(0.45 * min(1, contrast / 80) + 0.55 * min(1, edge_density * 8), 0, 1))
    if inferred:
        quality *= 0.7
        diagnostics.append("tank dimensions were inferred")
    if resolution_m > 2:
        quality *= 0.35
        diagnostics.append("imagery resolution is too coarse for precise lid mapping")
    if solar_elevation <= 10:
        quality *= 0.35
    certainty = quality
    if certainty < 0.45:
        diagnostics.append("shadow/lid evidence is ambiguous")
    return ShadowMeasurement(
        lid_fraction=round(lid_fraction, 4),
        lid_height_m=round(lid_fraction * tank_height_m, 3),
        solar_elevation_degrees=round(solar_elevation, 2),
        quality_score=round(float(np.clip(quality, 0, 1)), 3),
        diagnostics=tuple(diagnostics),
    )


def detect_overlay_detections(
    image: np.ndarray,
    *,
    estimated_fill_percentage: float,
    target_center_px: tuple[float, float] | None = None,
    detected_circle: tuple[float, float, float] | None = None,
) -> OverlayDetections:
    """Find the visual detections used to review a fill estimate."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    circle = detected_circle or _find_tank_circle(image, target_center_px)
    x, y, radius = map(int, np.around(circle))
    lines = cv2.HoughLinesP(
        cv2.Canny(blurred, 30, 120),
        1,
        np.pi / 180,
        threshold=max(30, image.shape[1] // 10),
        minLineLength=max(40, image.shape[1] // 8),
        maxLineGap=25,
    )
    candidates: list[tuple[int, int, int, int]] = []
    if lines is not None:
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(int, line)
            angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
            if angle <= 10 and (mid_x - x) ** 2 + (mid_y - y) ** 2 <= radius**2:
                candidates.append((x1, y1, x2, y2))
    estimated_y = int(round(y + radius * (1 - estimated_fill_percentage / 100)))
    selected = min(
        candidates,
        key=lambda line: abs((line[1] + line[3]) / 2 - estimated_y),
        default=(max(0, x - radius), estimated_y, min(image.shape[1] - 1, x + radius), estimated_y),
    )
    return OverlayDetections((x, y, radius), tuple(candidates), selected)


def _find_tank_circle(
    image: np.ndarray, target_center_px: tuple[float, float] | None
) -> tuple[float, float, float]:
    """Find the roof circle, preferring the expected crop centre."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(20, min(image.shape[:2]) // 5),
        param1=100,
        param2=30,
        minRadius=max(4, min(image.shape[:2]) // 40),
        maxRadius=max(11, min(image.shape[:2]) // 2),
    )
    if circles is None:
        raise ValueError("could not identify a circular tank roof")
    if target_center_px is None:
        return tuple(max(circles[0], key=lambda candidate: candidate[2]))
    target_x, target_y = target_center_px
    return tuple(
        min(
            circles[0],
            key=lambda candidate: (candidate[0] - target_x) ** 2
            + (candidate[1] - target_y) ** 2,
        )
    )


def write_inspection_overlay(
    image: np.ndarray,
    detections: OverlayDetections,
    *,
    output_path: str | Path,
    fill_percentage: float,
    certainty: str,
) -> dict[str, Any]:
    """Write the tank circle, candidate edges, and selected boundary."""

    overlay = image.copy()
    x, y, radius = detections.tank_circle
    cv2.circle(overlay, (x, y), radius, (255, 190, 0), 3)
    for x1, y1, x2, y2 in detections.candidate_edges:
        cv2.line(overlay, (x1, y1), (x2, y2), (0, 165, 255), 2)
    x1, y1, x2, y2 = detections.selected_boundary
    cv2.line(overlay, (x1, y1), (x2, y2), (0, 255, 0), 4)
    label = f"Fill {fill_percentage:.1f}% | {certainty}"
    cv2.rectangle(overlay, (12, 12), (min(overlay.shape[1] - 12, 380), 52), (0, 0, 0), -1)
    cv2.putText(overlay, label, (24, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), overlay):
        raise OSError(f"Could not write inspection overlay: {output}")
    return {
        "path": str(output),
        "tank_circle": {"x": x, "y": y, "radius": radius},
        "candidate_edge_count": len(detections.candidate_edges),
        "selected_boundary": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "legend": {"tank_circle": "cyan", "candidate_edges": "orange", "selected_boundary": "green"},
    }


def certainty_label(score: float) -> str:
    if score >= 0.72:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"


def estimate_scene(
    candidate: TankCandidate,
    scene: ImageryScene,
    image: np.ndarray,
    *,
    overlay_path: str | Path | None = None,
) -> dict[str, Any]:
    target_center = (image.shape[1] / 2, image.shape[0] / 2)
    detected_circle = _find_tank_circle(image, target_center)
    measurement = estimate_lid_shadow(
        image,
        observed_at=scene.observed_at,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
        tank_diameter_m=candidate.diameter_m,
        tank_height_m=candidate.height_m,
        resolution_m=scene.resolution_m,
        inferred_dimensions=candidate.diameter_m is None or candidate.height_m is None,
        target_center_px=target_center,
        detected_circle=detected_circle,
    )
    fill_percentage = round(measurement.lid_fraction * 100, 2)
    score = measurement.quality_score * (0.6 if scene.fallback else 1.0)
    result = {
        "tank": asdict(candidate),
        "imagery": {
            "provider": scene.provider,
            "observed_at_utc": scene.observed_at.isoformat().replace("+00:00", "Z"),
            "resolution_m": scene.resolution_m,
            "fallback": scene.fallback,
            "cloud_fraction": scene.cloud_fraction,
            "scene_id": scene.scene_id,
            "bbox": scene.bbox,
        },
        "fill_percentage": fill_percentage,
        "certainty": certainty_label(score),
        "certainty_score": round(score, 3),
        "diagnostics": list(measurement.diagnostics),
        "solar_elevation_degrees": measurement.solar_elevation_degrees,
        "method": "automated circular-roof and shadow proxy; dimensions may be inferred",
    }
    detections = detect_overlay_detections(
        image,
        estimated_fill_percentage=fill_percentage,
        target_center_px=target_center,
        detected_circle=detected_circle,
    )
    center_distance_px = math.hypot(
        detections.tank_circle[0] - target_center[0],
        detections.tank_circle[1] - target_center[1],
    )
    max_distance_px = min(image.shape[:2]) * 0.35
    if center_distance_px > max_distance_px:
        raise ValueError(
            "detected tank is not centered in the imagery crop; "
            "target tank could not be validated"
        )
    expected_radius_px = None
    if scene.bbox and candidate.diameter_m:
        west, _, east, _ = scene.bbox
        metres_per_pixel = (
            (east - west)
            * 111_320
            * max(0.1, math.cos(math.radians(candidate.latitude)))
            / image.shape[1]
        )
        expected_radius_px = candidate.diameter_m / (2 * metres_per_pixel)
        detected_radius_px = detections.tank_circle[2]
        if not 0.45 * expected_radius_px <= detected_radius_px <= 2.2 * expected_radius_px:
            raise ValueError(
                "detected circular feature has the wrong scale for the target tank; "
                "target tank could not be validated"
            )
    result["target_validation"] = {
        "status": "passed",
        "center_distance_px": round(center_distance_px, 2),
        "max_allowed_distance_px": round(max_distance_px, 2),
        "expected_radius_px": (
            round(expected_radius_px, 2) if expected_radius_px is not None else None
        ),
        "detected_radius_px": detections.tank_circle[2],
    }
    if overlay_path is not None:
        result["inspection_overlay"] = write_inspection_overlay(
            image,
            detections,
            output_path=overlay_path,
            fill_percentage=fill_percentage,
            certainty=certainty_label(score),
        )
    return result


def default_date_window(days: int = 30) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end
