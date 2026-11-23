"""Baseline unit tests for lora_gis.rf propagation math and 1-hop/2-hop solver."""

import math
import unittest

import numpy as np

from lora_gis.config import LoRaGISConfig
from lora_gis.dem import DEMProvider
from lora_gis.rf import (
    analyze_link,
    analyze_link_profile,
    calc_fspl_db,
    compute_link_padding,
    evaluate_segments_vectorized,
    rank_solution_key,
)


class _FakePoint:
    def __init__(self, x: float, y: float):
        self._x = x
        self._y = y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class _FakeInvTransform:
    """Maps synthetic UTM meters linearly to dummy lat/lon degrees for unit tests."""

    def transform(self, pt) -> _FakePoint:
        return _FakePoint(-74.0 + pt.x() / 100000.0, 41.0 + pt.y() / 100000.0)


class TestRFMath(unittest.TestCase):
    def test_calc_fspl_db(self) -> None:
        self.assertEqual(calc_fspl_db(0.0, 915.0), 0.0)
        fspl_1km = calc_fspl_db(1000.0, 915.0)
        expected_1km = 20.0 * math.log10(1.0) + 20.0 * math.log10(915.0) + 32.44
        self.assertAlmostEqual(fspl_1km, expected_1km, places=5)
        # Doubling distance increases FSPL by ~6.0206 dB
        fspl_2km = calc_fspl_db(2000.0, 915.0)
        self.assertAlmostEqual(fspl_2km - fspl_1km, 20.0 * math.log10(2.0), places=5)

    def test_analyze_link_profile_flat_terrain_earth_bulge_and_fresnel(self) -> None:
        # Flat 10 km terrain at 300 m ASL; antennas at 20 m AGL
        arr = np.full((20, 200), 300.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 12000.0, 1000.0, 200, 20)
        cfg = LoRaGISConfig(freq_mhz=915.0)

        res = analyze_link_profile(
            dem, cfg, (1000.0, 500.0), 20.0, (11000.0, 500.0), 20.0, include_profile=True
        )
        dist_m = 10000.0
        mid_bulge = (5000.0 * 5000.0) / (2.0 * cfg.earth_radius_eff_m)
        expected_min_clear = 20.0 - mid_bulge
        expected_f1_mid = math.sqrt(cfg.wavelength_m * 5000.0 * 5000.0 / dist_m)

        self.assertTrue(res["clear"])
        self.assertAlmostEqual(res["dist_m"], dist_m, places=3)
        self.assertAlmostEqual(res["min_clearance_m"], expected_min_clear, places=2)
        self.assertAlmostEqual(res["min_fresnel_ratio"], expected_min_clear / expected_f1_mid, places=2)
        self.assertIn("profile", res)
        self.assertAlmostEqual(res["profile"]["worst_dist_km"], 5.0, places=1)

    def test_analyze_link_profile_blocked_by_ridge(self) -> None:
        arr = np.full((20, 200), 300.0, dtype=np.float64)
        # Put a 400 m ridge in the middle (x around 5000 m)
        arr[:, 95:105] = 400.0
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 10000.0, 1000.0, 200, 20)
        cfg = LoRaGISConfig(freq_mhz=915.0)

        res = analyze_link_profile(
            dem, cfg, (500.0, 500.0), 10.0, (9500.0, 500.0), 10.0, include_profile=True
        )
        self.assertFalse(res["clear"])
        self.assertLess(res["min_clearance_m"], -85.0)
        self.assertLess(res["min_fresnel_ratio"], 0.0)
        self.assertAlmostEqual(res["profile"]["worst_dist_km"], 4.5, delta=0.5)

    def test_analyze_link_profile_invalid_dem_values(self) -> None:
        arr = np.full((10, 10), -9999.0, dtype=np.float64)
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 1000.0, 1000.0, 10, 10)
        cfg = LoRaGISConfig()

        res = analyze_link_profile(dem, cfg, (100.0, 500.0), 10.0, (900.0, 500.0), 10.0)
        self.assertFalse(res["clear"])
        self.assertEqual(res["min_clearance_m"], -9999.0)

    def test_evaluate_segments_vectorized_matches_single_profile(self) -> None:
        arr = np.full((100, 100), 300.0, dtype=np.float64)
        # Ridge blocking y in [0, 500] around x = 500 m, open valley for y in [600, 1000]
        arr[50:, 45:55] = 380.0
        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 1000.0, 1000.0, 100, 100)
        cfg = LoRaGISConfig(los_num_samples=80)

        p1_arr = np.array([[100.0, 200.0], [100.0, 800.0]], dtype=np.float64)
        p2_arr = np.array([[900.0, 200.0], [900.0, 800.0]], dtype=np.float64)
        ok, clr, f1 = evaluate_segments_vectorized(dem, cfg, p1_arr, 10.0, p2_arr, 10.0)

        self.assertFalse(bool(ok[0]))
        self.assertTrue(bool(ok[1]))

        single_blocked = analyze_link_profile(dem, cfg, (100.0, 200.0), 10.0, (900.0, 200.0), 10.0, multi_link_mode=True)
        single_clear = analyze_link_profile(dem, cfg, (100.0, 800.0), 10.0, (900.0, 800.0), 10.0, multi_link_mode=True)
        self.assertAlmostEqual(float(clr[0]), single_blocked["min_clearance_m"], places=4)
        self.assertAlmostEqual(float(clr[1]), single_clear["min_clearance_m"], places=4)
        self.assertAlmostEqual(float(f1[1]), single_clear["min_fresnel_ratio"], places=4)

        # Empty array handling
        ok_e, clr_e, f1_e = evaluate_segments_vectorized(
            dem, cfg, np.empty((0, 2)), 10.0, np.empty((0, 2)), 10.0
        )
        self.assertEqual(len(ok_e), 0)
        self.assertEqual(len(clr_e), 0)
        self.assertEqual(len(f1_e), 0)

    def test_compute_link_padding_and_rank_solution_key(self) -> None:
        cfg = LoRaGISConfig(grid_padding_m=1000.0, narrow_axis_padding_m=2500.0, min_fresnel_clearance=0.60)
        # Wide E-W link -> standard padding
        self.assertEqual(compute_link_padding({"x": 0.0, "y": 0.0}, {"x": 5000.0, "y": 0.0}, cfg), 1000.0)
        # Narrow N-S link -> expanded padding
        self.assertEqual(compute_link_padding({"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 5000.0}, cfg), 2500.0)

        sol_fresnel_long = {"total_dist": 9000.0, "min_fresnel": 0.80}
        sol_fresnel_short = {"total_dist": 7000.0, "min_fresnel": 0.65}
        sol_marginal_short = {"total_dist": 6000.0, "min_fresnel": 0.30}
        ranked = sorted(
            [sol_fresnel_long, sol_marginal_short, sol_fresnel_short],
            key=lambda s: rank_solution_key(s, cfg, multi_link_mode=False),
        )
        self.assertEqual(ranked, [sol_fresnel_short, sol_fresnel_long, sol_marginal_short])


class TestAnalyzeLinkSolver(unittest.TestCase):
    def test_analyze_link_finds_1hop_grid_and_explicit_candidate(self) -> None:
        # 4 km x 4 km DEM at 40 m/px (100x100 px), base elevation 300 m.
        # Endpoint A at (1000, 1500), Endpoint B at (3000, 1500).
        # Put a tall 450 m mountain ridge blocking direct sightline at x = 2000, y in [0, 2200].
        # Put a tall 500 m hilltop to the north at (2000, 2800) with clear sightlines to both A and B.
        arr = np.full((100, 100), 300.0, dtype=np.float64)
        # Row 0 is y=4000, Row 99 is y=0 (40 m/px)
        # Direct blocking wall: x in [1880, 2120] -> cols 47..53; y in [0, 2200] -> rows 45..100
        arr[45:100, 47:53] = 450.0
        # Smooth conical hill peaking at (2000, 2800) so the summit does not self-shadow
        yy, xx = np.mgrid[0:100, 0:100]
        dist_peak = np.hypot((xx - 50.0) * 40.0, (yy - 30.0) * 40.0)
        hill = 300.0 + 200.0 * np.exp(-0.5 * (dist_peak / 280.0) ** 2)
        arr = np.maximum(arr, hill)

        dem = DEMProvider("https://example.invalid", wkid=26918)
        dem.cache = (arr, 0.0, 0.0, 4000.0, 4000.0, 100, 100)

        cfg = LoRaGISConfig(
            initial_grid_step_m=400.0,
            min_grid_step_m=400.0,
            grid_padding_m=600.0,
            narrow_axis_padding_m=600.0,
            relay_height_m=18.3,
            locations={
                "town-a": {"name": "Town A", "lat": 41.015, "lon": -73.99, "x": 1000.0, "y": 1500.0, "xy": (1000.0, 1500.0), "height_m": 10.0},
                "town-b": {"name": "Town B", "lat": 41.015, "lon": -73.97, "x": 3000.0, "y": 1500.0, "xy": (3000.0, 1500.0), "height_m": 10.0},
                "north-peak": {"name": "North Peak", "lat": 41.028, "lon": -73.98, "x": 2000.0, "y": 2800.0, "xy": (2000.0, 2800.0), "height_m": 10.0},
                "valley-hole": {"name": "Valley Hole", "lat": 41.005, "lon": -73.98, "x": 2000.0, "y": 500.0, "xy": (2000.0, 500.0), "height_m": 10.0},
            },
        )

        res = analyze_link(
            u_key="town-a",
            v_key="town-b",
            config=cfg,
            dem=dem,
            inv_transform=_FakeInvTransform(),
            hub_repeater_keys={"town-a"},
            multi_link_mode=True,
            allow_2hop=True,
            headless_cli=True,
            candidate_keys=["north-peak", "valley-hole"],
        )

        self.assertFalse(res["direct_clear"])
        self.assertIsNotNone(res["best_1hop"])
        self.assertEqual(len(res["explicit_candidates"]), 2)

        by_key = {ec["key"]: ec for ec in res["explicit_candidates"]}
        self.assertTrue(by_key["north-peak"]["viable"])
        self.assertFalse(by_key["valley-hole"]["viable"])
        self.assertEqual(len(res["sensitivity_tables"]), 1)
        self.assertEqual(len(res["explicit_sensitivity"]), 1)


if __name__ == "__main__":
    unittest.main()
