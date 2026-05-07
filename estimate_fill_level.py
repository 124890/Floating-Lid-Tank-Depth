import argparse
from datetime import datetime, timezone

import cv2
import matplotlib.pyplot as plt
import numpy as np
from pysolar.solar import get_altitude


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate floating roof tank fill level from shadow geometry.",
    )
    parser.add_argument("--image", default="tank.jpg", help="Path to input tank image")
    parser.add_argument("--tank-height", type=float, default=22.0, help="Tank height in metres")
    parser.add_argument("--tank-diameter", type=float, default=80.0, help="Tank diameter in metres")
    parser.add_argument("--latitude", type=float, default=51.5074, help="Tank latitude")
    parser.add_argument("--longitude", type=float, default=-0.1278, help="Tank longitude")
    parser.add_argument(
        "--timestamp-utc",
        default="2026-05-07T14:30:00",
        help="Image timestamp in UTC ISO format, e.g. 2026-05-07T14:30:00",
    )
    parser.add_argument(
        "--pixels-per-metre",
        type=float,
        default=52.0,
        help="Pixel-to-metre calibration for the tank wall",
    )
    parser.add_argument(
        "--output-image",
        default="",
        help="Optional path to save annotated output image",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Skip interactive display (useful in headless environments)",
    )
    return parser.parse_args()


def _mid_y(line: tuple[int, int, int, int]) -> float:
    return (line[1] + line[3]) / 2


def detect_horizontal_lines(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    edges = cv2.Canny(blur, 50, 150)

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=200,
        maxLineGap=20,
    )

    if lines is None:
        raise RuntimeError("No shadow lines detected.")

    horizontal_lines: list[tuple[int, int, int, int]] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) < 10:
            horizontal_lines.append((x1, y1, x2, y2))

    if not horizontal_lines:
        raise RuntimeError("No horizontal shadow lines found.")

    return horizontal_lines


def main() -> None:
    args = parse_args()

    if args.tank_height <= 0:
        raise ValueError("--tank-height must be positive")
    if args.tank_diameter <= 0:
        raise ValueError("--tank-diameter must be positive")
    if args.pixels_per_metre <= 0:
        raise ValueError("--pixels-per-metre must be positive")

    timestamp = datetime.fromisoformat(args.timestamp_utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(f"Could not load image: {args.image}")

    original = img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    horizontal_lines = detect_horizontal_lines(gray)

    shadow_line = max(horizontal_lines, key=_mid_y)
    x1, y1, x2, y2 = shadow_line
    shadow_y = int((y1 + y2) / 2)
    cv2.line(original, (x1, y1), (x2, y2), (0, 0, 255), 3)

    rim_line = min(horizontal_lines, key=_mid_y)
    rx1, ry1, rx2, ry2 = rim_line
    rim_y = int((ry1 + ry2) / 2)
    cv2.line(original, (rx1, ry1), (rx2, ry2), (255, 0, 0), 3)

    shadow_height_pixels = abs(shadow_y - rim_y)
    shadow_height_metres = shadow_height_pixels / args.pixels_per_metre

    solar_elevation_deg = get_altitude(args.latitude, args.longitude, timestamp)
    solar_elevation_rad = np.radians(solar_elevation_deg)

    if solar_elevation_deg <= 0 or np.isclose(np.tan(solar_elevation_rad), 0.0):
        raise RuntimeError(
            "Solar elevation is too low for stable estimation. Provide a daytime image with positive sun elevation."
        )

    visible_wall_height = shadow_height_metres / np.tan(solar_elevation_rad)
    visible_wall_height = max(0.0, min(args.tank_height, visible_wall_height))

    liquid_height = args.tank_height - visible_wall_height
    fill_percentage = (liquid_height / args.tank_height) * 100

    print(f"Solar elevation: {solar_elevation_deg:.2f} deg")
    print("\n========== RESULTS ==========")
    print(f"Shadow height: {shadow_height_metres:.2f} m")
    print(f"Visible wall height: {visible_wall_height:.2f} m")
    print(f"Estimated liquid height: {liquid_height:.2f} m")
    print(f"Estimated fill: {fill_percentage:.1f}%")

    plt.figure(figsize=(12, 8))
    plt.imshow(cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
    plt.title(f"Estimated Fill Level: {fill_percentage:.1f}%")
    plt.axis("off")

    if args.output_image:
        plt.savefig(args.output_image, bbox_inches="tight")

    if not args.no_display:
        plt.show()


if __name__ == "__main__":
    main()
