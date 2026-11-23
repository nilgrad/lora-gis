"""Optional USGS 3DEP LiDAR Entwine Point Tile (EPT) DSM streaming via PDAL."""

import hashlib
import json
import os
import tempfile
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

from .dem import DEMProvider

DEFAULT_USGS_EPT_INDEX_URLS = (
    "https://raw.githubusercontent.com/hobuinc/usgs-lidar/master/boundaries/resources.geojson",
    "https://usgs.entwine.io/boundaries/resources.geojson",
)


def _feature_bbox_wgs84(geom: Dict) -> Optional[Tuple[float, float, float, float]]:
    """Computes (south, west, north, east) bbox for a GeoJSON Polygon or MultiPolygon."""
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None

    lons: List[float] = []
    lats: List[float] = []
    if gtype == "Polygon":
        for ring in coords:
            for pt in ring:
                if len(pt) >= 2:
                    lons.append(float(pt[0]))
                    lats.append(float(pt[1]))
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for pt in ring:
                    if len(pt) >= 2:
                        lons.append(float(pt[0]))
                        lats.append(float(pt[1]))
    else:
        return None

    if not lons:
        return None
    return (min(lats), min(lons), max(lats), max(lons))


def match_ept_resources_for_bbox(
    geojson_data: Dict,
    bbox_wgs84: Tuple[float, float, float, float],
    max_datasets: int = 3,
) -> List[Dict]:
    """
    Finds USGS 3DEP EPT resources whose boundary polygons intersect `bbox_wgs84`
    (south, west, north, east), sorted newest / highest point count first.
    """
    q_s, q_w, q_n, q_e = bbox_wgs84
    matches: List[Dict] = []

    for feat in geojson_data.get("features", []):
        props = feat.get("properties") or {}
        url = props.get("url")
        if not url:
            continue
        geom = feat.get("geometry") or {}
        fb = _feature_bbox_wgs84(geom)
        if fb is None:
            continue
        f_s, f_w, f_n, f_e = fb
        if f_e < q_w or f_w > q_e or f_n < q_s or f_s > q_n:
            continue

        name = str(props.get("name") or url)
        count = int(props.get("count") or 0)
        # Extract 4-digit acquisition year from dataset name when available (e.g. KS_Statewide_2018)
        year = 0
        for tok in name.replace("-", "_").split("_"):
            if len(tok) == 4 and tok.isdigit() and 1990 <= int(tok) <= 2035:
                year = max(year, int(tok))

        matches.append({
            "name": name,
            "url": str(url),
            "count": count,
            "year": year,
        })

    matches.sort(key=lambda m: (m["year"], m["count"]), reverse=True)
    return matches[: max(1, int(max_datasets))]


def load_usgs_ept_index(
    index_urls: Sequence[str] = DEFAULT_USGS_EPT_INDEX_URLS,
    cache_dir: Optional[str] = None,
    timeout_s: float = 25.0,
) -> Dict:
    """Downloads (and locally caches) the USGS 3DEP EPT resources.geojson index."""
    cdir = cache_dir or os.path.join(tempfile.gettempdir(), "lora_gis_cache")
    os.makedirs(cdir, exist_ok=True)
    cache_file = os.path.join(cdir, "usgs_3dep_ept_resources.geojson")

    if os.path.isfile(cache_file) and os.path.getsize(cache_file) > 1024:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    last_exc: Optional[Exception] = None
    for url in index_urls:
        try:
            print(f"Downloading USGS 3DEP EPT project index ({url})...", flush=True)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "lora-gis/1.2 (+https://github.com/nilgrad/lora-gis)"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw_bytes = resp.read()
            data = json.loads(raw_bytes.decode("utf-8"))
            with open(cache_file, "wb") as f:
                f.write(raw_bytes)
            return data
        except Exception as exc:
            last_exc = exc

    raise RuntimeError(f"Failed to download USGS 3DEP EPT index: {last_exc}")


def bbox_wgs84_to_3857(bbox_wgs84: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """Transforms (south, west, north, east) WGS84 bbox to Web Mercator (xmin, ymin, xmax, ymax)."""
    from osgeo import osr

    src = osr.SpatialReference()
    src.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(3857)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)

    south, west, north, east = bbox_wgs84
    sw_x, sw_y, _ = ct.TransformPoint(west, south)
    ne_x, ne_y, _ = ct.TransformPoint(east, north)
    return (min(sw_x, ne_x), min(sw_y, ne_y), max(sw_x, ne_x), max(sw_y, ne_y))


def build_pdal_dsm_pipeline(
    ept_urls: Sequence[str],
    bounds_3857: Tuple[float, float, float, float],
    output_tif_path: str,
    resolution_m: float = 2.0,
    dst_epsg: Optional[int] = None,
) -> Dict:
    """
    Constructs a PDAL pipeline dictionary that streams USGS 3DEP EPT point clouds,
    filters noise classes (7 and 18), optionally reprojects to UTM, and rasterizes
    a first-return maximum-Z DSM GeoTIFF.
    """
    xmin, ymin, xmax, ymax = bounds_3857
    bounds_str = f"([{xmin:.2f}, {xmax:.2f}], [{ymin:.2f}, {ymax:.2f}])"

    stages: List[Dict] = []
    for url in ept_urls:
        stages.append({
            "type": "readers.ept",
            "filename": str(url),
            "bounds": bounds_str,
            "resolution": float(resolution_m),
        })

    if len(ept_urls) > 1:
        stages.append({"type": "filters.merge"})

    # Exclude ASPRS low noise (7) and high noise (18)
    stages.append({
        "type": "filters.range",
        "limits": "Classification![7:7],Classification![18:18]",
    })

    if dst_epsg is not None:
        stages.append({
            "type": "filters.reprojection",
            "out_srs": f"EPSG:{int(dst_epsg)}",
        })

    stages.append({
        "type": "writers.gdal",
        "filename": output_tif_path,
        "gdaldriver": "GTiff",
        "output_type": "max",
        "resolution": float(resolution_m),
        "window_size": 3,
        "nodata": -9999.0,
        "data_type": "float32",
    })
    return {"pipeline": stages}


def stream_3dep_lidar_dsm(
    dem: DEMProvider,
    bbox_wgs84: Tuple[float, float, float, float],
    utm_bounds: Tuple[float, float, float, float],
    wkid: int,
    resolution_m: float = 2.0,
    ept_url: Optional[str] = None,
    max_area_km2: float = 36.0,
) -> str:
    """
    Streams a true 1-2 m USGS 3DEP LiDAR DSM (buildings + tree canopy) via PDAL EPT
    into a temporary GeoTIFF and attaches it to `dem.surface_cache`.
    Returns the path to the generated GeoTIFF (cached in temp dir).
    """
    try:
        import pdal
    except ImportError as exc:
        raise RuntimeError(
            "USGS 3DEP LiDAR EPT streaming requires the optional 'pdal' package. "
            "Install via conda ('conda install -c conda-forge python-pdal') or "
            "'pip install \"lora-gis[lidar]\"'."
        ) from exc

    uxmin, uymin, uxmax, uymax = utm_bounds
    area_km2 = max(0.0, (uxmax - uxmin) * (uymax - uymin)) / 1e6
    if area_km2 > max_area_km2:
        print(
            f"Warning: Study area ({area_km2:.1f} km^2) exceeds recommended LiDAR EPT limit "
            f"({max_area_km2:.0f} km^2); streaming may take longer.",
            flush=True,
        )

    if ept_url:
        ept_urls = [ept_url]
    else:
        index_data = load_usgs_ept_index()
        matches = match_ept_resources_for_bbox(index_data, bbox_wgs84, max_datasets=2)
        if not matches:
            raise RuntimeError(
                f"No USGS 3DEP LiDAR EPT dataset found intersecting bbox {bbox_wgs84}."
            )
        ept_urls = [m["url"] for m in matches]
        names = ", ".join(m["name"] for m in matches)
        print(f"Matched USGS 3DEP LiDAR EPT dataset(s): {names}", flush=True)

    bounds_3857 = bbox_wgs84_to_3857(bbox_wgs84)
    cache_dir = os.path.join(tempfile.gettempdir(), "lora_gis_cache")
    os.makedirs(cache_dir, exist_ok=True)
    key_str = f"{ept_urls}|{bounds_3857}|{wkid}|{resolution_m}"
    digest = hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:12]
    out_tif = os.path.join(cache_dir, f"usgs_3dep_dsm_{digest}.tif")

    if not os.path.isfile(out_tif):
        pipeline_dict = build_pdal_dsm_pipeline(
            ept_urls=ept_urls,
            bounds_3857=bounds_3857,
            output_tif_path=out_tif,
            resolution_m=resolution_m,
            dst_epsg=wkid,
        )
        print(
            f"Streaming USGS 3DEP LiDAR point cloud via PDAL ({resolution_m:.1f}m/px DSM)...",
            flush=True,
        )
        pipe = pdal.Pipeline(json.dumps(pipeline_dict))
        pt_count = pipe.execute()
        print(f"Streamed {pt_count:,} LiDAR points into DSM GeoTIFF '{out_tif}'.", flush=True)

    dem.surface_cache = dem._load_geotiff_to_cache(
        out_tif,
        uxmin,
        uymin,
        uxmax,
        uymax,
        max_px=4000,
        resample_mode="nearest",
        label="3DEP LiDAR DSM",
    )
    if dem.surface_cache is not None:
        _, s_xmin, s_ymin, s_xmax, s_ymax, w, h = dem.surface_cache
        dem.pixel_res_m = min((s_xmax - s_xmin) / max(1, w), (s_ymax - s_ymin) / max(1, h))
    return out_tif
