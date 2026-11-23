"""Unit tests for Phase 2: OpenStreetMap (Overpass) building overlay and tall-structure candidates."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from lora_gis.buildings import (
    BuildingFeature,
    build_overpass_query,
    fetch_osm_buildings,
    parse_osm_height_m,
    parse_overpass_elements,
    rasterize_buildings_onto_dem,
    select_tall_structure_candidates,
)
from lora_gis.cli import apply_cli_args, run_analysis
from lora_gis.config import FEET_TO_METERS, LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.rf import analyze_link_profile


class _MockHTTPResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


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


class TestOSMHeightParsing(unittest.TestCase):
    def test_explicit_height_formats(self) -> None:
        h_m, src = parse_osm_height_m({"height": "42"})
        self.assertAlmostEqual(h_m, 42.0)
        self.assertEqual(src, "height")

        h_m, src = parse_osm_height_m({"height": "~35.5 m"})
        self.assertAlmostEqual(h_m, 35.5)
        self.assertEqual(src, "height")

        h_m, src = parse_osm_height_m({"height": "20 m; 48 m"})
        self.assertAlmostEqual(h_m, 48.0)
        self.assertEqual(src, "height")

        h_m, src = parse_osm_height_m({"height": "120 ft"})
        self.assertAlmostEqual(h_m, 120.0 * FEET_TO_METERS, places=3)
        self.assertEqual(src, "height")

        h_m, src = parse_osm_height_m({"height": "35'6\""})
        self.assertAlmostEqual(h_m, 35.5 * FEET_TO_METERS, places=3)
        self.assertEqual(src, "height")

    def test_levels_type_defaults_and_fallback(self) -> None:
        h_m, src = parse_osm_height_m({"building:levels": "6", "roof:levels": "1"})
        self.assertAlmostEqual(h_m, 6 * 3.5 + 2.0)
        self.assertEqual(src, "levels")

        h_m, src = parse_osm_height_m({"man_made": "water_tower"})
        self.assertAlmostEqual(h_m, 35.0)
        self.assertEqual(src, "type_default")

        h_m, src = parse_osm_height_m({"man_made": "silo"})
        self.assertAlmostEqual(h_m, 25.0)
        self.assertEqual(src, "type_default")

        h_m, src = parse_osm_height_m({"building": "hospital"})
        self.assertAlmostEqual(h_m, 12.0)
        self.assertEqual(src, "type_default")

        h_m, src = parse_osm_height_m({"building": "yes"}, default_building_height_m=7.5)
        self.assertAlmostEqual(h_m, 7.5)
        self.assertEqual(src, "default")


class TestOverpassParsingAndFetch(unittest.TestCase):
    def test_parse_ways_relations_and_nodes(self) -> None:
        def fake_proj(lon: float, lat: float):
            return ((lon + 97.62) * 100000.0, (lat - 38.83) * 100000.0)

        elements = [
            {
                "type": "way",
                "id": 101,
                "tags": {
                    "building": "office",
                    "name": "United Building",
                    "height": "44 m",
                    "addr:housenumber": "119",
                    "addr:street": "S Santa Fe Ave",
                },
                "geometry": [
                    {"lat": 38.8400, "lon": -97.6100},
                    {"lat": 38.8400, "lon": -97.6095},
                    {"lat": 38.8405, "lon": -97.6095},
                    {"lat": 38.8405, "lon": -97.6100},
                    {"lat": 38.8400, "lon": -97.6100},
                ],
            },
            {
                "type": "node",
                "id": 202,
                "lat": 38.8420,
                "lon": -97.6120,
                "tags": {"man_made": "water_tower", "operator": "City of Salina"},
            },
            {
                "type": "relation",
                "id": 303,
                "tags": {"building": "yes", "building:levels": "5"},
                "members": [
                    {
                        "role": "outer",
                        "geometry": [
                            {"lat": 38.8380, "lon": -97.6140},
                            {"lat": 38.8380, "lon": -97.6135},
                            {"lat": 38.8385, "lon": -97.6135},
                            {"lat": 38.8385, "lon": -97.6140},
                        ],
                    }
                ],
            },
            # Unrelated feature should be ignored
            {"type": "node", "id": 999, "lat": 38.84, "lon": -97.61, "tags": {"amenity": "bench"}},
        ]

        feats = parse_overpass_elements(elements, proj_fn=fake_proj)
        self.assertEqual(len(feats), 3)

        by_id = {f.osm_id: f for f in feats}
        self.assertEqual(by_id["way/101"].name, "United Building")
        self.assertEqual(by_id["way/101"].address, "119 S Santa Fe Ave")
        self.assertAlmostEqual(by_id["way/101"].height_m, 44.0)

        self.assertEqual(by_id["node/202"].name, "City of Salina Water Tower")
        self.assertEqual(by_id["node/202"].structure_type, "water_tower")
        self.assertAlmostEqual(by_id["node/202"].height_m, 35.0)
        self.assertEqual(len(by_id["node/202"].polygons_utm), 1)

        self.assertAlmostEqual(by_id["relation/303"].height_m, 17.5)
        self.assertEqual(by_id["relation/303"].height_source, "levels")

    def test_fetch_osm_buildings_mirror_fallback(self) -> None:
        attempts = []

        def fake_urlopen(req, timeout=35.0):
            attempts.append(req.full_url)
            if len(attempts) == 1:
                raise OSError("primary overloaded")
            return _MockHTTPResponse(
                {
                    "elements": [
                        {
                            "type": "node",
                            "id": 1,
                            "lat": 38.84,
                            "lon": -97.61,
                            "tags": {"man_made": "silo", "name": "Co-op Grain Elevator", "height": "38 m"},
                        }
                    ]
                }
            )

        q = build_overpass_query((38.83, -97.62, 38.85, -97.60))
        self.assertIn('way["building"]', q)
        self.assertIn("water_tower", q)

        with patch("lora_gis.buildings.urllib.request.urlopen", side_effect=fake_urlopen):
            feats = fetch_osm_buildings(
                (38.83, -97.62, 38.85, -97.60),
                proj_fn=lambda lon, lat: (lon * 1000.0, lat * 1000.0),
            )

        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0].name, "Co-op Grain Elevator")
        self.assertAlmostEqual(feats[0].height_m, 38.0)


class TestRasterizationAndCandidateSelection(unittest.TestCase):
    def test_rasterize_buildings_onto_dem_and_los_blockage(self) -> None:
        # Flat 1000 m x 400 m bare-earth DEM at 300 m ASL
        ground = np.full((100, 250), 300.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="bilinear")
        dem.cache = (ground, 0.0, 0.0, 1000.0, 400.0, 250, 100)

        # Two overlapping buildings at x=500, y=200: 15 m podium + 45 m central tower
        podium = BuildingFeature(
            osm_id="way/1",
            name="Podium",
            structure_type="building",
            lat=38.84,
            lon=-97.61,
            x=500.0,
            y=200.0,
            height_m=15.0,
            height_source="height",
            polygons_utm=[[(460.0, 160.0), (540.0, 160.0), (540.0, 240.0), (460.0, 240.0)]],
        )
        tower = BuildingFeature(
            osm_id="way/2",
            name="Tower",
            structure_type="office",
            lat=38.84,
            lon=-97.61,
            x=500.0,
            y=200.0,
            height_m=45.0,
            height_source="height",
            polygons_utm=[[(485.0, 185.0), (515.0, 185.0), (515.0, 215.0), (485.0, 215.0)]],
        )

        # Pass tower BEFORE podium to verify ascending height sort guarantees taller wins
        rasterize_buildings_onto_dem(dem, [tower, podium], target_res_m=2.0)

        self.assertTrue(dem.has_separate_surface)
        # Bare-earth ground stays 300 m everywhere
        self.assertAlmostEqual(float(dem.sample_ground(np.array([500.0]), np.array([200.0]))[0]), 300.0)
        # Center of tower = 345 m, podium wing = 315 m, outside = 300 m
        surf_vals = dem.sample_surface(np.array([500.0, 470.0, 100.0]), np.array([200.0, 200.0, 200.0]))
        self.assertAlmostEqual(float(surf_vals[0]), 345.0)
        self.assertAlmostEqual(float(surf_vals[1]), 315.0)
        self.assertAlmostEqual(float(surf_vals[2]), 300.0)

        # Link from (100, 200) to (900, 200) at 10 m AGL must be blocked by the 45 m tower
        cfg = LoRaGISConfig(buildings_source="osm")
        prof = analyze_link_profile(dem, cfg, (100.0, 200.0), 10.0, (900.0, 200.0), 10.0, include_profile=True)
        self.assertFalse(prof["clear"])
        self.assertLess(prof["min_clearance_m"], -30.0)
        self.assertIn("ground_m", prof["profile"])

    def test_select_tall_structure_candidates_ranks_and_deduplicates(self) -> None:
        ground = np.full((100, 100), 300.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26914)
        dem.cache = (ground, 0.0, 0.0, 2000.0, 2000.0, 100, 100)

        buildings = [
            BuildingFeature("way/1", "Tall Tower A", "office", 38.84, -97.61, 500.0, 500.0, 45.0, "height"),
            # Very close (40 m) to Tall Tower A -> should be deduplicated
            BuildingFeature("way/2", "Tall Tower A Annex", "office", 38.84, -97.61, 540.0, 500.0, 42.0, "height"),
            BuildingFeature("node/3", "Water Tower", "water_tower", 38.85, -97.60, 1200.0, 1200.0, 35.0, "type_default"),
            # Below min_height_m=15 -> excluded
            BuildingFeature("way/4", "Small House", "house", 38.84, -97.62, 1600.0, 400.0, 6.0, "default"),
        ]

        selected = select_tall_structure_candidates(buildings, dem, count=3, min_height_m=15.0, min_separation_m=150.0)
        self.assertEqual([b.osm_id for b in selected], ["way/1", "node/3"])


class TestPhase2CLIAndEndToEnd(unittest.TestCase):
    def test_cli_and_json_building_options(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--route",
                "a=38.84,-97.62",
                "b=38.84,-97.60",
                "--buildings",
                "osm",
                "--default-building-height",
                "25ft",
                "--auto-candidates",
                "4",
                "--min-building-height",
                "60ft",
                "--overpass-url",
                "https://overpass.example/api/interpreter",
            ],
        )
        self.assertEqual(cfg.buildings_source, "osm")
        self.assertTrue(cfg.is_dsm_mode)
        self.assertAlmostEqual(cfg.default_building_height_m, 25.0 / 3.28084, places=3)
        self.assertEqual(cfg.auto_candidates, 4)
        self.assertAlmostEqual(cfg.min_building_height_m, 60.0 / 3.28084, places=3)
        self.assertEqual(cfg.overpass_url, "https://overpass.example/api/interpreter")

        with tempfile.TemporaryDirectory() as tmpdir:
            jpath = os.path.join(tmpdir, "city.json")
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "buildings": "osm",
                        "default_building_height": "8m",
                        "auto_candidates": 3,
                        "min_building_height": "20m",
                    },
                    f,
                )
            cfg_j = LoRaGISConfig()
            cfg_j.load_json_config(jpath)
            self.assertEqual(cfg_j.buildings_source, "osm")
            self.assertAlmostEqual(cfg_j.default_building_height_m, 8.0)
            self.assertEqual(cfg_j.auto_candidates, 3)
            self.assertAlmostEqual(cfg_j.min_building_height_m, 20.0)

    def test_end_to_end_osm_buildings_and_auto_candidates(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        with tempfile.TemporaryDirectory() as tmpdir:
            dem_path = os.path.join(tmpdir, "salina_ground.tif")
            out_dir = os.path.join(tmpdir, "out")
            ground = np.full((200, 300), 370.0, dtype=np.float32)
            gt = (-97.64, 0.0002, 0.0, 38.86, 0.0, -0.0002)
            _write_geotiff(dem_path, ground, gt, epsg=4326)

            mock_overpass_payload = {
                "elements": [
                    # Tall obstructing downtown block right on the direct West <-> East line
                    {
                        "type": "way",
                        "id": 1001,
                        "tags": {"building": "office", "name": "Midtown Block", "height": "45 m"},
                        "geometry": [
                            {"lat": 38.8390, "lon": -97.6110},
                            {"lat": 38.8390, "lon": -97.6090},
                            {"lat": 38.8410, "lon": -97.6090},
                            {"lat": 38.8410, "lon": -97.6110},
                            {"lat": 38.8390, "lon": -97.6110},
                        ],
                    },
                    # Tall grain elevator to the north with clear view to both West and East
                    {
                        "type": "node",
                        "id": 2002,
                        "lat": 38.8480,
                        "lon": -97.6100,
                        "tags": {
                            "man_made": "silo",
                            "name": "North Grain Elevator",
                            "height": "55 m",
                            "addr:housenumber": "400",
                            "addr:street": "N Grain Rd",
                        },
                    },
                ]
            }

            cfg = LoRaGISConfig(
                title="SalinaOSMTest",
                dem_file=dem_path,
                buildings_source="osm",
                auto_candidates=2,
                min_building_height_m=20.0,
                initial_grid_step_m=900.0,
                min_grid_step_m=900.0,
                output_dir=out_dir,
                basemap="osm",
            )
            apply_cli_args(
                cfg,
                argv=[
                    "--route",
                    "west=38.840,-97.625",
                    "east=38.840,-97.595",
                    "--hops",
                    "1",
                ],
            )

            with patch(
                "lora_gis.buildings.urllib.request.urlopen",
                return_value=_MockHTTPResponse(mock_overpass_payload),
            ):
                res = run_analysis(cfg)

            self.assertEqual(res["buildings_count"], 2)
            self.assertFalse(res["link_results"][0]["direct_clear"])
            self.assertTrue(os.path.isfile(res["md_output_path"]))
            self.assertTrue(os.path.isfile(res["png_output_path"]))

            with open(res["md_output_path"], "r", encoding="utf-8") as f:
                md_txt = f.read()
            self.assertIn("Building Overlay", md_txt)
            self.assertIn("North Grain Elevator", md_txt)
            self.assertIn("400 N Grain Rd", md_txt)


if __name__ == "__main__":
    unittest.main()
