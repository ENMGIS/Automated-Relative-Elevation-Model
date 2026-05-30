"""Tests for rem_cache + extracted ui.validation.
Run: python3 test_cache_and_manifest.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rem_cache
from ui.validation import path_exists, validate_dem_file, validate_river_file


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rem_cache_test_")
        os.environ["REM_CACHE_DIR"] = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("REM_CACHE_DIR", None)

    def test_store_and_retrieve(self):
        src = os.path.join(self.tmp, "fake_tile.tif")
        with open(src, "wb") as f:
            f.write(b"fake raster bytes")

        url = "https://example.com/tiles/foo.tif"
        self.assertIsNone(rem_cache.get_cached(url))
        cached_path = rem_cache.store_in_cache(url, src)
        self.assertIsNotNone(cached_path)
        self.assertTrue(os.path.exists(cached_path))

        self.assertIsNotNone(rem_cache.get_cached(url))

        # Link into a fresh destination
        dest = os.path.join(self.tmp, "out.tif")
        self.assertTrue(rem_cache.link_from_cache(url, dest))
        self.assertTrue(os.path.exists(dest))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"fake raster bytes")

    def test_cache_key_is_deterministic(self):
        url = "https://example.com/tiles/A.tif"
        p1 = rem_cache.cached_path_for(url)
        p2 = rem_cache.cached_path_for(url)
        self.assertEqual(p1, p2)

    def test_cache_stats(self):
        stats0 = rem_cache.cache_stats()
        self.assertEqual(stats0["count"], 0)

        src = os.path.join(self.tmp, "x.tif")
        with open(src, "wb") as f:
            f.write(b"data" * 100)
        rem_cache.store_in_cache("https://u/1.tif", src)
        rem_cache.store_in_cache("https://u/2.tif", src)

        stats = rem_cache.cache_stats()
        self.assertEqual(stats["count"], 2)
        self.assertGreater(stats["bytes"], 0)


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rem_manifest_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_and_read_roundtrip(self):
        payload = {
            "aoi_bbox": [-76.2, 43.5, -76.0, 43.6],
            "config": {"resolution": 10, "engine": "hand"},
            "outputs": {"rem": "/tmp/REM.tif"},
        }
        path = rem_cache.write_manifest(self.tmp, payload)
        self.assertTrue(os.path.exists(path))

        loaded = rem_cache.read_manifest(self.tmp)
        self.assertEqual(loaded["schema"], rem_cache.SCHEMA_VERSION)
        self.assertEqual(loaded["aoi_bbox"], payload["aoi_bbox"])
        self.assertEqual(loaded["config"]["engine"], "hand")
        self.assertIn("timestamp", loaded)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rem_validation_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_path_exists(self):
        self.assertFalse(path_exists(""))
        self.assertFalse(path_exists("/does/not/exist/probably"))
        self.assertTrue(path_exists(self.tmp))

    def test_validate_dem_missing(self):
        r = validate_dem_file("/does/not/exist.tif")
        self.assertFalse(r["valid"])
        self.assertIn("not found", r["error"])

    def test_validate_river_missing(self):
        r = validate_river_file("/does/not/exist.shp")
        self.assertFalse(r["valid"])
        self.assertIn("not found", r["error"])

    def test_validate_dem_real_file(self):
        # Build a tiny in-memory-backed GeoTIFF and validate it.
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        path = os.path.join(self.tmp, "tiny.tif")
        data = np.ones((10, 10), dtype=np.float32)
        with rasterio.open(
            path, "w", driver="GTiff",
            height=10, width=10, count=1, dtype=data.dtype,
            crs="EPSG:32610",
            transform=from_origin(500000, 4000000, 10, 10),
        ) as dst:
            dst.write(data, 1)

        r = validate_dem_file(path)
        self.assertTrue(r["valid"], r["error"])
        self.assertFalse(r["info"]["is_geographic"])
        self.assertEqual(r["info"]["width"], 10)

    def test_validate_river_real_file(self):
        import geopandas as gpd
        from shapely.geometry import LineString

        path = os.path.join(self.tmp, "river.gpkg")
        gdf = gpd.GeoDataFrame(
            {"gnis_name": ["Test River"]},
            geometry=[LineString([(0, 0), (1, 1)])],
            crs="EPSG:4326",
        )
        gdf.to_file(path, driver="GPKG")

        r = validate_river_file(path)
        self.assertTrue(r["valid"], r["error"])
        self.assertEqual(r["info"]["feature_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
