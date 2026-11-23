"""Baseline unit tests for lora_gis.utm."""

import unittest

from lora_gis.utm import detect_utm_crs, parse_crs_wkid


class TestUTMDetection(unittest.TestCase):
    def test_north_america_defaults_to_nad83(self) -> None:
        # New York -> UTM Zone 18N (EPSG:26918)
        epsg, wkid, label = detect_utm_crs(41.5048, -73.9696)
        self.assertEqual(epsg, "EPSG:26918")
        self.assertEqual(wkid, 26918)
        self.assertEqual(label, "UTM Zone 18N")

        # Kansas -> UTM Zone 14N (EPSG:26914)
        epsg, wkid, label = detect_utm_crs(38.8403, -97.6114)
        self.assertEqual(epsg, "EPSG:26914")
        self.assertEqual(wkid, 26914)
        self.assertEqual(label, "UTM Zone 14N")

    def test_north_america_wgs84_override(self) -> None:
        epsg, wkid, label = detect_utm_crs(41.5048, -73.9696, prefer_nad83_na=False)
        self.assertEqual(epsg, "EPSG:32618")
        self.assertEqual(wkid, 32618)
        self.assertEqual(label, "UTM Zone 18N")

    def test_europe_and_southern_hemisphere_use_wgs84(self) -> None:
        # Zurich, Switzerland -> UTM Zone 32N
        epsg, wkid, label = detect_utm_crs(47.3769, 8.5417)
        self.assertEqual((epsg, wkid, label), ("EPSG:32632", 32632, "UTM Zone 32N"))

        # Sydney, Australia -> UTM Zone 56S
        epsg, wkid, label = detect_utm_crs(-33.8688, 151.2093)
        self.assertEqual((epsg, wkid, label), ("EPSG:32756", 32756, "UTM Zone 56S"))

    def test_antimeridian_zone_clamping(self) -> None:
        _, wkid_west, _ = detect_utm_crs(0.0, -180.0)
        _, wkid_east, _ = detect_utm_crs(0.0, 180.0)
        self.assertEqual(wkid_west, 32601)
        self.assertEqual(wkid_east, 32660)


class TestParseCRSWkid(unittest.TestCase):
    def test_parse_with_and_without_prefix(self) -> None:
        self.assertEqual(parse_crs_wkid("EPSG:26918"), ("EPSG:26918", 26918, "UTM Zone 18N"))
        self.assertEqual(parse_crs_wkid("26914"), ("EPSG:26914", 26914, "UTM Zone 14N"))
        self.assertEqual(parse_crs_wkid(" epsg:32633 "), ("EPSG:32633", 32633, "UTM Zone 33N"))
        self.assertEqual(parse_crs_wkid("32756"), ("EPSG:32756", 32756, "UTM Zone 56S"))

    def test_parse_non_utm_epsg(self) -> None:
        self.assertEqual(parse_crs_wkid("EPSG:3857"), ("EPSG:3857", 3857, "EPSG:3857"))


if __name__ == "__main__":
    unittest.main()
