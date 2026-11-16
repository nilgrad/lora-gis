"""Automatic UTM Zone & EPSG Coordinate Reference System detection."""

from typing import Tuple


def detect_utm_crs(lat: float, lon: float, prefer_nad83_na: bool = True) -> Tuple[str, int, str]:
    """
    Computes the metric UTM EPSG code, numeric WKID, and human-readable zone name
    from a reference (lat, lon) coordinate.

    For North America (Zones 10N..19N, lat >= 15°N), defaults to NAD83 UTM (EPSG:269xx)
    for compatibility with USGS 3DEP and state GIS servers; elsewhere uses WGS84 UTM
    (EPSG:326xx North / EPSG:327xx South).
    """
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    hemisphere = "N" if lat >= 0.0 else "S"

    if prefer_nad83_na and hemisphere == "N" and 10 <= zone <= 22 and 14.0 <= lat <= 72.0:
        wkid = 26900 + zone
    elif hemisphere == "N":
        wkid = 32600 + zone
    else:
        wkid = 32700 + zone

    epsg_str = f"EPSG:{wkid}"
    zone_label = f"UTM Zone {zone}{hemisphere}"
    return epsg_str, wkid, zone_label


def parse_crs_wkid(epsg_str: str) -> Tuple[str, int, str]:
    """Parses an explicit EPSG string like 'EPSG:26918' or '32633' into (epsg_str, wkid, label)."""
    clean = epsg_str.strip().upper()
    if clean.startswith("EPSG:"):
        wkid = int(clean.split(":", 1)[1])
    else:
        wkid = int(clean)
        clean = f"EPSG:{wkid}"

    if 26901 <= wkid <= 26960:
        label = f"UTM Zone {wkid - 26900}N"
    elif 32601 <= wkid <= 32660:
        label = f"UTM Zone {wkid - 32600}N"
    elif 32701 <= wkid <= 32760:
        label = f"UTM Zone {wkid - 32700}S"
    else:
        label = clean
    return clean, wkid, label
