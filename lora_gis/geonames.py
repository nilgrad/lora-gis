"""USGS GeoNames and NRCan CGNDB location resolution and surrounding terrain feature queries."""

import json
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_CGNDB_URL, LoRaGISConfig, normalize_loc_key
from .nrcan import NRCAN_USER_AGENT, utm_bounds_to_wgs84_bbox

# Statistics Canada Standard Geographical Classification (SGC) province/territory codes
# required by the NRCan CGNDB GeoName API (`province=<code>`).
# Note: None of these 13 2-letter codes collide with the 50 US state postal codes.
CANADA_PROVINCE_CODES: Dict[str, str] = {
    "NL": "10",
    "PE": "11",
    "NS": "12",
    "NB": "13",
    "QC": "24",
    "ON": "35",
    "MB": "46",
    "SK": "47",
    "AB": "48",
    "BC": "59",
    "YT": "60",
    "NT": "61",
    "NU": "62",
}

CGNDB_POPULATED_RANK: Dict[str, int] = {
    "CITY": 0,
    "TOWN": 1,
    "VILG": 2,
    "HAM": 3,
    "UNP": 4,
    "MUN1": 5,
    "MUN2": 6,
    "IR": 7,
}
CGNDB_POPULATED_CONCISE = set(CGNDB_POPULATED_RANK.keys())
CGNDB_PEAK_CONCISE = {"MTN", "CLF", "ESCP", "CRAT"}


def is_canada_province(code: Optional[str]) -> bool:
    """Returns True if `code` is a 2-letter Canadian province or territory postal code."""
    if not code:
        return False
    return code.strip().upper() in CANADA_PROVINCE_CODES


def _parse_place_and_region(
    place_token: str,
    default_region: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Splits 'Place, XX' into (clean_place_name, 2-letter region code or default_region)."""
    region_filter = default_region.strip().upper() if default_region else None
    raw_place = place_token.strip()
    if "," in raw_place:
        parts = [p.strip() for p in raw_place.split(",", 1)]
        raw_place = parts[0]
        if len(parts[1]) == 2 and parts[1].isalpha():
            region_filter = parts[1].upper()
    clean_name = raw_place.replace("-", " ").strip()
    return clean_name, region_filter


def lookup_cgndb_place(
    place_token: str,
    cgndb_url: str = DEFAULT_CGNDB_URL,
    default_height_m: float = 10.0,
    default_province: Optional[str] = None,
) -> Optional[Dict]:
    """
    Queries NRCan's Canadian Geographical Names Data Base (CGNDB) API for a Canadian
    populated place or mountain/summit. Supports tokens like 'Ottawa, ON', 'Banff, AB',
    or 'Whistler' (with optional default_province).
    """
    clean_name, prov_filter = _parse_place_and_region(place_token, default_province)
    if not clean_name:
        return None

    params_dict: Dict[str, str] = {
        "q": clean_name,
        "num": "50",
    }
    if prov_filter and prov_filter in CANADA_PROVINCE_CODES:
        params_dict["province"] = CANADA_PROVINCE_CODES[prov_filter]

    url = f"{cgndb_url}?{urllib.parse.urlencode(params_dict)}"
    req = urllib.request.Request(url, headers={"User-Agent": NRCAN_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    items = data.get("items", [])
    if not items:
        return None

    candidates = []
    target_lower = clean_name.lower()
    for item in items:
        name = (item.get("name") or "").strip()
        lat = item.get("latitude")
        lon = item.get("longitude")
        if not name or lat is None or lon is None:
            continue
        concise_code = ((item.get("concise") or {}).get("code") or "").strip().upper()
        if concise_code in CGNDB_POPULATED_CONCISE:
            category_tier = 0
            type_rank = CGNDB_POPULATED_RANK[concise_code]
        elif concise_code in CGNDB_PEAK_CONCISE:
            category_tier = 1
            type_rank = 0
        else:
            continue

        exact_rank = 0 if name.lower() == target_lower else 1
        status_code = ((item.get("status") or {}).get("code") or "").strip().lower()
        official_rank = 0 if status_code == "official" else 1
        candidates.append((
            category_tier,
            exact_rank,
            official_rank,
            type_rank,
            {
                "name": name,
                "lat": float(lat),
                "lon": float(lon),
                "height_m": default_height_m,
                "country": "CA",
                "source": "NRCan CGNDB",
            },
        ))

    if not candidates:
        return None
    candidates.sort(key=lambda row: row[:4])
    return candidates[0][4]


def lookup_geonames_place(
    place_token: str,
    geonames_url: str,
    default_height_m: float,
    default_state: Optional[str] = None,
    cgndb_url: str = DEFAULT_CGNDB_URL,
    prefer_canada: bool = False,
) -> Optional[Dict]:
    """
    Queries USGS National Map GeoNames (US) or NRCan CGNDB (Canada) for a Populated Place
    or Summit. Supports tokens like 'Beacon, NY', 'Ottawa, ON', 'Banff, AB', or bare names
    with optional `default_state` (US state or Canadian province 2-letter code).
    """
    clean_name, state_filter = _parse_place_and_region(place_token, default_state)
    if not clean_name:
        return None

    # Canadian province codes do not collide with US state codes: route directly to CGNDB.
    if is_canada_province(state_filter):
        return lookup_cgndb_place(
            place_token=place_token,
            cgndb_url=cgndb_url,
            default_height_m=default_height_m,
            default_province=state_filter,
        )

    if prefer_canada and not state_filter:
        ca_found = lookup_cgndb_place(
            place_token=place_token,
            cgndb_url=cgndb_url,
            default_height_m=default_height_m,
            default_province=None,
        )
        if ca_found is not None:
            return ca_found

    safe_name = clean_name.replace("'", "''")
    for layer_id, feature_clause in [
        (3, "gaz_featureclass = 'Populated Place'"),
        (5, "gaz_featureclass IN ('Summit', 'Range', 'Ridge')"),
    ]:
        where = f"UPPER(gaz_name) LIKE UPPER('%{safe_name}%') AND {feature_clause}"
        if state_filter:
            where += f" AND state_alpha = '{state_filter.upper()}'"

        params = urllib.parse.urlencode({
            "where": where,
            "outSR": "4326",
            "outFields": "gaz_name,gaz_featureclass,state_alpha",
            "f": "json",
        })
        url = f"{geonames_url}/{layer_id}/query?{params}"
        try:
            with urllib.request.urlopen(url, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                features = data.get("features", [])
                # Prefer exact case-insensitive match first
                features.sort(
                    key=lambda ft: 0
                    if (ft.get("attributes", {}).get("gaz_name") or "").strip().lower() == clean_name.lower()
                    else 1
                )
                for feat in features:
                    attrs = feat.get("attributes", {})
                    geom = feat.get("geometry", {})
                    pts = geom.get("points") or ([[geom["x"], geom["y"]]] if "x" in geom else [])
                    if pts:
                        lon, lat = float(pts[0][0]), float(pts[0][1])
                        return {
                            "name": attrs.get("gaz_name") or clean_name.title(),
                            "lat": lat,
                            "lon": lon,
                            "height_m": default_height_m,
                        }
        except Exception:
            pass

    if not state_filter and not prefer_canada and cgndb_url:
        return lookup_cgndb_place(
            place_token=place_token,
            cgndb_url=cgndb_url,
            default_height_m=default_height_m,
            default_province=None,
        )

    return None


def resolve_location(token: str, config: LoRaGISConfig) -> str:
    """
    Resolves a location token into a key in `config.locations`.
    Supports:
      - Known slug/name in `config.locations`
      - Inline coordinate definition: 'name=lat,lon' (e.g., 'beacon=41.504,-73.969')
      - Automatic USGS GeoNames (US) or NRCan CGNDB (Canada) lookup
        (e.g., 'Beacon, NY', 'Ottawa, ON', 'Banff, AB')
    """
    if "=" in token and "," in token.split("=", 1)[1]:
        raw_label, coords_str = token.split("=", 1)
        lat_s, lon_s = coords_str.split(",", 1)
        key = normalize_loc_key(raw_label)
        config.locations[key] = {
            "name": raw_label.replace("-", " ").strip().title(),
            "lat": float(lat_s.strip()),
            "lon": float(lon_s.strip()),
            "height_m": config.default_observer_height_m,
        }
        return key

    key = normalize_loc_key(token)
    if key in config.locations:
        return key

    found = lookup_geonames_place(
        token,
        geonames_url=config.geonames_url,
        default_height_m=config.default_observer_height_m,
        default_state=config.default_state,
        cgndb_url=config.cgndb_url,
        prefer_canada=config.is_canada_dem,
    )
    if found is not None:
        config.locations[key] = found
        source_lbl = found.get("source") or "USGS GeoNames"
        print(
            f"Resolved '{found['name']}' via {source_lbl}: ({found['lat']:.6f}, {found['lon']:.6f})",
            flush=True,
        )
        return key

    known = ", ".join(sorted(config.locations.keys())) if config.locations else "(none predefined)"
    raise SystemExit(
        f"Error: Unknown location '{token}'. Known locations: {known} "
        f"(or pass 'name=lat,lon' or '\"Town, ST\"' / '\"City, PR\"')."
    )


def parse_link_pair(pair_token: str, config: LoRaGISConfig) -> Tuple[str, str]:
    """Parses a link token like 'node1:node2' or 'node1->node2' into (key1, key2)."""
    for sep in ("<->", "->", ":"):
        if sep in pair_token:
            left, right = pair_token.split(sep, 1)
            return (resolve_location(left, config), resolve_location(right, config))
    raise SystemExit(
        f"Error: Invalid link format '{pair_token}'. Expected 'node1:node2' (e.g., 'site_a:site_b')."
    )


def fetch_cgndb_features(
    extent_rect,
    wkid: int,
    cgndb_url: str = DEFAULT_CGNDB_URL,
) -> Tuple[List[Tuple[str, Tuple[float, float]]], List[Tuple[str, Tuple[float, float]]]]:
    """Queries NRCan CGNDB GeoNames for mountain summits/peaks and populated places in the map extent."""
    from osgeo import osr

    osr.UseExceptions()
    utm_bounds = (
        float(extent_rect.xMinimum()),
        float(extent_rect.yMinimum()),
        float(extent_rect.xMaximum()),
        float(extent_rect.yMaximum()),
    )
    west, south, east, north = utm_bounds_to_wgs84_bbox(utm_bounds, wkid)
    bbox_str = f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"

    src = osr.SpatialReference()
    src.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(int(wkid))
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_utm = osr.CoordinateTransformation(src, dst)

    peaks: List[Tuple[str, Tuple[float, float]]] = []
    towns: List[Tuple[str, Tuple[float, float]]] = []
    seen_peaks = set()
    seen_towns = set()

    queries = [
        {"bbox": bbox_str, "concise": "MTN", "num": "50"},
        {"bbox": bbox_str, "num": "150"},
    ]
    for qparams in queries:
        url = f"{cgndb_url}?{urllib.parse.urlencode(qparams)}"
        req = urllib.request.Request(url, headers={"User-Agent": NRCAN_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue

        for item in data.get("items", []):
            name = (item.get("name") or "").strip()
            lat = item.get("latitude")
            lon = item.get("longitude")
            if not name or lat is None or lon is None:
                continue
            concise_code = ((item.get("concise") or {}).get("code") or "").strip().upper()
            if concise_code in CGNDB_PEAK_CONCISE:
                if name in seen_peaks:
                    continue
                x, y, _ = to_utm.TransformPoint(float(lon), float(lat))
                if not (utm_bounds[0] <= x <= utm_bounds[2] and utm_bounds[1] <= y <= utm_bounds[3]):
                    continue
                seen_peaks.add(name)
                peaks.append((name, (float(x), float(y))))
            elif concise_code in CGNDB_POPULATED_CONCISE:
                if name in seen_towns:
                    continue
                x, y, _ = to_utm.TransformPoint(float(lon), float(lat))
                if not (utm_bounds[0] <= x <= utm_bounds[2] and utm_bounds[1] <= y <= utm_bounds[3]):
                    continue
                seen_towns.add(name)
                towns.append((name, (float(x), float(y))))

    return peaks, towns


def fetch_geonames_features(
    extent_rect,
    wkid: int,
    geonames_url: str,
    use_canada: bool = False,
    cgndb_url: str = DEFAULT_CGNDB_URL,
) -> Tuple[List[Tuple[str, Tuple[float, float]]], List[Tuple[str, Tuple[float, float]]]]:
    """
    Queries USGS National Map GeoNames (or NRCan CGNDB when `use_canada=True`) for
    mountain summits/peaks and towns in the map extent.
    """
    if use_canada:
        return fetch_cgndb_features(extent_rect, wkid, cgndb_url=cgndb_url)

    bbox = f"{extent_rect.xMinimum()},{extent_rect.yMinimum()},{extent_rect.xMaximum()},{extent_rect.yMaximum()}"
    peaks: List[Tuple[str, Tuple[float, float]]] = []
    towns: List[Tuple[str, Tuple[float, float]]] = []

    for layer_id, target_list, allowed_classes in [
        (5, peaks, {"Summit", "Range", "Ridge", "Cliff", "Pillar"}),
        (3, towns, {"Populated Place"}),
    ]:
        params = urllib.parse.urlencode({
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "inSR": str(wkid),
            "outSR": str(wkid),
            "outFields": "gaz_name,gaz_featureclass",
            "f": "json",
        })
        url = f"{geonames_url}/{layer_id}/query?{params}"
        try:
            with urllib.request.urlopen(url, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                seen = set()
                for feat in data.get("features", []):
                    attrs = feat.get("attributes", {})
                    name = attrs.get("gaz_name")
                    fclass = attrs.get("gaz_featureclass")
                    if not name or name in seen or (allowed_classes and fclass not in allowed_classes):
                        continue
                    geom = feat.get("geometry", {})
                    pts = geom.get("points") or ([[geom["x"], geom["y"]]] if "x" in geom else [])
                    if pts:
                        seen.add(name)
                        target_list.append((name, (float(pts[0][0]), float(pts[0][1]))))
        except Exception:
            pass

    return peaks, towns
