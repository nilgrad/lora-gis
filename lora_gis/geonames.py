"""USGS GeoNames location resolution and surrounding terrain feature queries."""

import json
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from .config import LoRaGISConfig, normalize_loc_key


def lookup_geonames_place(
    place_token: str,
    geonames_url: str,
    default_height_m: float,
    default_state: Optional[str] = None,
) -> Optional[Dict]:
    """
    Queries USGS National Map GeoNames for a Populated Place or Summit across any US state.
    Supports tokens like 'Beacon, NY', 'boulder,co', or 'neversink' (with optional default_state).
    """
    state_filter = default_state
    raw_place = place_token.strip()
    if "," in raw_place:
        parts = [p.strip() for p in raw_place.split(",", 1)]
        raw_place = parts[0]
        if len(parts[1]) == 2 and parts[1].isalpha():
            state_filter = parts[1].upper()

    clean_name = raw_place.replace("-", " ").strip()
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
    return None


def resolve_location(token: str, config: LoRaGISConfig) -> str:
    """
    Resolves a location token into a key in `config.locations`.
    Supports:
      - Known slug/name in `config.locations`
      - Inline coordinate definition: 'name=lat,lon' (e.g., 'beacon=41.504,-73.969')
      - Automatic USGS GeoNames lookup (e.g., 'Beacon, NY', 'Boulder, CO', or 'neversink')
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
    )
    if found is not None:
        config.locations[key] = found
        print(
            f"Resolved '{found['name']}' via USGS GeoNames: ({found['lat']:.6f}, {found['lon']:.6f})",
            flush=True,
        )
        return key

    known = ", ".join(sorted(config.locations.keys())) if config.locations else "(none predefined)"
    raise SystemExit(
        f"Error: Unknown location '{token}'. Known locations: {known} "
        f"(or pass 'name=lat,lon' or '\"Town, ST\"')."
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


def fetch_geonames_features(
    extent_rect,
    wkid: int,
    geonames_url: str,
) -> Tuple[List[Tuple[str, Tuple[float, float]]], List[Tuple[str, Tuple[float, float]]]]:
    """Queries USGS National Map GeoNames for mountain summits/peaks and towns in the map extent."""
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
