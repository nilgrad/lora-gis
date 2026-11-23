"""Unit tests for Phase 4: optional Overture Maps and USGS 3DEP LiDAR EPT backends."""

import builtins
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from lora_gis.buildings import (
    BuildingFeature,
    fetch_overture_buildings,
    merge_building_datasets,
    parse_overture_records,
)
from lora_gis.cli import apply_cli_args
from lora_gis.config import LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.lidar import (
    bbox_wgs84_to_3857,
    build_pdal_dsm_pipeline,
    match_ept_resources_for_bbox,
    stream_3dep_lidar_dsm,
)


def _make_wkb_polygon(ring_ll) -> bytes:
    from osgeo import ogr

    ring = ogr.Geometry(ogr.wkbLinearRing)
    for lon, lat in ring_ll:
        ring.AddPoint_2D(float(lon), float(lat))
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return bytes(poly.ExportToWkb())


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


class TestOvertureBackend(unittest.TestCase):
    def test_parse_overture_records_wkb_geojson_and_heights(self) -> None:
        wkb_poly = _make_wkb_polygon([
            (-97.6105, 38.8400),
            (-97.6095, 38.8400),
            (-97.6095, 38.8408),
            (-97.6105, 38.8408),
            (-97.6105, 38.8400),
        ])
        records = [
            {
                "id": "ov-001",
                "geometry": wkb_poly,
                "height": 41.5,
                "names": {"primary": "Salina Plaza"},
                "class": "office",
            },
            {
                "id": "ov-002",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-97.6120, 38.8410],
                        [-97.6115, 38.8410],
                        [-97.6115, 38.8415],
                        [-97.6120, 38.8415],
                        [-97.6120, 38.8410],
                    ]],
                },
                "height": None,
                "num_floors": 4,
                "roof_height": 2.5,
                "subtype": "commercial",
            },
            {
                "id": "ov-003",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-97.6130, 38.8420],
                        [-97.6125, 38.8420],
                        [-97.6125, 38.8425],
                        [-97.6130, 38.8425],
                    ]],
                },
                "height": None,
                "num_floors": None,
                "subtype": "residential",
            },
        ]

        feats = parse_overture_records(
            records,
            proj_fn=lambda lon, lat: ((lon + 97.62) * 100000.0, (lat - 38.83) * 100000.0),
            default_building_height_m=6.5,
        )
        self.assertEqual(len(feats), 3)
        self.assertEqual(feats[0].name, "Salina Plaza")
        self.assertAlmostEqual(feats[0].height_m, 41.5)
        self.assertEqual(feats[0].height_source, "overture_height")
        self.assertEqual(len(feats[0].polygons_utm), 1)

        self.assertAlmostEqual(feats[1].height_m, 4 * 3.5 + 2.5)
        self.assertEqual(feats[1].height_source, "levels")

        self.assertAlmostEqual(feats[2].height_m, 6.5)
        self.assertEqual(feats[2].height_source, "default")

    def test_merge_building_datasets_enriches_names_and_keeps_osm_towers(self) -> None:
        overture = [
            BuildingFeature(
                osm_id="overture/abc12345",
                name="Building (abc12345)",
                structure_type="office",
                lat=38.8404,
                lon=-97.6100,
                x=1000.0,
                y=1000.0,
                height_m=44.0,
                height_source="overture_height",
                polygons_utm=[[(990.0, 990.0), (1010.0, 990.0), (1010.0, 1010.0), (990.0, 1010.0)]],
            )
        ]
        osm = [
            BuildingFeature(
                osm_id="way/101",
                name="United Building",
                structure_type="office",
                lat=38.8404,
                lon=-97.6100,
                x=1005.0,
                y=1003.0,
                height_m=12.0,
                height_source="type_default",
                address="119 S Santa Fe Ave",
            ),
            BuildingFeature(
                osm_id="node/202",
                name="North Water Tower",
                structure_type="water_tower",
                lat=38.8480,
                lon=-97.6050,
                x=1500.0,
                y=1800.0,
                height_m=38.0,
                height_source="height",
            ),
        ]

        merged = merge_building_datasets(overture, osm, match_radius_m=25.0)
        self.assertEqual(len(merged), 2)
        # Enriched Overture footprint keeps ML height (44m) + gains OSM name & address!
        self.assertEqual(merged[0].name, "United Building")
        self.assertEqual(merged[0].address, "119 S Santa Fe Ave")
        self.assertAlmostEqual(merged[0].height_m, 44.0)
        # Unmatched OSM water tower preserved!
        self.assertEqual(merged[1].name, "North Water Tower")
        self.assertEqual(merged[1].structure_type, "water_tower")

    def test_fetch_overture_missing_dependency_error(self) -> None:
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "overturemaps":
                raise ImportError("No module named 'overturemaps'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_overture_buildings((38.83, -97.62, 38.85, -97.60), proj_fn=lambda x, y: (x, y))
        self.assertIn("lora-gis[overture]", str(ctx.exception))


class TestUSGS3DEPLiDARBackend(unittest.TestCase):
    def test_match_ept_resources_filters_and_sorts_newest_first(self) -> None:
        index_geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "KS_Central_2015",
                        "url": "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/KS_Central_2015/ept.json",
                        "count": 500000000,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-98.0, 38.5], [-97.0, 38.5], [-97.0, 39.2], [-98.0, 39.2], [-98.0, 38.5]]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "name": "KS_Salina_QL1_2023",
                        "url": "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/KS_Salina_QL1_2023/ept.json",
                        "count": 200000000,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-97.8, 38.7], [-97.4, 38.7], [-97.4, 39.0], [-97.8, 39.0], [-97.8, 38.7]]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "name": "NY_Catskills_2022",
                        "url": "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/NY_Catskills_2022/ept.json",
                        "count": 900000000,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-75.0, 41.5], [-74.0, 41.5], [-74.0, 42.2], [-75.0, 42.2], [-75.0, 41.5]]],
                    },
                },
            ],
        }

        matches = match_ept_resources_for_bbox(index_geojson, (38.82, -97.63, 38.86, -97.59))
        self.assertEqual([m["name"] for m in matches], ["KS_Salina_QL1_2023", "KS_Central_2015"])
        self.assertEqual(matches[0]["year"], 2023)

    def test_bbox_3857_and_pdal_pipeline_structure(self) -> None:
        b3857 = bbox_wgs84_to_3857((38.83, -97.62, 38.85, -97.60))
        self.assertLess(b3857[0], b3857[2])
        self.assertLess(b3857[1], b3857[3])
        # Rough Web Mercator sanity check around -97.6 W, 38.84 N
        self.assertLess(b3857[0], -10800000.0)
        self.assertGreater(b3857[1], 4600000.0)

        pipe = build_pdal_dsm_pipeline(
            ept_urls=["https://example.invalid/a/ept.json", "https://example.invalid/b/ept.json"],
            bounds_3857=b3857,
            output_tif_path="/tmp/out_dsm.tif",
            resolution_m=1.5,
            dst_epsg=26914,
        )
        stages = pipe["pipeline"]
        types_list = [s["type"] for s in stages]
        self.assertEqual(
            types_list,
            ["readers.ept", "readers.ept", "filters.merge", "filters.range", "filters.reprojection", "writers.gdal"],
        )
        self.assertEqual(stages[-1]["output_type"], "max")
        self.assertEqual(stages[-1]["resolution"], 1.5)
        self.assertEqual(stages[-2]["out_srs"], "EPSG:26914")

    def test_stream_lidar_missing_pdal_error(self) -> None:
        dem = DEMProvider("https://example.invalid", wkid=26914)
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "pdal":
                raise ImportError("No module named 'pdal'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            with self.assertRaises(RuntimeError) as ctx:
                stream_3dep_lidar_dsm(dem, (38.83, -97.62, 38.85, -97.60), (620000, 4300000, 621000, 4301000), 26914)
        self.assertIn("lora-gis[lidar]", str(ctx.exception))

    def test_stream_lidar_with_mocked_pdal_attaches_surface(self) -> None:
        dem = DEMProvider("https://example.invalid", wkid=26914, sampling_mode="bilinear")
        dem.cache = (np.full((50, 50), 370.0), 620000.0, 4300000.0, 621000.0, 4301000.0, 50, 50)

        class _FakePipeline:
            def __init__(self, json_str: str):
                self.spec = json.loads(json_str)

            def execute(self) -> int:
                out_path = self.spec["pipeline"][-1]["filename"]
                arr = np.full((100, 100), 370.0, dtype=np.float32)
                arr[40:60, 40:60] = 415.0
                _write_geotiff(out_path, arr, (620000.0, 10.0, 0.0, 4301000.0, 0.0, -10.0), epsg=26914)
                return 250000

        fake_pdal = types.ModuleType("pdal")
        fake_pdal.Pipeline = _FakePipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(sys.modules, {"pdal": fake_pdal}):
                with patch("lora_gis.lidar.tempfile.gettempdir", return_value=tmpdir):
                    out_tif = stream_3dep_lidar_dsm(
                        dem=dem,
                        bbox_wgs84=(38.83, -97.62, 38.85, -97.60),
                        utm_bounds=(620000.0, 4300000.0, 621000.0, 4301000.0),
                        wkid=26914,
                        resolution_m=2.0,
                        ept_url="https://example.invalid/mock/ept.json",
                    )
            self.assertTrue(os.path.isfile(out_tif))
            self.assertTrue(dem.has_separate_surface)
            val = float(dem.sample_surface(np.array([620500.0]), np.array([4300500.0]))[0])
            self.assertAlmostEqual(val, 415.0, places=2)


class TestPhase4CLIAndConfig(unittest.TestCase):
    def test_cli_flags_for_overture_hybrid_and_lidar(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--city",
                "Salina, KS",
                "--buildings",
                "hybrid",
                "--dem",
                "usgs-3dep-dsm",
                "--lidar-resolution",
                "1.5",
                "--ept-url",
                "https://example.invalid/ept.json",
            ],
        )
        self.assertEqual(cfg.buildings_source, "hybrid")
        self.assertTrue(cfg.use_lidar_ept)
        self.assertTrue(cfg.is_dsm_mode)
        self.assertEqual(cfg.image_server_base, "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer")
        self.assertAlmostEqual(cfg.lidar_resolution_m, 1.5)
        self.assertEqual(cfg.ept_url, "https://example.invalid/ept.json")


if __name__ == "__main__":
    unittest.main()
