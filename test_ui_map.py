"""Tests for ui/map.py — extract_aoi_from_map, build_aoi_map, coverage fetch.
Run: python3 test_ui_map.py
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.map import (
    extract_aoi_from_map,
    build_aoi_map,
    save_aoi_geojson,
    fetch_dem_coverage_footprints,
    _SilentSink,
)


class TestExtractAoi(unittest.TestCase):
    def test_empty_map_data(self):
        self.assertIsNone(extract_aoi_from_map(None))
        self.assertIsNone(extract_aoi_from_map({}))

    def test_all_drawings_dict_form(self):
        gj = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                "properties": {},
            }],
        }
        gdf = extract_aoi_from_map({"all_drawings": gj})
        self.assertIsNotNone(gdf)
        self.assertEqual(len(gdf), 1)
        self.assertEqual(str(gdf.crs), "EPSG:4326")

    def test_last_active_drawing(self):
        feature = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            "properties": {},
        }
        gdf = extract_aoi_from_map({"last_active_drawing": feature})
        self.assertIsNotNone(gdf)
        self.assertEqual(len(gdf), 1)


class TestBuildMap(unittest.TestCase):
    def test_basic_map(self):
        m = build_aoi_map(center=[40.0, -100.0], zoom_start=5)
        self.assertIsNotNone(m)

    def test_with_coverage(self):
        from shapely.geometry import box
        coverage = {
            10: [{"geometry": box(-100.1, 40.0, -100.0, 40.1), "title": "t", "date": "2024-01-01"}],
            30: [],
        }
        m = build_aoi_map([40.0, -100.0], 5, coverage_data=coverage, show_coverage_layers=True)
        self.assertIsNotNone(m)


class TestCoverageFetch(unittest.TestCase):
    def test_mocked_tnm(self):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"items": [
            {
                "title": "USGS 1/3 arc-second n40w100 — 10m",
                "downloadURL": "https://example/10m.tif",
                "boundingBox": {"minX": -100.0, "minY": 40.0, "maxX": -99.9, "maxY": 40.1},
                "publicationDate": "2024-01-01",
            },
            {
                "title": "USGS Standard 1-Meter tile",  # S1M — should be skipped
                "downloadURL": "https://example/s1m.tif",
                "boundingBox": {"minX": -100.0, "minY": 40.0, "maxX": -99.9, "maxY": 40.1},
                "publicationDate": "2024-01-01",
            },
        ]}

        with patch("ui.map.requests.get", return_value=fake_resp):
            result = fetch_dem_coverage_footprints(
                bounds=(40.0, -100.0, 40.1, -99.9),
                sink=_SilentSink(),
            )

        self.assertEqual(len(result[10]), 1)
        self.assertEqual(len(result[1]), 0)  # S1M filtered

    def test_aoi_filter(self):
        from shapely.geometry import box
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"items": [
            {
                "title": "10m tile inside",
                "downloadURL": "https://example/a.tif",
                "boundingBox": {"minX": -100.0, "minY": 40.0, "maxX": -99.95, "maxY": 40.05},
                "publicationDate": "2024-01-01",
            },
            {
                "title": "10m tile outside",
                "downloadURL": "https://example/b.tif",
                "boundingBox": {"minX": -110.0, "minY": 50.0, "maxX": -109.9, "maxY": 50.1},
                "publicationDate": "2024-01-01",
            },
        ]}

        aoi = box(-100.0, 40.0, -99.9, 40.1)
        with patch("ui.map.requests.get", return_value=fake_resp):
            result = fetch_dem_coverage_footprints(
                bounds=(40.0, -100.0, 40.1, -99.9),
                aoi_geom=aoi,
                sink=_SilentSink(),
            )

        self.assertEqual(len(result[10]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
