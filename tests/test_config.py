"""Baseline unit tests for lora_gis.config."""

import json
import os
import tempfile
import unittest

from lora_gis.config import (
    DEM_PRESETS,
    LoRaGISConfig,
    normalize_loc_key,
    parse_height_value_m,
)


class TestConfigHelpers(unittest.TestCase):
    def test_normalize_loc_key(self) -> None:
        self.assertEqual(normalize_loc_key("Beacon, NY"), "beacon")
        self.assertEqual(normalize_loc_key("Livingston_Manor, NY"), "livingston-manor")
        self.assertEqual(normalize_loc_key("  New   Paltz "), "new-paltz")

    def test_parse_height_value_m(self) -> None:
        self.assertAlmostEqual(parse_height_value_m(15), 15.0)
        self.assertAlmostEqual(parse_height_value_m(9.14), 9.14)
        self.assertAlmostEqual(parse_height_value_m("10m"), 10.0)
        self.assertAlmostEqual(parse_height_value_m("12.5 meters"), 12.5)
        self.assertAlmostEqual(parse_height_value_m("30ft"), 30.0 / 3.28084, places=5)
        self.assertAlmostEqual(parse_height_value_m("60 feet"), 60.0 / 3.28084, places=5)
        self.assertAlmostEqual(parse_height_value_m("45'"), 45.0 / 3.28084, places=5)
        self.assertAlmostEqual(parse_height_value_m("18.3"), 18.3)


class TestLoRaGISConfig(unittest.TestCase):
    def test_defaults_and_properties(self) -> None:
        cfg = LoRaGISConfig()
        self.assertAlmostEqual(cfg.wavelength_m, 299.792458 / 915.0, places=6)
        self.assertEqual(cfg.image_server_base, DEM_PRESETS["usgs-3dep"])

        cfg_eu = LoRaGISConfig(freq_mhz=868.0, dem_source="ny-gis")
        self.assertAlmostEqual(cfg_eu.wavelength_m, 299.792458 / 868.0, places=6)
        self.assertEqual(cfg_eu.image_server_base, DEM_PRESETS["ny-gis"])

        custom_url = "https://example.org/arcgis/rest/services/Custom/ImageServer"
        cfg_custom = LoRaGISConfig(dem_source=custom_url)
        self.assertEqual(cfg_custom.image_server_base, custom_url)

    def test_load_json_config(self) -> None:
        payload = {
            "title": "KansasMesh",
            "default_state": "KS",
            "freq_mhz": 906.875,
            "min_fresnel_clearance": 0.70,
            "relay_height": "50ft",
            "candidate_height": "35ft",
            "observer_height": "12m",
            "repeater_height": "40ft",
            "dem_source": "usgs-3dep",
            "dem_file": "/tmp/sample.tif",
            "crs_epsg": "EPSG:26914",
            "output_dir": "custom_out",
            "locations": {
                "Site_A": {"name": "Site A", "lat": 38.84, "lon": -97.61, "height": "30ft"},
                "site-b": {"lat": 38.88, "lon": -97.55, "height_m": 15.0},
                "site-c": {"lat": 38.86, "lon": -97.58},
            },
            "route": ["site-a", "site-b"],
            "links": [["site-a", "site-c"], ["site-c", "site-b"]],
            "candidate_relays": ["site-c"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "network.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            cfg = LoRaGISConfig()
            cfg.load_json_config(cfg_path)

        self.assertEqual(cfg.title, "KansasMesh")
        self.assertEqual(cfg.default_state, "KS")
        self.assertAlmostEqual(cfg.freq_mhz, 906.875)
        self.assertAlmostEqual(cfg.min_fresnel_clearance, 0.70)
        self.assertAlmostEqual(cfg.relay_height_m, 50.0 / 3.28084, places=4)
        self.assertAlmostEqual(cfg.candidate_height_m, 35.0 / 3.28084, places=4)
        self.assertAlmostEqual(cfg.default_observer_height_m, 12.0)
        self.assertAlmostEqual(cfg.default_repeater_height_m, 40.0 / 3.28084, places=4)
        self.assertEqual(cfg.dem_file, "/tmp/sample.tif")
        self.assertEqual(cfg.crs_epsg, "EPSG:26914")
        self.assertEqual(cfg.output_dir, "custom_out")

        self.assertIn("site-a", cfg.locations)
        self.assertEqual(cfg.locations["site-a"]["name"], "Site A")
        self.assertAlmostEqual(cfg.locations["site-a"]["height_m"], 30.0 / 3.28084, places=4)
        self.assertEqual(cfg.locations["site-b"]["name"], "Site B")
        self.assertAlmostEqual(cfg.locations["site-b"]["height_m"], 15.0)
        # Missing height falls back to default_observer_height_m loaded from JSON
        self.assertAlmostEqual(cfg.locations["site-c"]["height_m"], 12.0)
        self.assertEqual(cfg.default_route, ["site-a", "site-b"])
        self.assertEqual(cfg.default_links, [("site-a", "site-c"), ("site-c", "site-b")])
        self.assertEqual(cfg.candidate_relays, ["site-c"])


if __name__ == "__main__":
    unittest.main()
