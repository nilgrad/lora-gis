"""Unit tests for Phase 3: city rooftop ranking, radial viewshed scoring, and multi-site optimization."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from lora_gis.buildings import BuildingFeature, rasterize_buildings_onto_dem
from lora_gis.cli import apply_cli_args, run_analysis
from lora_gis.config import FEET_TO_METERS, LoRaGISConfig, parse_distance_m
from lora_gis.dem import DEMProvider
from lora_gis.viewshed import (
    CityCandidateResult,
    build_city_target_grid,
    build_coverage_grid_2d,
    evaluate_candidate_viewshed,
    extract_dsm_peak_candidates,
    optimize_site_combinations,
)


class _MockHTTPResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _FakePoint:
    def __init__(self, x: float, y: float):
        self._x = x
        self._y = y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class _FakeInvTransform:
    def transform(self, pt) -> _FakePoint:
        return _FakePoint(-97.62 + pt.x() / 100000.0, 38.83 + pt.y() / 100000.0)


def _write_geotiff(path: str, arr: np.ndarray, geotransform, epsg: int) -> None:
    from osgeo import gdal, osr

    if gdal.GetDriverCount() == 0:
        gdal.AllRegister()
    gdal.UseExceptions()
    h, w = arr.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(geotransform)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(arr.astype(np.float32))
    ds.FlushCache()
    ds = None


class TestPhase3ConfigAndParsing(unittest.TestCase):
    def test_parse_distance_m(self) -> None:
        self.assertAlmostEqual(parse_distance_m("3km"), 3000.0)
        self.assertAlmostEqual(parse_distance_m("2 mi"), 2.0 * 1609.344, places=3)
        self.assertAlmostEqual(parse_distance_m("2500m"), 2500.0)
        self.assertAlmostEqual(parse_distance_m("5000ft"), 5000.0 * FEET_TO_METERS, places=3)
        self.assertAlmostEqual(parse_distance_m(1800), 1800.0)

    def test_city_cli_and_json_options(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--city",
                "salina=38.8403,-97.6114",
                "--radius",
                "2mi",
                "--top",
                "8",
                "--rx-height",
                "25ft",
                "--mast-height",
                "15ft",
                "--max-sites",
                "20",
                "--viewshed-grid",
                "41",
            ],
        )
        self.assertEqual(cfg.city_target, "salina=38.8403,-97.6114")
        self.assertTrue(cfg.is_dsm_mode)
        self.assertAlmostEqual(cfg.city_radius_m, 2.0 * 1609.344, places=2)
        self.assertEqual(cfg.city_top_n, 8)
        self.assertAlmostEqual(cfg.city_rx_height_m, 25.0 / 3.28084, places=3)
        self.assertAlmostEqual(cfg.city_mast_height_m, 15.0 / 3.28084, places=3)
        self.assertEqual(cfg.city_max_sites, 20)
        self.assertEqual(cfg.viewshed_grid_size, 41)

        with tempfile.TemporaryDirectory() as tmpdir:
            jpath = os.path.join(tmpdir, "city.json")
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "city": "Salina, KS",
                        "radius": "4km",
                        "top": 12,
                        "rx_height": "10ft",
                        "mast_height": "12ft",
                        "max_sites": 30,
                        "viewshed_grid": 51,
                    },
                    f,
                )
            cfg_j = LoRaGISConfig()
            cfg_j.load_json_config(jpath)
            self.assertEqual(cfg_j.city_target, "Salina, KS")
            self.assertAlmostEqual(cfg_j.city_radius_m, 4000.0)
            self.assertEqual(cfg_j.city_top_n, 12)
            self.assertEqual(cfg_j.city_max_sites, 30)
            self.assertEqual(cfg_j.viewshed_grid_size, 51)


class TestViewshedEngineAndSetCover(unittest.TestCase):
    def test_viewshed_tall_tower_beats_shadowed_building(self) -> None:
        # 2000 m x 2000 m flat city at 300 m ASL
        ground = np.full((200, 200), 300.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="bilinear")
        dem.cache = (ground, 0.0, 0.0, 2000.0, 2000.0, 200, 200)

        tall_tower = BuildingFeature(
            osm_id="way/1",
            name="Central Tower",
            structure_type="water_tower",
            lat=38.84,
            lon=-97.61,
            x=1000.0,
            y=1000.0,
            height_m=55.0,
            height_source="height",
            polygons_utm=[[(990.0, 990.0), (1010.0, 990.0), (1010.0, 1010.0), (990.0, 1010.0)]],
        )
        # Huge 45 m wall right next to a 8 m low roof at (1000, 600)
        blocker_wall = BuildingFeature(
            osm_id="way/2",
            name="Big Blocker",
            structure_type="office",
            lat=38.838,
            lon=-97.61,
            x=1000.0,
            y=660.0,
            height_m=45.0,
            height_source="height",
            polygons_utm=[[(700.0, 640.0), (1300.0, 640.0), (1300.0, 680.0), (700.0, 680.0)]],
        )
        low_roof = BuildingFeature(
            osm_id="way/3",
            name="Low Roof",
            structure_type="building",
            lat=38.837,
            lon=-97.61,
            x=1000.0,
            y=600.0,
            height_m=8.0,
            height_source="height",
            polygons_utm=[[(985.0, 585.0), (1015.0, 585.0), (1015.0, 615.0), (985.0, 615.0)]],
        )

        rasterize_buildings_onto_dem(dem, [tall_tower, blocker_wall, low_roof], target_res_m=4.0)
        tg = build_city_target_grid((1000.0, 1000.0), radius_m=850.0, grid_size=31)
        cfg = LoRaGISConfig(city_target="test", sample_step_m=10.0, rooftop_margin_m=15.0)

        los_tall, f1_tall, max_los_tall, _ = evaluate_candidate_viewshed(
            dem, cfg, (1000.0, 1000.0), 3.0, tg["target_xy"], rx_height_m=2.0
        )
        los_low, f1_low, _, _ = evaluate_candidate_viewshed(
            dem, cfg, (1000.0, 600.0), 3.0, tg["target_xy"], rx_height_m=2.0
        )

        self.assertGreater(int(np.sum(f1_tall)), int(np.sum(f1_low)) * 1.3)
        self.assertGreater(int(np.sum(los_tall)), int(np.sum(los_low)))
        self.assertGreater(max_los_tall, 700.0)

        cov_2d = build_coverage_grid_2d(tg, los_tall, f1_tall)
        self.assertEqual(cov_2d.shape, (31, 31))
        self.assertTrue(np.any(cov_2d == 2))

    def test_greedy_set_cover_picks_complementary_sites(self) -> None:
        n = 100
        west = np.zeros(n, dtype=bool)
        west[:55] = True
        west_overlap = np.zeros(n, dtype=bool)
        west_overlap[:52] = True
        east = np.zeros(n, dtype=bool)
        east[45:] = True

        def _make(key: str, name: str, mask: np.ndarray) -> CityCandidateResult:
            cnt = int(np.sum(mask))
            return CityCandidateResult(
                key=key,
                name=name,
                structure_type="building",
                address=None,
                lat=38.84,
                lon=-97.61,
                x=0.0,
                y=0.0,
                ground_elev_m=300.0,
                structure_height_m=40.0,
                mast_height_m=3.0,
                height_source="height",
                los_pct=float(cnt),
                f1_pct=float(cnt),
                los_count=cnt,
                f1_count=cnt,
                total_targets=n,
                max_los_range_m=2000.0,
                max_f1_range_m=2000.0,
                los_mask=mask,
                f1_mask=mask,
            )

        c_west = _make("a", "West Tower", west)
        c_overlap = _make("b", "West Annex", west_overlap)
        c_east = _make("c", "East Silo", east)

        combos = optimize_site_combinations([c_west, c_overlap, c_east], max_combo_size=3)
        self.assertEqual(len(combos), 3)
        # 1-site picks West Tower (55%)
        self.assertEqual(combos[0]["added"].key, "a")
        self.assertAlmostEqual(combos[0]["cumulative_f1_pct"], 55.0)
        # 2-site MUST pick complementary East Silo (+45% -> 100%) instead of West Annex (+0%)
        self.assertEqual(combos[1]["added"].key, "c")
        self.assertAlmostEqual(combos[1]["marginal_f1_pct"], 45.0)
        self.assertAlmostEqual(combos[1]["cumulative_f1_pct"], 100.0)

    def test_extract_dsm_peak_candidates(self) -> None:
        arr = np.full((200, 200), 300.0, dtype=np.float64)
        # Two distinct peaks 600 m apart (10 m/px -> 2000 m x 2000 m)
        arr[60:64, 60:64] = 355.0
        arr[120:124, 120:124] = 345.0
        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="nearest")
        dem.cache = (arr, 0.0, 0.0, 2000.0, 2000.0, 200, 200)

        peaks = extract_dsm_peak_candidates(
            dem=dem,
            center_xy=(1000.0, 1000.0),
            radius_m=900.0,
            inv_transform=_FakeInvTransform(),
            count=5,
            min_height_m=20.0,
            min_separation_m=200.0,
        )
        self.assertEqual(len(peaks), 2)
        self.assertGreaterEqual(peaks[0].height_m, 50.0)
        self.assertGreaterEqual(peaks[1].height_m, 40.0)


class TestPhase3EndToEndCityMode(unittest.TestCase):
    def test_end_to_end_city_mode_with_osm_buildings(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        with tempfile.TemporaryDirectory() as tmpdir:
            dem_path = os.path.join(tmpdir, "salina_ground.tif")
            out_dir = os.path.join(tmpdir, "out")
            ground = np.full((200, 200), 370.0, dtype=np.float32)
            gt = (-97.63, 0.0002, 0.0, 38.86, 0.0, -0.0002)
            _write_geotiff(dem_path, ground, gt, epsg=4326)

            mock_overpass = {
                "elements": [
                    {
                        "type": "way",
                        "id": 101,
                        "tags": {
                            "building": "office",
                            "name": "United Building",
                            "height": "46 m",
                            "addr:housenumber": "119",
                            "addr:street": "S Santa Fe Ave",
                        },
                        "geometry": [
                            {"lat": 38.8400, "lon": -97.6105},
                            {"lat": 38.8400, "lon": -97.6095},
                            {"lat": 38.8408, "lon": -97.6095},
                            {"lat": 38.8408, "lon": -97.6105},
                            {"lat": 38.8400, "lon": -97.6105},
                        ],
                    },
                    {
                        "type": "node",
                        "id": 202,
                        "lat": 38.8460,
                        "lon": -97.6050,
                        "tags": {
                            "man_made": "water_tower",
                            "name": "East Water Tower",
                            "height": "42 m",
                        },
                    },
                    {
                        "type": "way",
                        "id": 303,
                        "tags": {"building": "commercial", "name": "Downtown Block", "height": "22 m"},
                        "geometry": [
                            {"lat": 38.8360, "lon": -97.6140},
                            {"lat": 38.8360, "lon": -97.6120},
                            {"lat": 38.8375, "lon": -97.6120},
                            {"lat": 38.8375, "lon": -97.6140},
                            {"lat": 38.8360, "lon": -97.6140},
                        ],
                    },
                ]
            }

            cfg = LoRaGISConfig(
                title="SalinaCityTest",
                dem_file=dem_path,
                buildings_source="osm",
                buildings_explicit=True,
                output_dir=out_dir,
            )
            apply_cli_args(
                cfg,
                argv=[
                    "--city",
                    "salina=38.8403,-97.6100",
                    "--radius",
                    "1.2km",
                    "--top",
                    "5",
                    "--rx-height",
                    "6ft",
                    "--mast-height",
                    "10ft",
                    "--viewshed-grid",
                    "25",
                ],
            )

            with patch(
                "lora_gis.buildings.urllib.request.urlopen",
                return_value=_MockHTTPResponse(mock_overpass),
            ):
                res = run_analysis(cfg)

            self.assertEqual(res["mode"], "city")
            self.assertEqual(res["buildings_count"], 3)
            self.assertEqual(len(res["city_result"]["top_results"]), 3)
            self.assertGreaterEqual(len(res["city_result"]["combos"]), 2)
            self.assertTrue(os.path.isfile(res["png_output_path"]))
            self.assertTrue(os.path.isfile(res["md_output_path"]))

            with open(res["md_output_path"], "r", encoding="utf-8") as f:
                md_txt = f.read()
            self.assertIn("City Viewshed & Rooftop Ranking", md_txt)
            self.assertIn("United Building", md_txt)
            self.assertIn("119 S Santa Fe Ave", md_txt)
            self.assertIn("East Water Tower", md_txt)
            self.assertIn("Optimal Multi-Site Combinations", md_txt)

    def test_end_to_end_city_mode_local_dsm_peaks_without_osm(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        with tempfile.TemporaryDirectory() as tmpdir:
            dsm_path = os.path.join(tmpdir, "salina_dsm.tif")
            out_dir = os.path.join(tmpdir, "out")
            surf = np.full((200, 200), 370.0, dtype=np.float32)
            # Two prominent rooftop towers inside the DSM
            surf[95:100, 95:100] = 420.0
            surf[75:80, 115:120] = 410.0
            gt = (-97.63, 0.0002, 0.0, 38.86, 0.0, -0.0002)
            _write_geotiff(dsm_path, surf, gt, epsg=4326)

            cfg = LoRaGISConfig(
                title="SalinaDSMOnlyCity",
                dem_file=dsm_path,
                surface_mode="dsm",
                output_dir=out_dir,
            )
            apply_cli_args(
                cfg,
                argv=[
                    "--city",
                    "salina=38.8403,-97.6100",
                    "--radius",
                    "1km",
                    "--top",
                    "3",
                    "--viewshed-grid",
                    "21",
                ],
            )
            res = run_analysis(cfg)
            self.assertEqual(res["mode"], "city")
            self.assertEqual(res["buildings_count"], 0)
            self.assertGreaterEqual(len(res["city_result"]["top_results"]), 2)
            self.assertTrue(os.path.isfile(res["png_output_path"]))
            self.assertTrue(os.path.isfile(res["md_output_path"]))


if __name__ == "__main__":
    unittest.main()
