"""Unit tests for Phase 1: georeferenced DSM/DEM GeoTIFF loading, units, and urban sampling."""

import json
import os
import tempfile
import unittest

import numpy as np

from lora_gis.cli import apply_cli_args
from lora_gis.config import BASEMAP_PRESETS, FEET_TO_METERS, LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.rf import analyze_link_profile, evaluate_segments_vectorized


def _write_geotiff(path: str, arr: np.ndarray, geotransform, epsg: int, nodata: float = -9999.0) -> None:
    from osgeo import gdal, osr

    if gdal.GetDriverCount() == 0:
        gdal.AllRegister()
    gdal.UseExceptions()
    h, w = arr.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(geotransform)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr.astype(np.float32))
    band.FlushCache()
    ds = None


class TestPhase1ConfigAndCLI(unittest.TestCase):
    def test_cli_flags_and_properties(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--route",
                "a=38.8403,-97.6114",
                "b=38.8503,-97.6114",
                "--dem-units",
                "ft",
                "--surface-mode",
                "dsm",
                "--sample-step",
                "4.0",
                "--rooftop-margin",
                "30ft",
                "--basemap",
                "osm",
            ],
        )
        self.assertAlmostEqual(cfg.dem_unit_scale, FEET_TO_METERS, places=6)
        self.assertTrue(cfg.is_dsm_mode)
        self.assertAlmostEqual(cfg.effective_sample_step_m, 4.0)
        self.assertAlmostEqual(cfg.effective_rooftop_margin_m, 30.0 / 3.28084, places=3)
        self.assertEqual(cfg.active_basemap_url, BASEMAP_PRESETS["osm"])

    def test_dsm_file_implies_dsm_mode_and_defaults(self) -> None:
        cfg = LoRaGISConfig(dsm_file="/tmp/fake_dsm.tif")
        self.assertTrue(cfg.is_dsm_mode)
        self.assertAlmostEqual(cfg.effective_sample_step_m, 5.0)
        self.assertAlmostEqual(cfg.effective_rooftop_margin_m, 12.0)

    def test_json_config_loads_phase1_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "city.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "title": "SalinaCityMesh",
                        "dem_units": "ft",
                        "surface_mode": "dsm",
                        "sample_step_m": 3.5,
                        "rooftop_margin": "15m",
                        "basemap": "satellite",
                    },
                    f,
                )
            cfg = LoRaGISConfig()
            cfg.load_json_config(cfg_path)
            self.assertEqual(cfg.title, "SalinaCityMesh")
            self.assertAlmostEqual(cfg.dem_unit_scale, FEET_TO_METERS, places=6)
            self.assertTrue(cfg.is_dsm_mode)
            self.assertAlmostEqual(cfg.effective_sample_step_m, 3.5)
            self.assertAlmostEqual(cfg.effective_rooftop_margin_m, 15.0)
            self.assertEqual(cfg.active_basemap_url, BASEMAP_PRESETS["satellite"])

    def test_invalid_dem_units_raises(self) -> None:
        cfg = LoRaGISConfig(dem_units="furlongs")
        with self.assertRaises(ValueError):
            _ = cfg.dem_unit_scale


class TestPhase1GeotiffAndDSM(unittest.TestCase):
    def test_georeferenced_geotiff_alignment_nodata_and_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tif_path = os.path.join(tmpdir, "city_dsm_ft.tif")
            # 200x200 raster at 2 m/px covering E [620000, 620400], N [4300000, 4300400] in UTM 14N (EPSG:26914)
            # Ground = 1000 ft, building block at cols [90:110], rows [90:110] = 1200 ft, corner = nodata
            arr = np.full((200, 200), 1000.0, dtype=np.float32)
            arr[90:110, 90:110] = 1200.0
            arr[0:5, 0:5] = -9999.0
            gt = (620000.0, 2.0, 0.0, 4300400.0, 0.0, -2.0)
            _write_geotiff(tif_path, arr, gt, epsg=26914, nodata=-9999.0)

            # Intentionally pass a MUCH larger study bbox to prove the GeoTIFF is NOT stretched across it!
            dem = DEMProvider(
                image_server_base="https://example.invalid",
                wkid=26914,
                dem_file=tif_path,
                unit_scale=FEET_TO_METERS,
                sampling_mode="nearest",
            )
            dem.load_raster(618000.0, 4298000.0, 622000.0, 4302000.0)

            # Building center is at x = 620000 + 100*2 = 620200, y = 4300400 - 100*2 = 4300200
            xs = np.array([620200.0, 620050.0, 620002.0, 619000.0])
            ys = np.array([4300200.0, 4300050.0, 4300398.0, 4300200.0])
            vals = dem.sample_surface(xs, ys)

            self.assertAlmostEqual(vals[0], 1200.0 * FEET_TO_METERS, places=2)
            self.assertAlmostEqual(vals[1], 1000.0 * FEET_TO_METERS, places=2)
            self.assertTrue(np.isnan(vals[2]))  # NoData corner
            self.assertTrue(np.isnan(vals[3]))  # Outside GeoTIFF extent

    def test_georeferenced_geotiff_reprojection_wgs84_to_utm(self) -> None:
        from osgeo import osr

        with tempfile.TemporaryDirectory() as tmpdir:
            tif_path = os.path.join(tmpdir, "wgs84_dem.tif")
            # Near Salina, KS (~38.84 N, -97.61 W -> UTM Zone 14N EPSG:26914)
            arr = np.full((100, 100), 375.0, dtype=np.float32)
            gt = (-97.62, 0.0002, 0.0, 38.85, 0.0, -0.0002)
            _write_geotiff(tif_path, arr, gt, epsg=4326)

            src_srs = osr.SpatialReference()
            src_srs.ImportFromEPSG(4326)
            src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            dst_srs = osr.SpatialReference()
            dst_srs.ImportFromEPSG(26914)
            dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            ct = osr.CoordinateTransformation(src_srs, dst_srs)
            ux, uy, _ = ct.TransformPoint(-97.61, 38.84)

            dem = DEMProvider(
                image_server_base="https://example.invalid",
                wkid=26914,
                dem_file=tif_path,
                sampling_mode="bilinear",
            )
            dem.load_raster(ux - 2000.0, uy - 2000.0, ux + 2000.0, uy + 2000.0)
            val = dem.sample_ground(np.array([ux]), np.array([uy]))[0]
            self.assertAlmostEqual(val, 375.0, places=2)

    def test_non_overlapping_geotiff_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tif_path = os.path.join(tmpdir, "far_away.tif")
            arr = np.full((20, 20), 300.0, dtype=np.float32)
            gt = (500000.0, 10.0, 0.0, 4000000.0, 0.0, -10.0)
            _write_geotiff(tif_path, arr, gt, epsg=26914)

            dem = DEMProvider("https://example.invalid", wkid=26914, dem_file=tif_path)
            with self.assertRaises(ValueError):
                dem.load_raster(620000.0, 4300000.0, 621000.0, 4301000.0)

    def test_dsm_dense_sampling_catches_narrow_building(self) -> None:
        # Flat 3000 m x 200 m grid at 2 m/px (1500 x 100 px), ground = 300 m.
        # Place a narrow 10 m wide (5 px) skyscraper of +40 m at x = 1500 m (midpoint).
        w, h = 1500, 100
        ground = np.full((h, w), 300.0, dtype=np.float64)
        surface = ground.copy()
        surface[:, 748:753] = 340.0  # 10 m wide building at x in [1496, 1506]

        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="bilinear")
        dem.cache = (ground, 0.0, 0.0, 3000.0, 200.0, w, h)
        dem.set_surface_raster(surface, 0.0, 0.0, 3000.0, 200.0)

        p1 = (100.0, 100.0)
        p2 = (2900.0, 100.0)

        cfg_dsm = LoRaGISConfig(surface_mode="dsm", sample_step_m=4.0, rooftop_margin_m=12.0)
        prof = analyze_link_profile(dem, cfg_dsm, p1, 10.0, p2, 10.0, include_profile=True)
        self.assertFalse(prof["clear"])
        self.assertLess(prof["min_clearance_m"], -25.0)
        self.assertIn("ground_m", prof["profile"])

        # Vectorized evaluation must agree with single-segment evaluation
        ok, min_clr, _ = evaluate_segments_vectorized(
            dem,
            cfg_dsm,
            np.array([p1], dtype=np.float64),
            10.0,
            np.array([p2], dtype=np.float64),
            10.0,
        )
        self.assertFalse(bool(ok[0]))
        self.assertLess(float(min_clr[0]), -25.0)

    def test_rooftop_margin_avoids_self_blockage_but_catches_distant_building(self) -> None:
        # 1000 m x 100 m grid at 2 m/px (500 x 50 px).
        # Endpoint A at x = 50 m sits on a 320 m roof; a 325 m parapet sits 6 m away at x = 56 m.
        # Endpoint B at x = 950 m sits on a 320 m roof.
        # With 3 m mast (z = 323 m), the parapet at x = 56 m is taller by 2 m,
        # so margin=0 blocks the link while margin=12 m ignores the host roof parapet.
        w, h = 500, 50
        surface = np.full((h, w), 300.0, dtype=np.float64)
        surface[:, 20:32] = 320.0  # Host building A (x = 40..64 m)
        surface[:, 28:29] = 325.0  # Parapet at x = 56..58 m (6 m from x=50)
        surface[:, 470:480] = 320.0  # Host building B (x = 940..960 m)

        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="nearest")
        dem.cache = (surface, 0.0, 0.0, 1000.0, 100.0, w, h)

        p1 = (50.0, 50.0)
        p2 = (950.0, 50.0)

        cfg_no_margin = LoRaGISConfig(surface_mode="dsm", sample_step_m=2.0, rooftop_margin_m=0.0)
        res_no_margin = analyze_link_profile(dem, cfg_no_margin, p1, 3.0, p2, 3.0)
        self.assertFalse(res_no_margin["clear"])

        cfg_with_margin = LoRaGISConfig(surface_mode="dsm", sample_step_m=2.0, rooftop_margin_m=12.0)
        res_with_margin = analyze_link_profile(dem, cfg_with_margin, p1, 3.0, p2, 3.0)
        self.assertTrue(res_with_margin["clear"])

        # Now add an obstructing 335 m building halfway across town (x = 500 m) -> must be blocked!
        surface[:, 248:254] = 335.0
        res_blocked = analyze_link_profile(dem, cfg_with_margin, p1, 3.0, p2, 3.0)
        self.assertFalse(res_blocked["clear"])
        self.assertLess(res_blocked["min_clearance_m"], -10.0)

        ok_vec, clr_vec, _ = evaluate_segments_vectorized(
            dem,
            cfg_with_margin,
            np.array([p1], dtype=np.float64),
            3.0,
            np.array([p2], dtype=np.float64),
            3.0,
        )
        self.assertFalse(bool(ok_vec[0]))
        self.assertLess(float(clr_vec[0]), -10.0)

    def test_end_to_end_local_dem_and_dsm_report(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from lora_gis.cli import run_analysis

        with tempfile.TemporaryDirectory() as tmpdir:
            dem_path = os.path.join(tmpdir, "ground.tif")
            dsm_path = os.path.join(tmpdir, "surface.tif")
            out_dir = os.path.join(tmpdir, "out")

            # Salina, KS area in WGS84: lon [-97.64, -97.58], lat [38.82, 38.86]
            ground = np.full((200, 300), 370.0, dtype=np.float32)
            surface = ground.copy()
            # Tall obstructing building strip across the middle (lon ~ -97.61)
            surface[:, 145:155] = 420.0
            # Tall candidate rooftop to the north (lat ~ 38.85) with clear view over town
            surface[40:60, 140:160] = 435.0
            gt = (-97.64, 0.0002, 0.0, 38.86, 0.0, -0.0002)
            _write_geotiff(dem_path, ground, gt, epsg=4326)
            _write_geotiff(dsm_path, surface, gt, epsg=4326)

            cfg = LoRaGISConfig(
                title="SalinaDSMTest",
                dem_file=dem_path,
                dsm_file=dsm_path,
                surface_mode="dsm",
                sample_step_m=10.0,
                initial_grid_step_m=800.0,
                min_grid_step_m=800.0,
                output_dir=out_dir,
                basemap="osm",
            )
            apply_cli_args(
                cfg,
                argv=[
                    "--route",
                    "west=38.840,-97.625",
                    "east=38.840,-97.595",
                    "--candidates",
                    "tower=38.850,-97.610",
                    "--candidate-height",
                    "10ft",
                    "--hops",
                    "1",
                ],
            )
            res = run_analysis(cfg)
            self.assertEqual(len(res["link_results"]), 1)
            lr = res["link_results"][0]
            self.assertFalse(lr["direct_clear"])
            self.assertTrue(os.path.isfile(res["md_output_path"]))
            self.assertTrue(os.path.isfile(res["png_output_path"]))
            with open(res["md_output_path"], "r", encoding="utf-8") as f:
                md_txt = f.read()
            self.assertIn("DSM (nearest-neighbor", md_txt)
            self.assertIn("Tower", md_txt)


if __name__ == "__main__":
    unittest.main()
