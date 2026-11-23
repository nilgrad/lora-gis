"""Baseline unit tests for lora_gis.geonames (fully mocked, no network)."""

import io
import json
import unittest
from unittest.mock import patch

from lora_gis.config import LoRaGISConfig
from lora_gis.geonames import (
    fetch_geonames_features,
    lookup_geonames_place,
    parse_link_pair,
    resolve_location,
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


class TestGeoNamesLookup(unittest.TestCase):
    def test_lookup_prefers_exact_match_and_parses_state(self) -> None:
        requested_urls = []

        def fake_urlopen(url, timeout=8.0):
            requested_urls.append(url)
            return _MockHTTPResponse(
                {
                    "features": [
                        {
                            "attributes": {"gaz_name": "North Salina", "gaz_featureclass": "Populated Place"},
                            "geometry": {"x": -97.60, "y": 38.88},
                        },
                        {
                            "attributes": {"gaz_name": "Salina", "gaz_featureclass": "Populated Place"},
                            "geometry": {"points": [[-97.6114, 38.8403]]},
                        },
                    ]
                }
            )

        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=fake_urlopen):
            found = lookup_geonames_place("Salina, KS", "https://example.invalid/geonames", 10.0)

        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Salina")
        self.assertAlmostEqual(found["lat"], 38.8403)
        self.assertAlmostEqual(found["lon"], -97.6114)
        self.assertAlmostEqual(found["height_m"], 10.0)
        self.assertIn("state_alpha+%3D+%27KS%27", requested_urls[0])

    def test_lookup_returns_none_when_empty_or_error(self) -> None:
        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=OSError("offline")):
            found = lookup_geonames_place("Nowhere, KS", "https://example.invalid/geonames", 10.0)
        self.assertIsNone(found)


class TestResolveAndParseLinks(unittest.TestCase):
    def test_resolve_inline_coordinates(self) -> None:
        cfg = LoRaGISConfig(default_observer_height_m=12.0)
        key = resolve_location("valley_node=41.504,-73.969", cfg)
        self.assertEqual(key, "valley-node")
        self.assertEqual(cfg.locations[key]["name"], "Valley_Node")
        self.assertAlmostEqual(cfg.locations[key]["lat"], 41.504)
        self.assertAlmostEqual(cfg.locations[key]["lon"], -73.969)
        self.assertAlmostEqual(cfg.locations[key]["height_m"], 12.0)

    def test_resolve_predefined_catalog_entry(self) -> None:
        cfg = LoRaGISConfig(
            locations={
                "beacon": {"name": "Beacon", "lat": 41.5048, "lon": -73.9696, "height_m": 10.0}
            }
        )
        self.assertEqual(resolve_location("Beacon, NY", cfg), "beacon")

    def test_resolve_unknown_raises_system_exit(self) -> None:
        cfg = LoRaGISConfig()
        with patch("lora_gis.geonames.lookup_geonames_place", return_value=None):
            with self.assertRaises(SystemExit):
                resolve_location("NonexistentPlace", cfg)

    def test_parse_link_pair_delimiters_and_error(self) -> None:
        cfg = LoRaGISConfig(
            locations={
                "a": {"name": "A", "lat": 40.0, "lon": -74.0, "height_m": 10.0},
                "b": {"name": "B", "lat": 40.1, "lon": -74.1, "height_m": 10.0},
            }
        )
        self.assertEqual(parse_link_pair("a:b", cfg), ("a", "b"))
        self.assertEqual(parse_link_pair("a->b", cfg), ("a", "b"))
        self.assertEqual(parse_link_pair("a<->b", cfg), ("a", "b"))
        with self.assertRaises(SystemExit):
            parse_link_pair("a_without_delimiter_b", cfg)


class TestFetchGeonamesFeatures(unittest.TestCase):
    def test_fetches_deduplicates_and_filters_peaks_and_towns(self) -> None:
        def fake_urlopen(url, timeout=6.0):
            if "/5/query" in url:
                return _MockHTTPResponse(
                    {
                        "features": [
                            {
                                "attributes": {"gaz_name": "Mount Beacon", "gaz_featureclass": "Summit"},
                                "geometry": {"x": 585000.0, "y": 4595000.0},
                            },
                            {
                                "attributes": {"gaz_name": "Mount Beacon", "gaz_featureclass": "Summit"},
                                "geometry": {"x": 585001.0, "y": 4595001.0},
                            },
                            {
                                "attributes": {"gaz_name": "Some Lake", "gaz_featureclass": "Lake"},
                                "geometry": {"x": 586000.0, "y": 4596000.0},
                            },
                        ]
                    }
                )
            return _MockHTTPResponse(
                {
                    "features": [
                        {
                            "attributes": {"gaz_name": "Beacon", "gaz_featureclass": "Populated Place"},
                            "geometry": {"points": [[584000.0, 4594000.0]]},
                        }
                    ]
                }
            )

        rect = _FakeRect(580000.0, 4590000.0, 590000.0, 4600000.0)
        with patch("lora_gis.geonames.urllib.request.urlopen", side_effect=fake_urlopen):
            peaks, towns = fetch_geonames_features(rect, 26918, "https://example.invalid/geonames")

        self.assertEqual(peaks, [("Mount Beacon", (585000.0, 4595000.0))])
        self.assertEqual(towns, [("Beacon", (584000.0, 4594000.0))])


if __name__ == "__main__":
    unittest.main()
