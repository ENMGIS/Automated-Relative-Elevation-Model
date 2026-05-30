"""Live-network tests against real USGS + NHD endpoints.
Run: python3 test_live.py
Requires internet. Does NOT download DEM tiles (workers mocked).
Small AOI used to keep NHD payload small.
"""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
from shapely.geometry import box

import data_collections as dc


# Tiny AOI on Sacramento River near Colusa, CA.
# ~3 km x 3 km — small enough that NHD response is fast.
AOI_BOUNDS = (-122.00, 39.20, -121.97, 39.23)


def _write_tmp_aoi(path):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[box(*AOI_BOUNDS)], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")
    return path


class TestLiveNHDCache(unittest.TestCase):
    """Hits real NHDPlus V2 WaterData service."""

    def setUp(self):
        dc._NHD_V2_BBOX_CACHE.clear()
        self.tmpdir = os.path.join(os.path.dirname(__file__), "_test_live_tmp")
        os.makedirs(self.tmpdir, exist_ok=True)
        self.aoi_path = _write_tmp_aoi(os.path.join(self.tmpdir, "aoi.geojson"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_then_choose_hits_network_once(self):
        import pynhd
        original_bybox = pynhd.WaterData.bybox
        calls = {"n": 0}

        def counting_bybox(self, bounds, *a, **kw):
            calls["n"] += 1
            return original_bybox(self, bounds, *a, **kw)

        with patch.object(pynhd.WaterData, "bybox", counting_bybox):
            rivers = dc.scan_nhd_rivers(self.aoi_path)
            print(f"\n  [live] rivers found: {rivers[:5]}{'...' if len(rivers) > 5 else ''}")
            self.assertTrue(len(rivers) > 0, "expected at least one river near Sacramento River")

            target = rivers[0]
            out = dc.choose_and_save_nhd_river(
                [self.aoi_path], self.tmpdir, river_choice=1, river_name=target
            )
            self.assertIsNotNone(out)
            self.assertTrue(os.path.exists(out))

        print(f"  [live] pynhd.WaterData.bybox network calls: {calls['n']}")
        self.assertEqual(calls["n"], 1, "cache should have prevented a second bybox call")


class TestLiveTNMCoverage(unittest.TestCase):
    """Hits real TNM products API, mocks tile downloads.
    Verifies S1M-skip decision runs against real catalog response.
    """

    def setUp(self):
        self.tmpdir = os.path.join(os.path.dirname(__file__), "_test_live_tnm")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tnm_10m_real_catalog(self):
        aoi = gpd.GeoDataFrame({"id": [1]}, geometry=[box(*AOI_BOUNDS)], crs="EPSG:4326")
        captured = {"urls": []}

        def fake_dl(url, dest, idx, total):
            captured["urls"].append(url)
            # Don't create a real file; return None so downstream treats as failure
            # — we only care about WHICH urls were queued.
            return None

        with patch.object(dc, "_download_file_worker", side_effect=fake_dl):
            dc._download_via_source_api(aoi, self.tmpdir, resolution=10, n_jobs=1)

        print(f"\n  [live] TNM 10m queued {len(captured['urls'])} url(s)")
        for u in captured["urls"][:5]:
            print(f"    {u}")
        # 10m has no S1M category, but the coverage log should still print.
        # Just assert we got some tiles back from the real catalog.
        self.assertTrue(
            len(captured["urls"]) > 0,
            "TNM should return at least one 10m tile for this AOI",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
