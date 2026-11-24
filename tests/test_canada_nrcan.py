"""Offline unit and headless integration tests for Canada NRCan CanElevation & CGNDB support."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from lora_gis.cli import _apply_canada_smart_defaults, apply_cli_args, run_analysis
from lora_gis.config import BASEMAP_PRESETS, DEM_PRESETS, LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.geonames import (
    CANADA_PROVINCE_CODES,
    fetch_cgndb_features,
    fetch_geonames_features,
    is_canada_province,
    lookup_cgndb_place,
    lookup_geonames_place,
    resolve_location,
)
from lora_gis.nrcan import (
    is_canada_dem_source,
    is_canada_dsm_source,
    load_nrcan_dem,
    search_nrcan_stac_assets,
    stream_nrcan_elevation_grid,
    utm_bounds_to_wgs84_bbox,
)
from lora_gis.utm import detect_utm_crs


class _MockHTTPResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakeRect:
    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        self._vals = (xmin, ymin, xmax, ymax)

    def xMinimum(self) -> float:
        return self._vals[0]

    def yMinimum(self) -> float:
        return self._vals[1]

    def xMaximum(self) -> float:
        return self._vals[2]

    def yMaximum(self) -> float:
        return self._vals[3]


def _write_geotiff(
    path: str,
    arr: np.ndarray,
    geotransform,
    epsg: int,
    nodata: float = -32767.0,
) -> None:
    from osgeo import gdal, osr

    if gdal.GetDriverCount() == 0:
        gdal.AllRegister()
    gdal.UseExceptions()
    h, w = arr.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(geotransform)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(nodata))
    band.WriteArray(arr.astype(np.float32))
    ds.FlushCache()
    ds = None


def _project_utm_box_to_epsg3979(utm_bounds, wkid: int):
    from osgeo import osr

    src = osr.SpatialReference()
    src.ImportFromEPSG(int(wkid))
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(3979)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)

    xmin, ymin, xmax, ymax = utm_bounds
    pts = [
        ct.TransformPoint(xmin, ymin),
        ct.TransformPoint(xmin, ymax),
        ct.TransformPoint(xmax, ymin),
        ct.TransformPoint(xmax, ymax),
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


class TestCanadaConfigAndUTM(unittest.TestCase):
    def test_canada_dem_presets_and_config_properties(self) -> None:
        self.assertIn("canada-hrdem", DEM_PRESETS)
        self.assertIn("canada-hrdem-dsm", DEM_PRESETS)
        self.assertIn("canada-mrdem", DEM_PRESETS)
        self.assertIn("world-topo", BASEMAP_PRESETS)
        self.assertIn("canada-topo", BASEMAP_PRESETS)

        self.assertTrue(is_canada_dem_source("canada-hrdem"))
        self.assertTrue(is_canada_dem_source("nrcan-hrdem-dsm"))
        self.assertFalse(is_canada_dem_source("usgs-3dep"))
        self.assertFalse(is_canada_dsm_source("canada-hrdem"))
        self.assertTrue(is_canada_dsm_source("canada-hrdem-dsm"))
        self.assertTrue(is_canada_dsm_source("canada-mrdem-dsm"))

        cfg = LoRaGISConfig(dem_source="canada-hrdem-dsm")
        self.assertTrue(cfg.is_canada_dem)
        self.assertTrue(cfg.use_canada_dsm)
        self.assertTrue(cfg.is_dsm_mode)
        self.assertEqual(cfg.surface_kind_label, "NRCan HRDEM 1m LiDAR DSM")

        cfg_dtm = LoRaGISConfig(dem_source="canada-hrdem")
        self.assertTrue(cfg_dtm.is_canada_dem)
        self.assertFalse(cfg_dtm.use_canada_dsm)
        self.assertFalse(cfg_dtm.is_dsm_mode)

    def test_cli_and_json_canada_options(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--dem",
                "canada-hrdem-dsm",
                "--province",
                "ON",
                "--basemap",
                "canada-topo",
            ],
        )
        self.assertEqual(cfg.dem_source, "canada-hrdem-dsm")
        self.assertTrue(cfg.dem_explicit)
        self.assertEqual(cfg.default_state, "ON")
        self.assertEqual(cfg.basemap, "canada-topo")
        self.assertTrue(cfg.basemap_explicit)

        with tempfile.TemporaryDirectory() as tmpdir:
            jpath = os.path.join(tmpdir, "ca.json")
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "default_province": "BC",
                        "dem_source": "canada-mrdem",
                        "cgndb_url": "https://example.invalid/cgndb.json",
                        "nrcan_stac_url": "https://example.invalid/stac/search",
                    },
                    f,
                )
            cfg_j = LoRaGISConfig()
            cfg_j.load_json_config(jpath)
        self.assertEqual(cfg_j.default_state, "BC")
        self.assertEqual(cfg_j.dem_source, "canada-mrdem")
        self.assertTrue(cfg_j.dem_explicit)
        self.assertEqual(cfg_j.cgndb_url, "https://example.invalid/cgndb.json")
        self.assertEqual(cfg_j.nrcan_stac_url, "https://example.invalid/stac/search")

    def test_smart_canada_defaults_respect_explicit_overrides(self) -> None:
        cfg_route = LoRaGISConfig(
            locations={
                "ottawa": {"name": "Ottawa", "lat": 45.42, "lon": -75.70, "height_m": 10.0, "country": "CA"},
                "gatineau": {"name": "Gatineau", "lat": 45.47, "lon": -75.70, "height_m": 10.0, "country": "CA"},
            }
        )
        _apply_canada_smart_defaults(cfg_route, ["ottawa", "gatineau"], is_city=False)
        self.assertEqual(cfg_route.dem_source, "canada-hrdem")
        self.assertEqual(cfg_route.basemap, "world-topo")

        cfg_city = LoRaGISConfig(
            locations={
                "ottawa": {"name": "Ottawa", "lat": 45.42, "lon": -75.70, "height_m": 10.0, "country": "CA"},
            }
        )
        _apply_canada_smart_defaults(cfg_city, ["ottawa"], is_city=True)
        self.assertEqual(cfg_city.dem_source, "canada-hrdem-dsm")

        cfg_explicit = LoRaGISConfig(
            dem_source="canada-mrdem",
            dem_explicit=True,
            basemap="satellite",
            basemap_explicit=True,
            locations={
                "ottawa": {"name": "Ottawa", "lat": 45.42, "lon": -75.70, "height_m": 10.0, "country": "CA"},
            },
        )
        _apply_canada_smart_defaults(cfg_explicit, ["ottawa"], is_city=True)
        self.assertEqual(cfg_explicit.dem_source, "canada-mrdem")
        self.assertEqual(cfg_explicit.basemap, "satellite")

    def test_utm_detection_across_canada_zones_7_to_22(self) -> None:
        # Whitehorse, YT -> Zone 8N (EPSG:26908)
        self.assertEqual(detect_utm_crs(60.7212, -135.0568), ("EPSG:26908", 26908, "UTM Zone 8N"))
        # Prince Rupert, BC -> Zone 9N (EPSG:26909)
        self.assertEqual(detect_utm_crs(54.3150, -130.3208), ("EPSG:26909", 26909, "UTM Zone 9N"))
        # Vancouver, BC -> Zone 10N (EPSG:26910)
        self.assertEqual(detect_utm_crs(49.2827, -123.1207), ("EPSG:26910", 26910, "UTM Zone 10N"))
        # Ottawa, ON -> Zone 18N (EPSG:26918)
        self.assertEqual(detect_utm_crs(45.4215, -75.6972), ("EPSG:26918", 26918, "UTM Zone 18N"))
        # St. John's, NL -> Zone 22N (EPSG:26922)
        self.assertEqual(detect_utm_crs(47.5615, -52.7126), ("EPSG:26922", 26922, "UTM Zone 22N"))
        # Iqaluit, NU -> Zone 19N (EPSG:26919)
        self.assertEqual(detect_utm_crs(63.7467, -68.5170), ("EPSG:26919", 26919, "UTM Zone 19N"))


class TestNRCanSTACAndCOGStreaming(unittest.TestCase):
    def test_utm_bounds_to_wgs84_bbox(self) -> None:
        w, s, e, n = utm_bounds_to_wgs84_bbox((444000.0, 5029000.0, 446000.0, 5031000.0), 26918)
        self.assertLess(w, e)
        self.assertLess(s, n)
        self.assertTrue(-76.0 < w < -75.5)
        self.assertTrue(45.3 < s < 45.5)

    def test_search_nrcan_stac_assets_parses_and_deduplicates(self) -> None:
        seen_urls = []

        def fake_urlopen(req, timeout=20.0):
            seen_urls.append(req.full_url)
            return _MockHTTPResponse(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "id": "9_2-mosaic-1m",
                            "assets": {
                                "dtm": {"href": "https://example.invalid/9_2-dtm.tif"},
                                "dsm": {"href": "https://example.invalid/9_2-dsm.tif"},
                            },
                        },
                        {
                            "id": "9_2-mosaic-1m-dup",
                            "assets": {
                                "dtm": {"href": "https://example.invalid/9_2-dtm.tif"},
                                "dsm": {"href": "https://example.invalid/9_2-dsm.tif"},
                            },
                        },
                    ],
                }
            )

        with patch("lora_gis.nrcan.urllib.request.urlopen", side_effect=fake_urlopen):
            dtm_hrefs = search_nrcan_stac_assets("hrdem-mosaic-1m", (-75.73, 45.40, -75.67, 45.44), asset_key="dtm")
            dsm_hrefs = search_nrcan_stac_assets("hrdem-mosaic-1m", (-75.73, 45.40, -75.67, 45.44), asset_key="dsm")

        self.assertEqual(dtm_hrefs, ["https://example.invalid/9_2-dtm.tif"])
        self.assertEqual(dsm_hrefs, ["https://example.invalid/9_2-dsm.tif"])
        self.assertIn("collections=hrdem-mosaic-1m", seen_urls[0])
        self.assertIn("bbox=-75.730000", seen_urls[0])

    def test_multi_tile_stitching_nodata_gap_fill_and_caching(self) -> None:
        utm_bounds = (444000.0, 5029000.0, 445000.0, 5030000.0)
        wkid = 26918
        lx0, ly0, lx1, ly1 = _project_utm_box_to_epsg3979(utm_bounds, wkid)
        pad = 250.0
        lx0 -= pad
        ly0 -= pad
        lx1 += pad
        ly1 += pad
        lmid = 0.5 * (lx0 + lx1)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Two adjacent EPSG:3979 tiles for hrdem-mosaic-1m, with a NoData hole in tile_b
            tile_a = os.path.join(tmpdir, "tile_a_dtm.tif")
            tile_b = os.path.join(tmpdir, "tile_b_dtm.tif")
            fallback_tif = os.path.join(tmpdir, "mrdem_30_dtm.tif")

            w_half = 40
            h_full = 60
            px_w_a = (lmid - lx0) / w_half
            px_w_b = (lx1 - lmid) / w_half
            px_h = (ly1 - ly0) / h_full

            arr_a = np.full((h_full, w_half), 75.0, dtype=np.float32)
            arr_b = np.full((h_full, w_half), 85.0, dtype=np.float32)
            # Carve a NoData gap in the right half of tile_b
            arr_b[:, w_half // 2 :] = -32767.0
            arr_fb = np.full((h_full, w_half * 2), 95.0, dtype=np.float32)

            _write_geotiff(tile_a, arr_a, (lx0, px_w_a, 0.0, ly1, 0.0, -px_h), epsg=3979)
            _write_geotiff(tile_b, arr_b, (lmid, px_w_b, 0.0, ly1, 0.0, -px_h), epsg=3979)
            _write_geotiff(fallback_tif, arr_fb, (lx0, (lx1 - lx0) / (w_half * 2), 0.0, ly1, 0.0, -px_h), epsg=3979)

            search_calls = []

            def fake_search(collection, bbox_wgs84_wsen, asset_key="dtm", **kwargs):
                search_calls.append((collection, asset_key))
                if collection == "hrdem-mosaic-1m":
                    return [tile_a, tile_b]
                if collection == "hrdem-mosaic-2m":
                    return []
                if collection == "mrdem-30":
                    return [fallback_tif]
                return []

            cache_dir = os.path.join(tmpdir, "cache")
            with patch("lora_gis.nrcan.search_nrcan_stac_assets", side_effect=fake_search):
                arr, xmin, ymin, xmax, ymax, out_w, out_h, used = stream_nrcan_elevation_grid(
                    collections=("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
                    asset_key="dtm",
                    utm_bounds=utm_bounds,
                    wkid=wkid,
                    resolution_m=20.0,
                    max_px=200,
                    resample_mode="nearest",
                    cache_dir=cache_dir,
                )

            self.assertEqual(used, ["hrdem-mosaic-1m", "mrdem-30"])
            self.assertEqual((out_w, out_h), (50, 50))
            self.assertTrue(np.all(np.isfinite(arr)))
            # Left side from tile_a (~75m), right side backfilled from mrdem-30 (~95m)
            self.assertAlmostEqual(float(arr[25, 2]), 75.0, delta=0.5)
            self.assertAlmostEqual(float(arr[25, -2]), 95.0, delta=0.5)
            self.assertEqual(len(search_calls), 3)

            # Second call with identical bounds/params should hit disk cache without calling STAC
            with patch("lora_gis.nrcan.search_nrcan_stac_assets", side_effect=AssertionError("should use cache")):
                arr2, _, _, _, _, _, _, used2 = stream_nrcan_elevation_grid(
                    collections=("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
                    asset_key="dtm",
                    utm_bounds=utm_bounds,
                    wkid=wkid,
                    resolution_m=20.0,
                    max_px=200,
                    resample_mode="nearest",
                    cache_dir=cache_dir,
                )
            self.assertEqual(used2, ["hrdem-mosaic-1m", "mrdem-30"])
            self.assertTrue(np.allclose(arr, arr2))

    def test_dem_provider_loads_canada_hrdem_dsm_and_guards_fetch_elevations(self) -> None:
        utm_bounds = (444000.0, 5029000.0, 445000.0, 5030000.0)
        wkid = 26918
        lx0, ly0, lx1, ly1 = _project_utm_box_to_epsg3979(utm_bounds, wkid)
        pad = 250.0
        lx0 -= pad
        ly0 -= pad
        lx1 += pad
        ly1 += pad

        with tempfile.TemporaryDirectory() as tmpdir:
            dtm_tif = os.path.join(tmpdir, "hrdem_dtm.tif")
            dsm_tif = os.path.join(tmpdir, "hrdem_dsm.tif")
            dtm_arr = np.full((60, 60), 65.0, dtype=np.float32)
            dsm_arr = np.full((60, 60), 65.0, dtype=np.float32)
            dsm_arr[20:40, 20:40] = 145.0  # 80m downtown tower in DSM
            gt = (lx0, (lx1 - lx0) / 60.0, 0.0, ly1, 0.0, -(ly1 - ly0) / 60.0)
            _write_geotiff(dtm_tif, dtm_arr, gt, epsg=3979)
            _write_geotiff(dsm_tif, dsm_arr, gt, epsg=3979)

            def fake_search(collection, bbox_wgs84_wsen, asset_key="dtm", **kwargs):
                if collection == "hrdem-mosaic-1m":
                    return [dtm_tif if asset_key == "dtm" else dsm_tif]
                return []

            dem = DEMProvider(
                image_server_base="https://datacube.services.geo.ca/stac/api/search",
                wkid=wkid,
                sampling_mode="nearest",
                dem_source="canada-hrdem-dsm",
            )
            with patch("lora_gis.nrcan.search_nrcan_stac_assets", side_effect=fake_search):
                with patch("lora_gis.nrcan.tempfile.gettempdir", return_value=tmpdir):
                    dem.load_raster(*utm_bounds, resolution_m=20.0, max_px=100)

            self.assertIsNotNone(dem.cache)
            self.assertTrue(dem.has_separate_surface)
            ground_mid = float(dem.sample_ground(np.array([444500.0]), np.array([5029500.0]))[0])
            surf_mid = float(dem.sample_surface(np.array([444500.0]), np.array([5029500.0]))[0])
            self.assertAlmostEqual(ground_mid, 65.0, delta=0.5)
            self.assertAlmostEqual(surf_mid, 145.0, delta=0.5)

            # Out-of-bounds fetch_elevations must NOT attempt ArcGIS getSamples HTTP call
            with patch("lora_gis.dem.urllib.request.urlopen", side_effect=AssertionError("must not call ArcGIS")):
                elevs = dem.fetch_elevations([(444500.0, 5029500.0), (100000.0, 100000.0)])
            self.assertAlmostEqual(elevs[0], 65.0, delta=0.5)
            self.assertEqual(elevs[1], -9999.0)


class TestCGNDBGeoNames(unittest.TestCase):
    def test_province_codes_cover_all_13_and_never_collide_with_us_states(self) -> None:
        self.assertEqual(len(CANADA_PROVINCE_CODES), 13)
        for prov in ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"):
            self.assertTrue(is_canada_province(prov))
        for us_st in ("NY", "KS", "CA", "NE", "PA", "OH", "OK", "OR", "WA", "MT", "ME"):
            self.assertFalse(is_canada_province(us_st))

    def test_lookup_cgndb_place_maps_sgc_code_and_ranks_city_over_river(self) -> None:
        requested = []

        def fake_urlopen(req, timeout=8.0):
            requested.append(req.full_url)
            return _MockHTTPResponse(
                {
                    "items": [
                        {
                            "name": "Ottawa River",
                            "latitude": 45.34,
                            "longitude": -73.96,
                            "concise": {"code": "RIV"},
                            "status": {"code": "official"},
                        },
                        {
                            "name": "Ottawa",
                            "latitude": 45.33339,
                            "longitude": -75.58429,
                            "concise": {"code": "CITY"},
                            "status": {"code": "official"},
                        },
                    ]
                }
            )

        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=fake_urlopen):
            found = lookup_cgndb_place("Ottawa, ON", default_height_m=12.0)

        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Ottawa")
        self.assertAlmostEqual(found["lat"], 45.33339)
        self.assertAlmostEqual(found["lon"], -75.58429)
        self.assertAlmostEqual(found["height_m"], 12.0)
        self.assertEqual(found["country"], "CA")
        self.assertIn("province=35", requested[0])

    def test_lookup_geonames_place_routes_canadian_provinces_to_cgndb(self) -> None:
        requested = []

        def fake_urlopen(req, timeout=8.0):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            requested.append(url)
            return _MockHTTPResponse(
                {
                    "items": [
                        {
                            "name": "Banff",
                            "latitude": 51.1784,
                            "longitude": -115.5708,
                            "concise": {"code": "TOWN"},
                            "status": {"code": "official"},
                        }
                    ]
                }
            )

        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=fake_urlopen):
            found = lookup_geonames_place(
                "Banff, AB",
                geonames_url="https://usgs.invalid/geonames",
                default_height_m=10.0,
                cgndb_url="https://cgndb.invalid/geonames.json",
            )

        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Banff")
        self.assertEqual(found["country"], "CA")
        self.assertEqual(len(requested), 1)
        self.assertTrue(requested[0].startswith("https://cgndb.invalid/geonames.json"))
        self.assertIn("province=48", requested[0])

    def test_fetch_cgndb_features_extracts_peaks_and_towns_in_utm(self) -> None:
        def fake_urlopen(req, timeout=8.0):
            url = req.full_url
            if "concise=MTN" in url:
                return _MockHTTPResponse(
                    {
                        "items": [
                            {
                                "name": "Tunnel Mountain",
                                "latitude": 51.1764,
                                "longitude": -115.5547,
                                "concise": {"code": "MTN"},
                            },
                            {
                                "name": "Tunnel Mountain",
                                "latitude": 51.1765,
                                "longitude": -115.5548,
                                "concise": {"code": "MTN"},
                            },
                            {
                                "name": "Rocky Mountains",
                                "latitude": 54.5,
                                "longitude": -122.5,
                                "concise": {"code": "MTN"},
                            },
                        ]
                    }
                )
            return _MockHTTPResponse(
                {
                    "items": [
                        {
                            "name": "Banff",
                            "latitude": 51.1784,
                            "longitude": -115.5708,
                            "concise": {"code": "TOWN"},
                        },
                        {
                            "name": "Whiskey Creek",
                            "latitude": 51.1842,
                            "longitude": -115.5778,
                            "concise": {"code": "RIV"},
                        },
                    ]
                }
            )

        # Banff UTM Zone 11N (EPSG:26911)
        rect = _FakeRect(595000.0, 5665000.0, 606000.0, 5676000.0)
        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=fake_urlopen):
            peaks, towns = fetch_geonames_features(
                rect,
                26911,
                "https://usgs.invalid/geonames",
                use_canada=True,
                cgndb_url="https://cgndb.invalid/geonames.json",
            )

        self.assertEqual(len(peaks), 1)
        self.assertEqual(peaks[0][0], "Tunnel Mountain")
        self.assertTrue(595000.0 < peaks[0][1][0] < 606000.0)
        self.assertEqual(len(towns), 1)
        self.assertEqual(towns[0][0], "Banff")


class TestCanadaHeadlessPipeline(unittest.TestCase):
    def test_canada_city_viewshed_with_hrdem_dsm_headless(self) -> None:
        # Synthetic Ottawa EPSG:3979 DTM + DSM with a tall rooftop peak
        from osgeo import osr

        src = osr.SpatialReference()
        src.ImportFromEPSG(4326)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        dst = osr.SpatialReference()
        dst.ImportFromEPSG(26918)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(src, dst)
        cx, cy, _ = ct.TransformPoint(-75.6972, 45.4215)

        rad = 800.0
        pad = 350.0
        utm_bounds = (cx - rad - pad, cy - rad - pad, cx + rad + pad, cy + rad + pad)
        lx0, ly0, lx1, ly1 = _project_utm_box_to_epsg3979(utm_bounds, 26918)
        lx0 -= 400.0
        ly0 -= 400.0
        lx1 += 400.0
        ly1 += 400.0

        with tempfile.TemporaryDirectory() as tmpdir:
            dtm_tif = os.path.join(tmpdir, "ottawa_dtm.tif")
            dsm_tif = os.path.join(tmpdir, "ottawa_dsm.tif")
            dtm_arr = np.full((120, 120), 70.0, dtype=np.float32)
            dsm_arr = np.full((120, 120), 70.0, dtype=np.float32)
            dsm_arr[55:65, 55:65] = 150.0  # 80m tall tower near center
            gt = (lx0, (lx1 - lx0) / 120.0, 0.0, ly1, 0.0, -(ly1 - ly0) / 120.0)
            _write_geotiff(dtm_tif, dtm_arr, gt, epsg=3979)
            _write_geotiff(dsm_tif, dsm_arr, gt, epsg=3979)

            def fake_search(collection, bbox_wgs84_wsen, asset_key="dtm", **kwargs):
                if collection == "hrdem-mosaic-1m":
                    return [dtm_tif if asset_key == "dtm" else dsm_tif]
                return []

            cfg = LoRaGISConfig(
                city_target="Ottawa=45.4215,-75.6972",
                city_radius_m=rad,
                city_top_n=3,
                city_max_sites=3,
                viewshed_grid_size=21,
                dem_source="canada-hrdem-dsm",
                dem_explicit=True,
                buildings_source="none",
                buildings_explicit=True,
                basemap="osm",
                basemap_explicit=True,
                output_dir=os.path.join(tmpdir, "out"),
            )
            with patch("lora_gis.nrcan.search_nrcan_stac_assets", side_effect=fake_search):
                with patch("lora_gis.nrcan.tempfile.gettempdir", return_value=tmpdir):
                    res = run_analysis(cfg)

            self.assertEqual(res["mode"], "city")
            self.assertTrue(os.path.isfile(res["png_output_path"]))
            self.assertTrue(os.path.isfile(res["md_output_path"]))
            with open(res["md_output_path"], "r", encoding="utf-8") as f:
                md_text = f.read()
            self.assertIn("NRCan HRDEM 1m LiDAR DSM", md_text)
            self.assertIn("Ottawa", md_text)


if __name__ == "__main__":
    unittest.main()
