"""OpenStreetMap (Overpass API) building & tall-structure fetching and DSM rasterization."""

from dataclasses import dataclass, field
import json
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

from .config import FEET_TO_METERS
from .dem import DEMProvider

DEFAULT_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

TALL_MAN_MADE_TYPES = (
    "water_tower",
    "silo",
    "tower",
    "mast",
    "communications_tower",
)

MAN_MADE_DEFAULT_HEIGHTS_M = {
    "communications_tower": 45.0,
    "water_tower": 35.0,
    "chimney": 30.0,
    "tower": 30.0,
    "silo": 25.0,
    "mast": 25.0,
}

BUILDING_SUBTYPE_DEFAULT_HEIGHTS_M = {
    "cathedral": 20.0,
    "church": 14.0,
    "hospital": 12.0,
    "hotel": 12.0,
    "office": 12.0,
    "apartments": 12.0,
    "university": 12.0,
    "industrial": 8.0,
    "warehouse": 8.0,
    "commercial": 8.0,
    "retail": 7.0,
}


@dataclass
class BuildingFeature:
    """Normalized building or tall structure extracted from OpenStreetMap."""

    osm_id: str
    name: str
    structure_type: str
    lat: float
    lon: float
    x: float
    y: float
    height_m: float
    height_source: str
    polygons_utm: List[List[Tuple[float, float]]] = field(default_factory=list)
    address: Optional[str] = None


def _parse_single_height_token_m(token: str) -> Optional[float]:
    """Parses a single OSM height value (meters, feet, or feet'inches\") into meters."""
    s = token.strip().lower()
    if not s:
        return None
    s = s.lstrip("~≈ca. ").strip()

    # Feet and inches format, e.g. 35'6" or 35' 6" or 35'
    ft_in_match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*'(?:\s*([0-9]+(?:\.[0-9]+)?)\s*\"?)?$", s)
    if ft_in_match:
        feet = float(ft_in_match.group(1))
        inches = float(ft_in_match.group(2)) if ft_in_match.group(2) else 0.0
        val_m = (feet + inches / 12.0) * FEET_TO_METERS
        return val_m if 0.5 <= val_m <= 1000.0 else None

    # Feet with unit suffix, e.g. 120 ft / 120ft / 120 feet
    ft_match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:ft|feet|foot)$", s)
    if ft_match:
        val_m = float(ft_match.group(1)) * FEET_TO_METERS
        return val_m if 0.5 <= val_m <= 1000.0 else None

    # Meters with optional suffix, e.g. 42, 42m, 42.5 meters
    m_match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:m|meter|meters|metre|metres)?$", s)
    if m_match:
        val_m = float(m_match.group(1))
        return val_m if 0.5 <= val_m <= 1000.0 else None

    return None


def parse_osm_height_m(
    tags: Dict[str, str],
    default_building_height_m: float = 6.0,
    meters_per_level: float = 3.5,
) -> Tuple[float, str]:
    """
    Extracts structure height in meters from OSM tags with fallback heuristics.
    Returns (height_m, source) where source is one of:
    'height', 'levels', 'type_default', or 'default'.
    """
    for key in ("height", "est_height", "building:height"):
        raw = tags.get(key)
        if not raw:
            continue
        parsed_vals = [
            v for part in str(raw).split(";")
            if (v := _parse_single_height_token_m(part)) is not None
        ]
        if parsed_vals:
            return max(parsed_vals), "height"

    raw_levels = tags.get("building:levels")
    if raw_levels:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw_levels))
        if m:
            levels = float(m.group(1))
            if 0.5 <= levels <= 200.0:
                roof_h = 0.0
                raw_roof = tags.get("roof:levels")
                if raw_roof:
                    mr = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw_roof))
                    if mr:
                        roof_h = min(10.0, float(mr.group(1)) * 2.0)
                return levels * meters_per_level + roof_h, "levels"

    man_made = str(tags.get("man_made", "")).strip().lower()
    if man_made in MAN_MADE_DEFAULT_HEIGHTS_M:
        return MAN_MADE_DEFAULT_HEIGHTS_M[man_made], "type_default"

    btype = str(tags.get("building", "")).strip().lower()
    if btype in BUILDING_SUBTYPE_DEFAULT_HEIGHTS_M:
        return BUILDING_SUBTYPE_DEFAULT_HEIGHTS_M[btype], "type_default"

    return float(default_building_height_m), "default"


def _format_osm_address(tags: Dict[str, str]) -> Optional[str]:
    housenum = str(tags.get("addr:housenumber", "")).strip()
    street = str(tags.get("addr:street", "")).strip()
    if housenum and street:
        return f"{housenum} {street}"
    if street:
        return street
    return None


def _format_structure_label(structure_type: str) -> str:
    label_map = {
        "water_tower": "Water Tower",
        "silo": "Grain Silo",
        "communications_tower": "Comm Tower",
        "tower": "Tower",
        "mast": "Radio Mast",
        "building": "Building",
    }
    return label_map.get(structure_type, structure_type.replace("_", " ").title())


def _ring_centroid(pts: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Computes centroid of a 2D ring (falling back to vertex mean if degenerate)."""
    if len(pts) == 0:
        return (0.0, 0.0)
    unique_pts = pts[:-1] if (len(pts) > 1 and pts[0] == pts[-1]) else pts
    if len(unique_pts) < 3:
        xs = [p[0] for p in unique_pts]
        ys = [p[1] for p in unique_pts]
        return (float(np.mean(xs)), float(np.mean(ys)))
    xs = np.array([p[0] for p in unique_pts], dtype=np.float64)
    ys = np.array([p[1] for p in unique_pts], dtype=np.float64)
    xs_next = np.roll(xs, -1)
    ys_next = np.roll(ys, -1)
    cross = xs * ys_next - xs_next * ys
    area2 = float(np.sum(cross))
    if abs(area2) < 1e-6:
        return (float(np.mean(xs)), float(np.mean(ys)))
    cx = float(np.sum((xs + xs_next) * cross) / (3.0 * area2))
    cy = float(np.sum((ys + ys_next) * cross) / (3.0 * area2))
    return (cx, cy)


def _square_footprint(x: float, y: float, half_size_m: float) -> List[Tuple[float, float]]:
    return [
        (x - half_size_m, y - half_size_m),
        (x + half_size_m, y - half_size_m),
        (x + half_size_m, y + half_size_m),
        (x - half_size_m, y + half_size_m),
        (x - half_size_m, y - half_size_m),
    ]


def build_overpass_query(bbox_wgs84: Tuple[float, float, float, float], timeout_s: int = 30) -> str:
    """Builds an Overpass QL query for buildings and tall man-made structures."""
    south, west, north, east = bbox_wgs84
    bbox_str = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    man_made_regex = "^(" + "|".join(TALL_MAN_MADE_TYPES) + ")$"
    return (
        f"[out:json][timeout:{int(timeout_s)}];\n"
        f"(\n"
        f'  way["building"]({bbox_str});\n'
        f'  relation["building"]({bbox_str});\n'
        f'  nwr["man_made"~"{man_made_regex}"]({bbox_str});\n'
        f");\n"
        f"out tags geom;\n"
    )


def parse_overpass_elements(
    elements: Sequence[Dict],
    proj_fn: Callable[[float, float], Tuple[float, float]],
    default_building_height_m: float = 6.0,
    meters_per_level: float = 3.5,
) -> List[BuildingFeature]:
    """Converts raw Overpass JSON elements into projected `BuildingFeature` objects."""
    features: List[BuildingFeature] = []
    seen_ids = set()

    for elem in elements:
        etype = elem.get("type")
        eid = elem.get("id")
        if etype not in ("node", "way", "relation") or eid is None:
            continue
        osm_id = f"{etype}/{eid}"
        if osm_id in seen_ids:
            continue

        tags = elem.get("tags") or {}
        man_made = str(tags.get("man_made", "")).strip().lower()
        btag = str(tags.get("building", "")).strip().lower()
        if not btag and man_made not in TALL_MAN_MADE_TYPES:
            continue

        structure_type = man_made if man_made in TALL_MAN_MADE_TYPES else ("building" if btag in ("", "yes") else btag)
        height_m, height_source = parse_osm_height_m(
            tags,
            default_building_height_m=default_building_height_m,
            meters_per_level=meters_per_level,
        )

        polygons_utm: List[List[Tuple[float, float]]] = []
        lat_c: Optional[float] = None
        lon_c: Optional[float] = None

        if etype == "node":
            if "lat" not in elem or "lon" not in elem:
                continue
            lat_c = float(elem["lat"])
            lon_c = float(elem["lon"])
            ux, uy = proj_fn(lon_c, lat_c)
            half_w = 6.0 if structure_type in ("water_tower", "silo") else 3.0
            polygons_utm.append(_square_footprint(ux, uy, half_w))
        elif etype == "way":
            geom = elem.get("geometry") or []
            if len(geom) < 3:
                continue
            ring_ll = [(float(pt["lon"]), float(pt["lat"])) for pt in geom if "lat" in pt and "lon" in pt]
            if len(ring_ll) < 3:
                continue
            ring_utm = [proj_fn(lon, lat) for lon, lat in ring_ll]
            polygons_utm.append(ring_utm)
            lon_c, lat_c = _ring_centroid(ring_ll)
            ux, uy = _ring_centroid(ring_utm)
        else:
            members = elem.get("members") or []
            outer_rings_ll: List[List[Tuple[float, float]]] = []
            for mem in members:
                if mem.get("role", "") not in ("outer", ""):
                    continue
                mgeom = mem.get("geometry") or []
                ring_ll = [(float(pt["lon"]), float(pt["lat"])) for pt in mgeom if "lat" in pt and "lon" in pt]
                if len(ring_ll) >= 3:
                    outer_rings_ll.append(ring_ll)
                    polygons_utm.append([proj_fn(lon, lat) for lon, lat in ring_ll])
            if not polygons_utm:
                continue
            lon_c, lat_c = _ring_centroid(outer_rings_ll[0])
            ux, uy = _ring_centroid(polygons_utm[0])

        address = _format_osm_address(tags)
        raw_name = str(tags.get("name", "")).strip()
        if raw_name:
            name = raw_name
        elif man_made in TALL_MAN_MADE_TYPES:
            op = str(tags.get("operator", "")).strip()
            lbl = _format_structure_label(structure_type)
            name = f"{op} {lbl}" if op else lbl
        elif address:
            name = address
        else:
            name = f"{_format_structure_label(structure_type)} ({osm_id})"

        seen_ids.add(osm_id)
        features.append(
            BuildingFeature(
                osm_id=osm_id,
                name=name,
                structure_type=structure_type,
                lat=float(lat_c),
                lon=float(lon_c),
                x=float(ux),
                y=float(uy),
                height_m=float(height_m),
                height_source=height_source,
                polygons_utm=polygons_utm,
                address=address,
            )
        )

    return features


def fetch_osm_buildings(
    bbox_wgs84: Tuple[float, float, float, float],
    proj_fn: Callable[[float, float], Tuple[float, float]],
    overpass_url: Optional[str] = None,
    default_building_height_m: float = 6.0,
    timeout_s: float = 30.0,
) -> List[BuildingFeature]:
    """Fetches buildings and tall structures within `bbox_wgs84` from Overpass API."""
    query = build_overpass_query(bbox_wgs84, timeout_s=int(timeout_s))
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    urls = (overpass_url,) if overpass_url else DEFAULT_OVERPASS_URLS

    last_exc: Optional[Exception] = None
    for endpoint in urls:
        try:
            print(
                f"Querying OpenStreetMap buildings & tall structures via Overpass ({endpoint})...",
                flush=True,
            )
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"User-Agent": "lora-gis/1.3 (+https://github.com/nilgrad/lora-gis)"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s + 5.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            elements = payload.get("elements", [])
            features = parse_overpass_elements(
                elements,
                proj_fn=proj_fn,
                default_building_height_m=default_building_height_m,
            )
            tall_count = sum(1 for f in features if f.height_m >= 15.0)
            max_h = max((f.height_m for f in features), default=0.0)
            print(
                f"Loaded {len(features)} OSM structures ({tall_count} >= 15m, max height {max_h:.1f}m).",
                flush=True,
            )
            return features
        except Exception as exc:
            last_exc = exc
            print(f"  Overpass request to {endpoint} failed ({exc}); trying fallback...", flush=True)

    print(f"Warning: All Overpass API requests failed ({last_exc}); continuing without building overlay.", flush=True)
    return []


def rasterize_buildings_onto_dem(
    dem: DEMProvider,
    buildings: Sequence[BuildingFeature],
    target_res_m: float = 2.0,
    max_px: int = 4000,
) -> Optional[Tuple[np.ndarray, float, float, float, float]]:
    """
    Rasterizes building footprint heights onto the bare-earth DEM grid and attaches
    the resulting `dsm_surface = dem_ground + building_heights` to `dem`.
    """
    if dem.cache is None:
        return None

    ground_arr, xmin, ymin, xmax, ymax, gw, gh = dem.cache
    span_x = max(1.0, float(xmax - xmin))
    span_y = max(1.0, float(ymax - ymin))

    eff_res = max(float(target_res_m), span_x / max_px, span_y / max_px)
    out_w = max(1, int(round(span_x / eff_res)))
    out_h = max(1, int(round(span_y / eff_res)))

    if out_w == gw and out_h == gh:
        base_ground = ground_arr.astype(np.float64, copy=True)
    else:
        xs_1d = xmin + (np.arange(out_w, dtype=np.float64) + 0.5) * (span_x / out_w)
        ys_1d = ymax - (np.arange(out_h, dtype=np.float64) + 0.5) * (span_y / out_h)
        xx, yy = np.meshgrid(xs_1d, ys_1d)
        base_ground = dem.sample_ground(xx, yy)

    height_img = Image.new("F", (out_w, out_h), 0.0)
    draw = ImageDraw.Draw(height_img)

    sx = out_w / span_x
    sy = out_h / span_y

    # Sort ascending so taller buildings overwrite shorter overlapping footprints (exact max)
    for feat in sorted(buildings, key=lambda b: b.height_m):
        if feat.height_m <= 0.0:
            continue
        h_val = float(feat.height_m)
        for poly in feat.polygons_utm:
            if len(poly) < 3:
                continue
            px_pts = [((px - xmin) * sx, (ymax - py) * sy) for px, py in poly]
            xs_p = [p[0] for p in px_pts]
            ys_p = [p[1] for p in px_pts]
            if max(xs_p) < 0.0 or min(xs_p) >= out_w or max(ys_p) < 0.0 or min(ys_p) >= out_h:
                continue
            draw.polygon(px_pts, fill=h_val)
            # Ensure narrow towers/masts smaller than one pixel still burn at their centroid
            if (max(xs_p) - min(xs_p)) < 1.0 or (max(ys_p) - min(ys_p)) < 1.0:
                cx_px = int(np.clip(round((feat.x - xmin) * sx), 0, out_w - 1))
                cy_px = int(np.clip(round((ymax - feat.y) * sy), 0, out_h - 1))
                draw.point((cx_px, cy_px), fill=h_val)

    building_grid = np.array(height_img, dtype=np.float64)
    surface_grid = base_ground + building_grid
    dem.set_surface_raster(surface_grid, xmin, ymin, xmax, ymax)

    covered_px = int(np.sum(building_grid > 0.0))
    print(
        f"Rasterized {len(buildings)} buildings onto {out_w}x{out_h} px surface grid "
        f"(~{eff_res:.2f}m/px, {covered_px:,} building pixels).",
        flush=True,
    )
    return (surface_grid, xmin, ymin, xmax, ymax)


def select_tall_structure_candidates(
    buildings: Sequence[BuildingFeature],
    dem: DEMProvider,
    count: int,
    min_height_m: float = 15.0,
    min_separation_m: float = 150.0,
    study_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[BuildingFeature]:
    """
    Selects up to `count` tall structures as candidate relays, ranked by total tip
    elevation ASL (ground + height) with spatial separation deduplication.
    """
    if count <= 0 or not buildings:
        return []

    filtered = [b for b in buildings if b.height_m >= min_height_m]
    if study_bbox is not None:
        bxmin, bymin, bxmax, bymax = study_bbox
        filtered = [b for b in filtered if bxmin <= b.x <= bxmax and bymin <= b.y <= bymax]
    if not filtered:
        return []

    if dem.cache is not None:
        xs = np.array([b.x for b in filtered], dtype=np.float64)
        ys = np.array([b.y for b in filtered], dtype=np.float64)
        ground_vals = dem.sample_ground(xs, ys)
    else:
        ground_vals = np.zeros(len(filtered), dtype=np.float64)

    scored = []
    for feat, g_elev in zip(filtered, ground_vals):
        g_m = float(g_elev) if np.isfinite(g_elev) else 0.0
        tip_asl = g_m + feat.height_m
        explicit_bonus = 1 if feat.height_source in ("height", "levels") else 0
        scored.append((tip_asl, feat.height_m, explicit_bonus, feat))

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    selected: List[BuildingFeature] = []
    for _, _, _, feat in scored:
        if any(np.hypot(feat.x - s.x, feat.y - s.y) < min_separation_m for s in selected):
            continue
        selected.append(feat)
        if len(selected) >= count:
            break

    return selected


def _wkb_to_outer_rings_ll(wkb_bytes: bytes) -> List[List[Tuple[float, float]]]:
    """Decodes WKB Polygon/MultiPolygon bytes into exterior (lon, lat) rings via shapely or GDAL OGR."""
    if not wkb_bytes:
        return []
    try:
        from shapely import wkb as shapely_wkb

        geom = shapely_wkb.loads(wkb_bytes)
        if geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [[(float(x), float(y)) for x, y in geom.exterior.coords]]
        if geom.geom_type == "MultiPolygon":
            return [[(float(x), float(y)) for x, y in poly.exterior.coords] for poly in geom.geoms if not poly.is_empty]
        return []
    except ImportError:
        pass

    try:
        from osgeo import ogr

        geom = ogr.CreateGeometryFromWkb(bytes(wkb_bytes))
        if geom is None:
            return []
        gtype = geom.GetGeometryName().upper()
        rings: List[List[Tuple[float, float]]] = []
        if gtype == "POLYGON":
            if geom.GetGeometryCount() > 0:
                ring = geom.GetGeometryRef(0)
                rings.append([(float(ring.GetX(i)), float(ring.GetY(i))) for i in range(ring.GetPointCount())])
        elif gtype == "MULTIPOLYGON":
            for p_idx in range(geom.GetGeometryCount()):
                poly = geom.GetGeometryRef(p_idx)
                if poly is not None and poly.GetGeometryCount() > 0:
                    ring = poly.GetGeometryRef(0)
                    rings.append([(float(ring.GetX(i)), float(ring.GetY(i))) for i in range(ring.GetPointCount())])
        return rings
    except ImportError:
        return []


def parse_overture_records(
    records: Sequence[Dict],
    proj_fn: Callable[[float, float], Tuple[float, float]],
    default_building_height_m: float = 6.0,
    meters_per_level: float = 3.5,
) -> List[BuildingFeature]:
    """
    Converts Overture Maps `building` theme row dicts (from GeoParquet / PyArrow)
    into projected `BuildingFeature` objects.
    """
    features: List[BuildingFeature] = []
    seen_ids = set()

    for idx, row in enumerate(records):
        raw_id = row.get("id") or f"row-{idx}"
        oid = f"overture/{raw_id}"
        if oid in seen_ids:
            continue

        rings_ll: List[List[Tuple[float, float]]] = []
        raw_geom = row.get("geometry")
        if isinstance(raw_geom, (bytes, bytearray, memoryview)):
            rings_ll = _wkb_to_outer_rings_ll(bytes(raw_geom))
        elif isinstance(raw_geom, dict):
            gtype = raw_geom.get("type")
            coords = raw_geom.get("coordinates") or []
            if gtype == "Polygon" and coords:
                rings_ll = [[(float(p[0]), float(p[1])) for p in coords[0]]]
            elif gtype == "MultiPolygon" and coords:
                rings_ll = [[(float(p[0]), float(p[1])) for p in poly[0]] for poly in coords if poly]
        elif isinstance(raw_geom, (list, tuple)) and raw_geom:
            if isinstance(raw_geom[0], (list, tuple)) and len(raw_geom[0]) >= 2 and isinstance(raw_geom[0][0], (int, float)):
                rings_ll = [[(float(p[0]), float(p[1])) for p in raw_geom]]

        rings_ll = [r for r in rings_ll if len(r) >= 3]
        if not rings_ll:
            continue

        polygons_utm = [[proj_fn(lon, lat) for lon, lat in ring] for ring in rings_ll]
        lon_c, lat_c = _ring_centroid(rings_ll[0])
        ux, uy = _ring_centroid(polygons_utm[0])

        # Height extraction: explicit Overture height -> num_floors -> subtype/class default -> fallback
        raw_h = row.get("height")
        raw_floors = row.get("num_floors")
        raw_roof_h = row.get("roof_height")
        subtype = str(row.get("class") or row.get("subtype") or "building").strip().lower()
        if subtype in ("", "none", "null"):
            subtype = "building"

        height_m: Optional[float] = None
        height_source = "default"
        if raw_h is not None:
            try:
                hv = float(raw_h)
                if np.isfinite(hv) and 0.5 <= hv <= 1000.0:
                    height_m = hv
                    height_source = "overture_height"
            except (TypeError, ValueError):
                pass

        if height_m is None and raw_floors is not None:
            try:
                fv = float(raw_floors)
                if np.isfinite(fv) and 0.5 <= fv <= 200.0:
                    roof_add = 0.0
                    if raw_roof_h is not None:
                        try:
                            rv = float(raw_roof_h)
                            if np.isfinite(rv) and 0.0 < rv <= 30.0:
                                roof_add = rv
                        except (TypeError, ValueError):
                            pass
                    height_m = fv * meters_per_level + roof_add
                    height_source = "levels"
            except (TypeError, ValueError):
                pass

        if height_m is None:
            if subtype in BUILDING_SUBTYPE_DEFAULT_HEIGHTS_M:
                height_m = BUILDING_SUBTYPE_DEFAULT_HEIGHTS_M[subtype]
                height_source = "type_default"
            else:
                height_m = float(default_building_height_m)
                height_source = "default"

        names_field = row.get("names")
        primary_name = ""
        if isinstance(names_field, dict):
            primary_name = str(names_field.get("primary") or "").strip()
        elif isinstance(names_field, str):
            primary_name = names_field.strip()
        elif row.get("name"):
            primary_name = str(row.get("name")).strip()

        display_name = primary_name if primary_name else f"{_format_structure_label(subtype)} ({raw_id[:8]})"
        seen_ids.add(oid)
        features.append(
            BuildingFeature(
                osm_id=oid,
                name=display_name,
                structure_type=subtype,
                lat=float(lat_c),
                lon=float(lon_c),
                x=float(ux),
                y=float(uy),
                height_m=float(height_m),
                height_source=height_source,
                polygons_utm=polygons_utm,
                address=None,
            )
        )

    return features


def fetch_overture_buildings(
    bbox_wgs84: Tuple[float, float, float, float],
    proj_fn: Callable[[float, float], Tuple[float, float]],
    default_building_height_m: float = 6.0,
) -> List[BuildingFeature]:
    """
    Streams Overture Maps building footprints and ML-derived heights from cloud
    GeoParquet via the optional `overturemaps` Python client.
    """
    try:
        from overturemaps import record_batch_reader
    except ImportError as exc:
        raise RuntimeError(
            "Overture Maps building backend requires the optional 'overturemaps' package. "
            "Install with: pip install \"lora-gis[overture]\" (or pip install overturemaps shapely)."
        ) from exc

    south, west, north, east = bbox_wgs84
    print(
        f"Querying Overture Maps GeoParquet buildings for bbox ({west:.4f},{south:.4f},{east:.4f},{north:.4f})...",
        flush=True,
    )
    reader = record_batch_reader("building", bbox=(west, south, east, north))
    if reader is None:
        return []
    table = reader.read_all()
    cols = [c for c in ("id", "geometry", "height", "num_floors", "roof_height", "subtype", "class", "names") if c in table.column_names]
    records = table.select(cols).to_pylist()
    features = parse_overture_records(
        records,
        proj_fn=proj_fn,
        default_building_height_m=default_building_height_m,
    )
    tall_count = sum(1 for f in features if f.height_m >= 15.0)
    max_h = max((f.height_m for f in features), default=0.0)
    print(
        f"Loaded {len(features)} Overture buildings ({tall_count} >= 15m, max height {max_h:.1f}m).",
        flush=True,
    )
    return features


def merge_building_datasets(
    overture_buildings: Sequence[BuildingFeature],
    osm_buildings: Sequence[BuildingFeature],
    match_radius_m: float = 25.0,
) -> List[BuildingFeature]:
    """
    Merges Overture Maps buildings with OpenStreetMap buildings and tall `man_made`
    structures: enriches matching Overture footprints with OSM names, street addresses,
    and explicit height tags, and appends unmatched OSM tall structures (water towers,
    grain silos, radio towers).
    """
    merged: List[BuildingFeature] = []
    matched_osm_ids = set()

    osm_xs = np.array([b.x for b in osm_buildings], dtype=np.float64) if osm_buildings else np.empty(0)
    osm_ys = np.array([b.y for b in osm_buildings], dtype=np.float64) if osm_buildings else np.empty(0)

    for ob in overture_buildings:
        best_osm: Optional[BuildingFeature] = None
        if len(osm_buildings) > 0:
            dists = np.hypot(osm_xs - ob.x, osm_ys - ob.y)
            min_idx = int(np.argmin(dists))
            if float(dists[min_idx]) <= match_radius_m:
                best_osm = osm_buildings[min_idx]
                matched_osm_ids.add(best_osm.osm_id)

        if best_osm is None:
            merged.append(ob)
            continue

        # Prefer explicit OSM name/address when Overture lacks a real name
        ob_is_generic = "(" in ob.name and ob.name.endswith(")")
        osm_is_generic = "(" in best_osm.name and best_osm.name.endswith(")")
        name = best_osm.name if (ob_is_generic and not osm_is_generic) else ob.name
        address = ob.address or best_osm.address

        # Keep explicit height tags over fallback heuristics
        if best_osm.height_source == "height" and ob.height_source != "overture_height":
            height_m, h_src = best_osm.height_m, best_osm.height_source
        elif ob.height_source in ("overture_height", "levels"):
            height_m, h_src = ob.height_m, ob.height_source
        elif best_osm.height_source in ("height", "levels", "type_default"):
            height_m, h_src = best_osm.height_m, best_osm.height_source
        else:
            height_m, h_src = max(ob.height_m, best_osm.height_m), ob.height_source

        merged.append(
            BuildingFeature(
                osm_id=ob.osm_id,
                name=name,
                structure_type=best_osm.structure_type if best_osm.structure_type in TALL_MAN_MADE_TYPES else ob.structure_type,
                lat=ob.lat,
                lon=ob.lon,
                x=ob.x,
                y=ob.y,
                height_m=height_m,
                height_source=h_src,
                polygons_utm=ob.polygons_utm,
                address=address,
            )
        )

    # Append unmatched OSM tall man-made structures (water towers, silos, towers) and named tall buildings
    for osm_b in osm_buildings:
        if osm_b.osm_id in matched_osm_ids:
            continue
        if osm_b.structure_type in TALL_MAN_MADE_TYPES or osm_b.height_m >= 15.0:
            merged.append(osm_b)

    return merged
