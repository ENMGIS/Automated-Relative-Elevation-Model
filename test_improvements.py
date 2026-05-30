"""Smoke tests for DEM coverage skip + NHD cache.
Run: python3 test_improvements.py
No network calls — everything is stubbed.
"""
import sys
import os
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Polygon

import data_collections as dc


def _make_aoi(minx=-76.2, miny=43.5, maxx=-76.0, maxy=43.6):
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(minx, miny, maxx, maxy)],
        crs="EPSG:4326",
    )
    return gdf


class TestNHDCache(unittest.TestCase):
    def setUp(self):
        dc._NHD_V2_BBOX_CACHE.clear()

    def test_cache_roundtrip(self):
        bounds = (-76.2, 43.5, -76.0, 43.6)
        gdf = gpd.GeoDataFrame({"gnis_name": ["Foo"]}, geometry=[box(*bounds)], crs="EPSG:4326")
        self.assertIsNone(dc._nhd_cache_get(bounds))
        dc._nhd_cache_put(bounds, gdf)
        self.assertIs(dc._nhd_cache_get(bounds), gdf)

    def test_cache_bbox_rounding(self):
        bounds_a = (-76.200001234, 43.500001, -76.000001, 43.60000002)
        bounds_b = (-76.200001, 43.500001, -76.000001, 43.60000002)
        gdf = gpd.GeoDataFrame({"gnis_name": ["Foo"]}, geometry=[box(-76.2, 43.5, -76.0, 43.6)], crs="EPSG:4326")
        dc._nhd_cache_put(bounds_a, gdf)
        self.assertIs(dc._nhd_cache_get(bounds_b), gdf)

    def test_cache_eviction(self):
        gdf = gpd.GeoDataFrame({"gnis_name": ["X"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
        for i in range(dc._NHD_V2_CACHE_MAX + 3):
            dc._nhd_cache_put((i, i, i + 1, i + 1), gdf)
        self.assertLessEqual(len(dc._NHD_V2_BBOX_CACHE), dc._NHD_V2_CACHE_MAX)


class TestScanChooseSharedCache(unittest.TestCase):
    """scan_nhd_rivers populates cache; choose_and_save_nhd_river reuses it."""

    def setUp(self):
        dc._NHD_V2_BBOX_CACHE.clear()
        self.tmpdir = os.path.join(os.path.dirname(__file__), "_test_tmp")
        os.makedirs(self.tmpdir, exist_ok=True)
        self.aoi_path = os.path.join(self.tmpdir, "aoi.geojson")
        _make_aoi().to_file(self.aoi_path, driver="GeoJSON")

        self.flowlines = gpd.GeoDataFrame(
            {
                "gnis_name": ["Fake River", "Fake River", "Other Creek"],
                "comid": [1, 2, 3],
            },
            geometry=[
                box(-76.19, 43.55, -76.10, 43.56),
                box(-76.10, 43.55, -76.02, 43.56),
                box(-76.18, 43.52, -76.12, 43.53),
            ],
            crs="EPSG:4326",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_then_choose_uses_cache(self):
        call_counter = {"n": 0}

        def fake_bybox(bounds):
            call_counter["n"] += 1
            return self.flowlines.copy()

        fake_wd = MagicMock()
        fake_wd.bybox.side_effect = fake_bybox

        with patch.object(dc.pynhd, "WaterData", return_value=fake_wd):
            rivers = dc.scan_nhd_rivers(self.aoi_path)
            self.assertIn("Fake River", rivers)
            self.assertEqual(call_counter["n"], 1)

            out = dc.choose_and_save_nhd_river(
                [self.aoi_path], self.tmpdir, river_choice=1, river_name="Fake River"
            )
            # Still only one network call thanks to the cache.
            self.assertEqual(call_counter["n"], 1)
            self.assertIsNotNone(out)
            self.assertTrue(os.path.exists(out))


class TestS1mSkipCoverage(unittest.TestCase):
    """_download_via_source_api skips S1M when project tiles cover AOI."""

    def setUp(self):
        self.tmpdir = os.path.join(os.path.dirname(__file__), "_test_tmp_dem")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mock_tnm_response(self, project_tiles, s1m_tiles):
        items = []
        for url, geom, title in project_tiles:
            items.append({
                "title": title,
                "downloadURL": url,
                "boundingBox": {
                    "minX": geom.bounds[0], "minY": geom.bounds[1],
                    "maxX": geom.bounds[2], "maxY": geom.bounds[3],
                },
                "publicationDate": "2023-01-01",
            })
        for url, geom, title in s1m_tiles:
            items.append({
                "title": title,
                "downloadURL": url,
                "boundingBox": {
                    "minX": geom.bounds[0], "minY": geom.bounds[1],
                    "maxX": geom.bounds[2], "maxY": geom.bounds[3],
                },
                "publicationDate": "2020-01-01",
            })
        resp = MagicMock()
        resp.json.return_value = {"items": items}
        return resp

    def _run(self, project_tiles, s1m_tiles, aoi):
        captured = {"urls": []}

        def fake_dl(url, dest, idx, total):
            captured["urls"].append(url)
            return dest

        resp = self._mock_tnm_response(project_tiles, s1m_tiles)
        with patch.object(dc.requests, "get", return_value=resp), \
             patch.object(dc, "_download_file_worker", side_effect=fake_dl):
            dc._download_via_source_api(aoi, self.tmpdir, resolution=1, n_jobs=1)
        return captured["urls"]

    def test_full_coverage_skips_s1m(self):
        aoi = _make_aoi(-76.2, 43.5, -76.0, 43.6)
        project_tiles = [
            ("https://example/project_1.tif", box(-76.25, 43.45, -75.95, 43.65), "USGS 1 meter Project Tile"),
        ]
        s1m_tiles = [
            ("https://example/s1m_1.tif", box(-76.25, 43.45, -75.95, 43.65), "USGS S1M 1 meter Standard"),
        ]
        urls = self._run(project_tiles, s1m_tiles, aoi)
        self.assertTrue(any("project_1.tif" in u for u in urls))
        self.assertFalse(any("s1m_1.tif" in u for u in urls), f"S1M should be skipped, got: {urls}")

    def test_partial_coverage_keeps_s1m(self):
        aoi = _make_aoi(-76.2, 43.5, -76.0, 43.6)
        project_tiles = [
            ("https://example/project_1.tif", box(-76.20, 43.50, -76.10, 43.55), "USGS 1 meter Project Tile"),
        ]
        s1m_tiles = [
            ("https://example/s1m_1.tif", box(-76.25, 43.45, -75.95, 43.65), "USGS S1M 1 meter Standard"),
        ]
        urls = self._run(project_tiles, s1m_tiles, aoi)
        self.assertTrue(any("project_1.tif" in u for u in urls))
        self.assertTrue(any("s1m_1.tif" in u for u in urls), f"S1M should be kept, got: {urls}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
