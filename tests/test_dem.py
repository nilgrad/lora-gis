"""Baseline unit tests for lora_gis.dem (fully offline)."""

import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from lora_gis.dem import DEMProvider


class _MockBytesResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class TestDEMProvider(unittest.TestCase):
    def test_sample_bilinear_corners_and_midpoint(self) -> None:
        # 2x2 grid: top-left=100, top-right=200, bottom-left=300, bottom-right=400
        arr = np.array([[100.0, 200.0], [300.0, 400.0]], dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 100.0, 100.0, 2, 2)

        xs = np.array([0.0, 100.0, 0.0, 100.0, 50.0])
        ys = np.array([100.0, 100.0, 0.0, 0.0, 50.0])
        vals = dem.sample_bilinear(xs, ys)

        self.assertAlmostEqual(vals[0], 100.0, delta=0.05)
        self.assertAlmostEqual(vals[1], 200.0, delta=0.05)
        self.assertAlmostEqual(vals[2], 300.0, delta=0.05)
        self.assertAlmostEqual(vals[3], 400.0, delta=0.05)
        self.assertAlmostEqual(vals[4], 250.0, delta=0.05)

    def test_fetch_elevations_empty_and_from_cache(self) -> None:
        arr = np.full((10, 10), 425.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 100.0, 200.0, 200.0, 300.0, 10, 10)

        self.assertEqual(dem.fetch_elevations([]), [])
        with patch("lora_gis.dem.urllib.request.urlopen") as mock_http:
            vals = dem.fetch_elevations([(120.0, 250.0), (180.0, 280.0)])
            mock_http.assert_not_called()
        self.assertEqual(vals, [425.0, 425.0])

    def test_fetch_elevations_http_batching_and_invalid_values(self) -> None:
        dem = DEMProvider("https://example.invalid", wkid=26918)
        points = [(float(i), float(i)) for i in range(105)]

        call_count = 0

        def fake_urlopen(req, timeout=5.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                samples = [{"locationId": idx, "value": str(100.0 + idx)} for idx in range(100)]
                samples[5]["value"] = "NoData"
                return _MockBytesResponse(json.dumps({"samples": samples}).encode("utf-8"))
            samples = [{"locationId": idx, "value": str(500.0 + idx)} for idx in range(5)]
            return _MockBytesResponse(json.dumps({"samples": samples}).encode("utf-8"))

        with patch("lora_gis.dem.urllib.request.urlopen", side_effect=fake_urlopen):
            vals = dem.fetch_elevations(points)

        self.assertEqual(call_count, 2)
        self.assertEqual(len(vals), 105)
        self.assertAlmostEqual(vals[0], 100.0)
        self.assertAlmostEqual(vals[5], -9999.0)
        self.assertAlmostEqual(vals[100], 500.0)
        self.assertAlmostEqual(vals[104], 504.0)

    def test_fetch_elevations_http_failure_returns_sentinel(self) -> None:
        dem = DEMProvider("https://example.invalid", wkid=26918)
        with patch("lora_gis.dem.urllib.request.urlopen", side_effect=OSError("timeout")):
            vals = dem.fetch_elevations([(1.0, 2.0), (3.0, 4.0)])
        self.assertEqual(vals, [-9999.0, -9999.0])

    def test_load_raster_local_tiff_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tif_path = os.path.join(tmpdir, "local.tif")
            arr = np.full((16, 16), 312.5, dtype=np.float32)
            Image.fromarray(arr, mode="F").save(tif_path)

            dem = DEMProvider("https://example.invalid", wkid=26918, dem_file=tif_path)
            dem.load_raster(0.0, 0.0, 1000.0, 1000.0)

            self.assertIsNotNone(dem.cache)
            val = dem.sample_bilinear(np.array([500.0]), np.array([500.0]))[0]
            self.assertAlmostEqual(val, 312.5, places=3)

    def test_load_raster_streams_tiff_with_retry(self) -> None:
        buf = io.BytesIO()
        Image.fromarray(np.full((10, 10), 250.0, dtype=np.float32), mode="F").save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        attempts = 0

        def fake_urlopen(url, timeout=25.0):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("server busy at max_px")
            return _MockBytesResponse(tiff_bytes)

        dem = DEMProvider("https://example.invalid", wkid=26918)
        with patch("lora_gis.dem.urllib.request.urlopen", side_effect=fake_urlopen):
            dem.load_raster(0.0, 0.0, 5000.0, 5000.0, resolution_m=3.0, max_px=2500)

        self.assertEqual(attempts, 2)
        self.assertIsNotNone(dem.cache)
        self.assertAlmostEqual(dem.sample_bilinear(np.array([2500.0]), np.array([2500.0]))[0], 250.0, places=3)

    def test_load_raster_all_retries_fail_sets_cache_none(self) -> None:
        dem = DEMProvider("https://example.invalid", wkid=26918)
        with patch("lora_gis.dem.urllib.request.urlopen", side_effect=OSError("unreachable")):
            dem.load_raster(0.0, 0.0, 5000.0, 5000.0)
        self.assertIsNone(dem.cache)


if __name__ == "__main__":
    unittest.main()
