"""Estimate a floating-lid tank fill percentage from satellite imagery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

from satellite_fill import (
    CommercialTileProvider,
    PlanetaryComputerProvider,
    TankCandidate,
    default_date_window,
    discover_tanks,
    download_image,
    estimate_scene,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("depot", nargs="?", help="Depot name or address in the UK/EU")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--diameter-m", type=float)
    parser.add_argument("--height-m", type=float)
    parser.add_argument("--tank-id", help="OSM candidate identifier to select")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--provider", choices=("auto", "commercial", "sentinel"), default="auto"
    )
    parser.add_argument("--overlay-path", type=Path)
    args = parser.parse_args()

    if (args.latitude is None) != (args.longitude is None):
        parser.error("--latitude and --longitude must be supplied together")
    try:
        if args.latitude is not None:
            candidates = [
                TankCandidate(
                    identifier="coordinate-selection",
                    latitude=args.latitude,
                    longitude=args.longitude,
                    diameter_m=args.diameter_m,
                    height_m=args.height_m,
                    source="direct-coordinate",
                )
            ]
        elif args.depot:
            candidates = discover_tanks(args.depot)
        else:
            parser.error("provide a depot or --latitude/--longitude")
    except (LookupError, requests.RequestException) as error:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "tank discovery failed",
                    "error": str(error),
                },
                indent=2,
            )
        )
        raise SystemExit(2) from error
    if not candidates:
        raise SystemExit("No mapped storage tanks were found near the depot")
    if args.tank_id:
        candidate = next(
            (tank for tank in candidates if tank.identifier == args.tank_id), None
        )
        if candidate is None:
            raise SystemExit(f"Tank candidate was not found: {args.tank_id}")
    else:
        candidate = candidates[0]
    start, end = default_date_window(args.days)
    providers = []
    if args.provider in ("auto", "commercial"):
        providers.append(CommercialTileProvider())
    if args.provider in ("auto", "sentinel"):
        providers.append(PlanetaryComputerProvider())
    scenes = []
    try:
        for provider in providers:
            scenes.extend(
                provider.search(candidate.latitude, candidate.longitude, start, end)
            )
            if scenes and args.provider == "auto":
                break
    except requests.RequestException as error:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "imagery provider request failed",
                    "error": str(error),
                },
                indent=2,
            )
        )
        raise SystemExit(2) from error
    if not scenes:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "no suitable imagery was found for the selected tank",
                },
                indent=2,
            )
        )
        raise SystemExit(2)
    scene = sorted(scenes, key=lambda item: (item.fallback, -item.observed_at.timestamp()))[0]
    overlay_path = args.overlay_path or Path(
        f"tank-{candidate.identifier.replace('/', '-')}-inspection.png"
    )
    try:
        result = estimate_scene(
            candidate, scene, download_image(scene), overlay_path=overlay_path
        )
    except (requests.RequestException, ValueError) as error:
        result = {
            "status": "unavailable",
            "reason": "lid or shadow evidence could not be measured",
            "error": str(error),
        }
        print(json.dumps(result, indent=2))
        raise SystemExit(2) from error
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
