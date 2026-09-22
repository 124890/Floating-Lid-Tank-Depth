import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

from satellite_fill import (
    CommercialTileProvider,
    ImageryScene,
    PlanetaryComputerProvider,
    TankCandidate,
    certainty_label,
    estimate_lid_shadow,
    estimate_scene,
)


class SatelliteFillTests(unittest.TestCase):
    def test_certainty_bands_are_stable(self):
        self.assertEqual(certainty_label(0.8), "High")
        self.assertEqual(certainty_label(0.5), "Medium")
        self.assertEqual(certainty_label(0.2), "Low")

    def test_synthetic_roof_produces_bounded_measurement(self):
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        cv2.circle(image, (256, 256), 150, (180, 180, 180), 8)
        cv2.circle(image, (256, 256), 130, (70, 70, 70), -1)
        measurement = estimate_lid_shadow(
            image,
            observed_at=datetime(2026, 6, 21, 12, tzinfo=timezone.utc),
            latitude=51.5,
            longitude=0,
            tank_diameter_m=80,
            tank_height_m=22,
        )
        self.assertGreaterEqual(measurement.lid_fraction, 0)
        self.assertLessEqual(measurement.lid_fraction, 1)
        self.assertGreaterEqual(measurement.quality_score, 0)
        self.assertLessEqual(measurement.quality_score, 1)

    @patch("satellite_fill.get_altitude", return_value=45.0)
    def test_scene_penalizes_sentinel_fallback(self, _solar):
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        cv2.circle(image, (256, 256), 150, (180, 180, 180), 8)
        cv2.circle(image, (256, 256), 130, (70, 70, 70), -1)
        scene = ImageryScene(
            image_url="fixture",
            observed_at=datetime(2026, 6, 21, 12, tzinfo=timezone.utc),
            resolution_m=10,
            provider="sentinel",
            cloud_fraction=0.1,
            fallback=True,
        )
        result = estimate_scene(
            TankCandidate("tank-1", 51.5, 0, 80, 22, "fixture"), scene, image
        )
        self.assertEqual(result["imagery"]["fallback"], True)
        self.assertEqual(result["certainty"], "Low")

    def test_scene_writes_detection_overlay(self):
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        cv2.circle(image, (256, 256), 150, (180, 180, 180), 8)
        cv2.circle(image, (256, 256), 130, (70, 70, 70), -1)
        scene = ImageryScene(
            image_url="fixture",
            observed_at=datetime(2026, 6, 21, 12, tzinfo=timezone.utc),
            resolution_m=0.5,
            provider="commercial-fixture",
            cloud_fraction=0.0,
            fallback=False,
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "review" / "overlay.png"
            result = estimate_scene(
                TankCandidate("tank-1", 51.5, 0, 80, 22, "fixture"),
                scene,
                image,
                overlay_path=path,
            )
            self.assertTrue(path.is_file())
            self.assertEqual(result["inspection_overlay"]["path"], str(path))
            self.assertGreaterEqual(
                result["inspection_overlay"]["candidate_edge_count"], 0
            )
            self.assertEqual(result["target_validation"]["status"], "passed")

    def test_scene_rejects_wrong_scale_for_known_tank(self):
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        cv2.circle(image, (256, 256), 150, (180, 180, 180), 8)
        cv2.circle(image, (256, 256), 130, (70, 70, 70), -1)
        scene = ImageryScene(
            image_url="fixture",
            observed_at=datetime(2026, 6, 21, 12, tzinfo=timezone.utc),
            resolution_m=10,
            provider="sentinel",
            cloud_fraction=0.0,
            fallback=True,
            bbox=(0.0, 0.0, 0.01, 0.01),
        )
        with self.assertRaisesRegex(ValueError, "wrong scale"):
            estimate_scene(
                TankCandidate("tank-1", 51.5, 0, 80, 22, "fixture"),
                scene,
                image,
            )

    def test_commercial_scene_contains_centered_crop_bbox(self):
        scene = CommercialTileProvider(
            url_template="https://example.test/{latitude}/{longitude}/{bbox}"
        ).search(53.6, -0.2, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))[0]
        self.assertIsNotNone(scene.bbox)
        self.assertIn(str(scene.bbox[0]), scene.image_url)

    @patch("satellite_fill.requests.post")
    def test_planetary_search_builds_tank_centered_preview(self, post):
        post.return_value.json.return_value = {
            "features": [
                {
                    "id": "S2-test",
                    "properties": {
                        "datetime": "2026-09-20T11:21:09.024Z",
                        "eo:cloud_cover": 10,
                    },
                    "assets": {"rendered_preview": {"href": "https://example.test/full.png"}},
                }
            ]
        }
        post.return_value.raise_for_status.return_value = None
        scene = PlanetaryComputerProvider().search(
            53.6,
            -0.2,
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 22, tzinfo=timezone.utc),
        )[0]
        self.assertIn("item=S2-test", scene.image_url)
        self.assertIn("/tiles/WebMercatorQuad/16/", scene.image_url)
        self.assertEqual(len(scene.bbox), 4)
        self.assertEqual(scene.scene_id, "S2-test")


if __name__ == "__main__":
    unittest.main()
