"""Natural Resources Canada (NRCan) CanElevation Series (HRDEM / MRDEM-30) STAC + COG streaming."""

import hashlib
import json
import os
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple
import urllib.parse
import urllib.request

import numpy as np

NRCAN_STAC_SEARCH_URL = "https://datacube.services.geo.ca/stac/api/search"
NRCAN_USER_AGENT = "lora-gis/1.3 (+https://github.com/nilgrad/lora-gis)"

NRCAN_DEM_PRESETS: Dict[str, Dict] = {
    "canada-hrdem": {
        "collections": ("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
        "load_dsm": False,
        "label": "NRCan HRDEM 1m DTM",
    },
    "nrcan-hrdem": {
        "collections": ("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
        "load_dsm": False,
        "label": "NRCan HRDEM 1m DTM",
    },
    "canada-hrdem-dsm": {
        "collections": ("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
        "load_dsm": True,
        "label": "NRCan HRDEM 1m LiDAR DSM",
    },
    "nrcan-hrdem-dsm": {
        "collections": ("hrdem-mosaic-1m", "hrdem-mosaic-2m", "mrdem-30"),
        "load_dsm": True,
        "label": "NRCan HRDEM 1m LiDAR DSM",
    },
    "canada-mrdem": {
        "collections": ("mrdem-30",),
        "load_dsm": False,
        "label": "NRCan MRDEM-30 DTM",
    },
    "nrcan-mrdem": {
        "collections": ("mrdem-30",),
        "load_dsm": False,
        "label": "NRCan MRDEM-30 DTM",
    },
    "canada-mrdem-dsm": {
        "collections": ("mrdem-30",),
        "load_dsm": True,
        "label": "NRCan MRDEM-30 DSM",
    },
    "nrcan-mrdem-dsm": {
        "collections": ("mrdem-30",),
        "load_dsm": True,
        "label": "NRCan MRDEM-30 DSM",
    },
}


def is_canada_dem_source(dem_source: Optional[str]) -> bool:
    """Returns True if `dem_source` is a built-in NRCan CanElevation preset."""
    if not dem_source:
        return False
    return dem_source.strip().lower() in NRCAN_DEM_PRESETS


def is_canada_dsm_source(dem_source: Optional[str]) -> bool:
    """Returns True if `dem_source` requests both DTM and DSM from NRCan CanElevation."""
    if not dem_source:
        return False
    spec = NRCAN_DEM_PRESETS.get(dem_source.strip().lower())
    return bool(spec and spec.get("load_dsm"))


def utm_bounds_to_wgs84_bbox(
    utm_bounds: Tuple[float, float, float, float],
    wkid: int,
) -> Tuple[float, float, float, float]:
    """
    Transforms (xmin, ymin, xmax, ymax) in `EPSG:{wkid}` to WGS84 (west, south, east, north)
    by transforming all four corners to handle meridian convergence at northern latitudes.
    """
    from osgeo import osr

    osr.UseExceptions()
    src = osr.SpatialReference()
    src.ImportFromEPSG(int(wkid))
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)

    xmin, ymin, xmax, ymax = (float(v) for v in utm_bounds)
    corners = [
        ct.TransformPoint(xmin, ymin),
        ct.TransformPoint(xmin, ymax),
        ct.TransformPoint(xmax, ymin),
        ct.TransformPoint(xmax, ymax),
    ]
    lons = [float(pt[0]) for pt in corners]
    lats = [float(pt[1]) for pt in corners]
    return (min(lons), min(lats), max(lons), max(lats))


def search_nrcan_stac_assets(
    collection: str,
    bbox_wgs84_wsen: Tuple[float, float, float, float],
    asset_key: str = "dtm",
    stac_search_url: str = NRCAN_STAC_SEARCH_URL,
    timeout_s: float = 20.0,
) -> List[str]:
    """
    Queries the NRCan CCMEO STAC API for COG asset hrefs matching `collection` and `asset_key`
    within WGS84 `bbox_wgs84_wsen` (west, south, east, north).
    """
    west, south, east, north = (float(v) for v in bbox_wgs84_wsen)
    params = urllib.parse.urlencode({
        "collections": collection,
        "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
        "limit": "25",
    })
    url = f"{stac_search_url}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": NRCAN_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    hrefs: List[str] = []
    seen = set()
    for feat in payload.get("features", []):
        assets = feat.get("assets") or {}
        asset = assets.get(asset_key)
        if not isinstance(asset, dict):
            continue
        href = asset.get("href")
        if href and href not in seen:
            seen.add(href)
            hrefs.append(str(href))
    return hrefs


def _to_gdal_vsi_path(href: str) -> str:
    """Prefixes HTTP(S) URLs with GDAL `/vsicurl/` while preserving local or VSI paths."""
    if href.startswith("/vsi"):
        return href
    if href.startswith("http://") or href.startswith("https://"):
        return f"/vsicurl/{href}"
    return href


def _warp_cog_sources_to_array(
    hrefs: Sequence[str],
    utm_bounds: Tuple[float, float, float, float],
    wkid: int,
    out_w: int,
    out_h: int,
    resample_mode: str = "bilinear",
    unit_scale: float = 1.0,
) -> np.ndarray:
    """
    Streams and warps one or more COG / GeoTIFF sources into an `(out_h, out_w)` float64
    elevation array in `EPSG:{wkid}` covering `utm_bounds`.
    """
    from osgeo import gdal

    if gdal.GetDriverCount() == 0:
        gdal.AllRegister()
    gdal.UseExceptions()

    # Tune GDAL /vsicurl/ to avoid extra S3 directory listings and sidecar lookups
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.vrt")
    gdal.SetConfigOption("GDAL_HTTP_MULTIRANGE", "YES")
    gdal.SetConfigOption("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
    gdal.SetConfigOption("VSI_CACHE", "TRUE")

    vsi_paths = [_to_gdal_vsi_path(h) for h in hrefs]
    if len(vsi_paths) == 1:
        src_ds = gdal.Open(vsi_paths[0], gdal.GA_ReadOnly)
    else:
        src_ds = gdal.BuildVRT("", vsi_paths)

    if src_ds is None:
        raise RuntimeError(f"Failed to open NRCan COG source(s): {hrefs}")

    src_band = src_ds.GetRasterBand(1)
    src_nodata = src_band.GetNoDataValue() if src_band is not None else None

    xmin, ymin, xmax, ymax = (float(v) for v in utm_bounds)
    resample_alg = gdal.GRA_NearestNeighbour if resample_mode == "nearest" else gdal.GRA_Bilinear
    warp_opts = gdal.WarpOptions(
        format="MEM",
        dstSRS=f"EPSG:{int(wkid)}",
        outputBounds=(xmin, ymin, xmax, ymax),
        width=int(out_w),
        height=int(out_h),
        resampleAlg=resample_alg,
        outputType=gdal.GDT_Float64,
        dstNodata=float("nan"),
    )
    try:
        warped = gdal.Warp("", src_ds, options=warp_opts)
    finally:
        src_ds = None

    if warped is None:
        raise RuntimeError(f"GDAL warp failed for NRCan COG source(s): {hrefs}")

    arr = warped.GetRasterBand(1).ReadAsArray().astype(np.float64, copy=False)
    warped = None

    if src_nodata is not None and np.isfinite(src_nodata):
        arr = np.where(np.isclose(arr, src_nodata, rtol=0.0, atol=1e-6), np.nan, arr)
    arr = np.where(np.isfinite(arr) & (arr > -9000.0), arr * float(unit_scale), np.nan)
    return arr


def stream_nrcan_elevation_grid(
    collections: Sequence[str],
    asset_key: str,
    utm_bounds: Tuple[float, float, float, float],
    wkid: int,
    resolution_m: float = 2.0,
    max_px: int = 4000,
    resample_mode: str = "bilinear",
    unit_scale: float = 1.0,
    stac_search_url: str = NRCAN_STAC_SEARCH_URL,
    cache_dir: Optional[str] = None,
) -> Tuple[np.ndarray, float, float, float, float, int, int, List[str]]:
    """
    Streams an elevation raster (`dtm` or `dsm`) from NRCan CanElevation STAC COG collections
    in priority order, automatically backfilling any NoData gaps from fallback collections
    (e.g. `hrdem-mosaic-1m` -> `hrdem-mosaic-2m` -> `mrdem-30`).

    Returns `(arr, xmin, ymin, xmax, ymax, out_w, out_h, used_collections)`.
    """
    xmin, ymin, xmax, ymax = (float(v) for v in utm_bounds)
    span_x = max(1.0, xmax - xmin)
    span_y = max(1.0, ymax - ymin)
    eff_res = max(float(resolution_m), span_x / max(1, int(max_px)), span_y / max(1, int(max_px)))
    out_w = max(1, int(round(span_x / eff_res)))
    out_h = max(1, int(round(span_y / eff_res)))

    use_cache = cache_dir != ""
    cache_path = None
    meta_path = None
    if use_cache:
        cdir = cache_dir or os.path.join(tempfile.gettempdir(), "lora_gis_cache")
        os.makedirs(cdir, exist_ok=True)
        key_str = (
            f"{tuple(collections)}|{asset_key}|{wkid}|"
            f"{xmin:.1f},{ymin:.1f},{xmax:.1f},{ymax:.1f}|{out_w}x{out_h}|{resample_mode}|{unit_scale}"
        )
        digest = hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:14]
        cache_path = os.path.join(cdir, f"nrcan_{asset_key}_{digest}.npy")
        meta_path = os.path.join(cdir, f"nrcan_{asset_key}_{digest}.json")
        if os.path.isfile(cache_path) and os.path.isfile(meta_path):
            try:
                cached_arr = np.load(cache_path).astype(np.float64, copy=False)
                with open(meta_path, "r", encoding="utf-8") as mf:
                    meta = json.load(mf)
                if cached_arr.shape == (out_h, out_w):
                    used_cols = list(meta.get("used_collections", []))
                    return (cached_arr, xmin, ymin, xmax, ymax, out_w, out_h, used_cols)
            except Exception:
                pass

    bbox_wsen = utm_bounds_to_wgs84_bbox((xmin, ymin, xmax, ymax), wkid)
    result: Optional[np.ndarray] = None
    used_collections: List[str] = []
    last_exc: Optional[Exception] = None

    for col in collections:
        try:
            hrefs = search_nrcan_stac_assets(
                collection=col,
                bbox_wgs84_wsen=bbox_wsen,
                asset_key=asset_key,
                stac_search_url=stac_search_url,
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"  NRCan STAC search for '{col}' ({asset_key}) failed ({exc}); trying fallback...",
                flush=True,
            )
            continue

        if not hrefs:
            continue

        try:
            arr = _warp_cog_sources_to_array(
                hrefs=hrefs,
                utm_bounds=(xmin, ymin, xmax, ymax),
                wkid=wkid,
                out_w=out_w,
                out_h=out_h,
                resample_mode=resample_mode,
                unit_scale=unit_scale,
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"  NRCan COG stream for '{col}' ({asset_key}) failed ({exc}); trying fallback...",
                flush=True,
            )
            continue

        valid_mask = np.isfinite(arr)
        if not np.any(valid_mask):
            continue

        if result is None:
            result = arr
            used_collections.append(col)
        else:
            missing_mask = ~np.isfinite(result)
            fill_mask = missing_mask & valid_mask
            if np.any(fill_mask):
                result = np.where(fill_mask, arr, result)
                used_collections.append(col)

        if result is not None and np.all(np.isfinite(result)):
            break

    if result is None or not np.any(np.isfinite(result)):
        detail = f" ({last_exc})" if last_exc is not None else ""
        raise RuntimeError(
            f"No valid NRCan CanElevation '{asset_key}' coverage found for bbox {bbox_wsen} "
            f"across collections {list(collections)}{detail}."
        )

    if use_cache and cache_path is not None and meta_path is not None:
        try:
            np.save(cache_path, result.astype(np.float32))
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump({"used_collections": used_collections}, mf)
        except Exception:
            pass

    return (result, xmin, ymin, xmax, ymax, out_w, out_h, used_collections)


def load_nrcan_dem(
    dem,
    dem_source: str,
    utm_bounds: Tuple[float, float, float, float],
    wkid: int,
    resolution_m: float = 3.0,
    max_px: int = 2500,
    stac_search_url: str = NRCAN_STAC_SEARCH_URL,
    cache_dir: Optional[str] = None,
) -> Dict:
    """
    Streams NRCan CanElevation bare-earth DTM (into `dem.cache`) and optionally
    LiDAR DSM (into `dem.surface_cache`) for `dem_source`.
    """
    key = dem_source.strip().lower()
    spec = NRCAN_DEM_PRESETS.get(key)
    if spec is None:
        raise ValueError(f"Unknown NRCan DEM preset '{dem_source}'.")

    collections = spec["collections"]
    load_dsm = bool(spec["load_dsm"])
    xmin, ymin, xmax, ymax = (float(v) for v in utm_bounds)

    dtm_mode = "bilinear" if load_dsm else dem.sampling_mode
    print(
        f"Streaming NRCan CanElevation DTM ({', '.join(collections)})...",
        flush=True,
    )
    dtm_arr, c_xmin, c_ymin, c_xmax, c_ymax, w, h, dtm_cols = stream_nrcan_elevation_grid(
        collections=collections,
        asset_key="dtm",
        utm_bounds=(xmin, ymin, xmax, ymax),
        wkid=wkid,
        resolution_m=resolution_m,
        max_px=max_px,
        resample_mode=dtm_mode,
        unit_scale=dem.unit_scale,
        stac_search_url=stac_search_url,
        cache_dir=cache_dir,
    )
    dem.cache = (dtm_arr, c_xmin, c_ymin, c_xmax, c_ymax, w, h)
    dem.pixel_res_m = min((c_xmax - c_xmin) / max(1, w), (c_ymax - c_ymin) / max(1, h))
    valid_dtm = dtm_arr[np.isfinite(dtm_arr)]
    print(
        f"Loaded NRCan DTM ({w}x{h} px, ~{dem.pixel_res_m:.2f}m/px, "
        f"sources: {', '.join(dtm_cols)}, Elev range: {valid_dtm.min():.1f}m - {valid_dtm.max():.1f}m).",
        flush=True,
    )

    dsm_cols: List[str] = []
    if load_dsm and not dem.has_separate_surface:
        dsm_res = min(float(resolution_m), 2.0)
        dsm_max_px = max(int(max_px), 4000)
        print(
            f"Streaming NRCan CanElevation DSM ({', '.join(collections)})...",
            flush=True,
        )
        dsm_arr, s_xmin, s_ymin, s_xmax, s_ymax, sw, sh, dsm_cols = stream_nrcan_elevation_grid(
            collections=collections,
            asset_key="dsm",
            utm_bounds=(xmin, ymin, xmax, ymax),
            wkid=wkid,
            resolution_m=dsm_res,
            max_px=dsm_max_px,
            resample_mode="nearest",
            unit_scale=dem.unit_scale,
            stac_search_url=stac_search_url,
            cache_dir=cache_dir,
        )
        dem.surface_cache = (dsm_arr, s_xmin, s_ymin, s_xmax, s_ymax, sw, sh)
        dem.pixel_res_m = min((s_xmax - s_xmin) / max(1, sw), (s_ymax - s_ymin) / max(1, sh))
        valid_dsm = dsm_arr[np.isfinite(dsm_arr)]
        print(
            f"Loaded NRCan DSM ({sw}x{sh} px, ~{dem.pixel_res_m:.2f}m/px, "
            f"sources: {', '.join(dsm_cols)}, Elev range: {valid_dsm.min():.1f}m - {valid_dsm.max():.1f}m).",
            flush=True,
        )

    return {"dtm_collections": dtm_cols, "dsm_collections": dsm_cols}
