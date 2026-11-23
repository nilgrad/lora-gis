"""Baseline unit tests for CLI argument parsing, Markdown reporting, and profile charts."""

import json
import os
import tempfile
import unittest

import numpy as np

from lora_gis.cartography import render_candidate_profiles
from lora_gis.cli import apply_cli_args
from lora_gis.config import LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.report import export_markdown_report
from lora_gis.rf import analyze_link


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
        return _FakePoint(-74.0 + pt.x() / 100000.0, 41.0 + pt.y() / 100000.0)


class TestCLIArgParsing(unittest.TestCase):
    def test_route_candidates_and_height_precedence(self) -> None:
        cfg = LoRaGISConfig()
        apply_cli_args(
            cfg,
            argv=[
                "--route",
                "alpha=41.50,-73.97",
                "beta=41.60,-73.90",
                "gamma=41.70,-73.85",
                "--candidates",
                "ridge1=41.55,-73.93",
                "ridge2=41.65,-73.88",
                "--candidate-height",
                "30ft",
                "--height",
                "alpha=45ft",
                "ridge1=50ft",
                "--freq-mhz",
                "868.0",
                "--hops",
                "2",
                "--grid-step",
                "400",
                "--min-grid-step",
                "200",
            ],
        )
        self.assertEqual(cfg.active_links, [("alpha", "beta"), ("beta", "gamma")])
        self.assertEqual(cfg.active_candidate_keys, ["ridge1", "ridge2"])
        self.assertAlmostEqual(cfg.locations["alpha"]["height_m"], 45.0 / 3.28084, places=4)
        # Explicit --height overrides --candidate-height
        self.assertAlmostEqual(cfg.locations["ridge1"]["height_m"], 50.0 / 3.28084, places=4)
        self.assertAlmostEqual(cfg.locations["ridge2"]["height_m"], 30.0 / 3.28084, places=4)
        self.assertAlmostEqual(cfg.freq_mhz, 868.0)
        self.assertEqual(cfg.hops_override, 2)
        self.assertAlmostEqual(cfg.initial_grid_step_m, 400.0)
        self.assertAlmostEqual(cfg.min_grid_step_m, 200.0)

    def test_links_deduplication_and_cli_overrides_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "net.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "title": "FromJSON",
                        "freq_mhz": 915.0,
                        "locations": {
                            "n1": {"lat": 41.5, "lon": -73.9},
                            "n2": {"lat": 41.6, "lon": -73.8},
                        },
                    },
                    f,
                )
            cfg = LoRaGISConfig()
            apply_cli_args(
                cfg,
                argv=[
                    "--config",
                    cfg_path,
                    "--title",
                    "FromCLI",
                    "--links",
                    "n1:n2",
                    "n2:n1",
                ],
            )
            self.assertEqual(cfg.title, "FromCLI")
            self.assertEqual(cfg.active_links, [("n1", "n2")])

    def test_invalid_route_and_height_raise_system_exit(self) -> None:
        with self.assertRaises(SystemExit):
            apply_cli_args(LoRaGISConfig(), argv=["--route", "onlyone=41.5,-73.9"])
        with self.assertRaises(SystemExit):
            apply_cli_args(LoRaGISConfig(), argv=["--height", "missing_equals_sign"])


class TestReportAndProfileExport(unittest.TestCase):
    def test_export_markdown_report_and_candidate_profiles(self) -> None:
        arr = np.full((100, 100), 300.0, dtype=np.float64)
        arr[45:100, 47:53] = 450.0
        yy, xx = np.mgrid[0:100, 0:100]
        dist_peak = np.hypot((xx - 50.0) * 40.0, (yy - 30.0) * 40.0)
        arr = np.maximum(arr, 300.0 + 200.0 * np.exp(-0.5 * (dist_peak / 280.0) ** 2))

        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 4000.0, 4000.0, 100, 100)

        cfg = LoRaGISConfig(
            title="BaselineTest",
            initial_grid_step_m=500.0,
            min_grid_step_m=500.0,
            grid_padding_m=600.0,
            narrow_axis_padding_m=600.0,
            locations={
                "town-a": {"name": "Town A", "lat": 41.015, "lon": -73.99, "x": 1000.0, "y": 1500.0, "xy": (1000.0, 1500.0), "height_m": 10.0},
                "town-b": {"name": "Town B", "lat": 41.015, "lon": -73.97, "x": 3000.0, "y": 1500.0, "xy": (3000.0, 1500.0), "height_m": 10.0},
                "north-peak": {"name": "North Peak", "lat": 41.028, "lon": -73.98, "x": 2000.0, "y": 2800.0, "xy": (2000.0, 2800.0), "height_m": 10.0},
            },
        )

        inv_tr = _FakeInvTransform()
        res = analyze_link(
            u_key="town-a",
            v_key="town-b",
            config=cfg,
            dem=dem,
            inv_transform=inv_tr,
            hub_repeater_keys=set(),
            multi_link_mode=False,
            allow_2hop=True,
            headless_cli=True,
            candidate_keys=["north-peak"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            prof_png = os.path.join(tmpdir, "candidate_profiles.png")
            written_prof = render_candidate_profiles(cfg, [res], prof_png)
            self.assertEqual(written_prof, prof_png)
            self.assertTrue(os.path.isfile(prof_png))
            self.assertGreater(os.path.getsize(prof_png), 1000)

            md_path = os.path.join(tmpdir, "report.md")
            export_markdown_report(
                config=cfg,
                dem=dem,
                active_location_keys=["town-a", "town-b"],
                link_results=[res],
                hub_repeater_keys=set(),
                multi_link_mode=False,
                enable_2hop=True,
                zone_label="UTM Zone 18N",
                inv_transform=inv_tr,
                peaks_list=[("North Peak Summit", (2000.0, 2800.0))],
                towns_list=[("Town A", (1000.0, 1500.0))],
                peak_elevs=[500.0],
                timestamp_str="2026-11-23_15-00-00",
                png_filename="map.png",
                md_output_path=md_path,
                candidate_keys=["north-peak"],
                profiles_filename="candidate_profiles.png",
            )

            self.assertTrue(os.path.isfile(md_path))
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            self.assertIn("# BaselineTest 915 MHz LoRa (MeshCore) Relay Report", md_content)
            self.assertIn("![Candidate Terrain & Line-of-Sight Profiles](candidate_profiles.png)", md_content)
            self.assertIn("North Peak", md_content)
            self.assertIn("Optimal 1-Hop Single-Repeater Solution", md_content)
            self.assertIn("Grid Resolution Scan Summary", md_content)
            self.assertIn("North Peak Summit", md_content)

        # No candidates -> render_candidate_profiles returns None
        self.assertIsNone(render_candidate_profiles(cfg, [], os.path.join(tempfile.gettempdir(), "unused.png")))


if __name__ == "__main__":
    unittest.main()
