"""DEM/DSM elevation raster streaming, georeferenced GeoTIFF loading, and interpolation."""

import io
import json
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image

RasterCache = Tuple[np.ndarray, float, float, float, float, int, int]


def _sample_raster(
    cache: RasterCache,
    xs: np.ndarray,
    ys: np.ndarray,
    mode: str = "bilinear",
) -> np.ndarray:
    """Samples elevation values (meters) from a cached raster grid using bilinear or nearest mode."""
    arr, xmin, ymin, xmax, ymax, w, h = cache
    xs_arr = np.asarray(xs, dtype=np.float64)
    ys_arr = np.asarray(ys, dtype=np.float64)

    span_x = max(1e-9, xmax - xmin)
    span_y = max(1e-9, ymax - ymin)
    in_bounds = (xs_arr >= xmin) & (xs_arr <= xmax) & (ys_arr >= ymin) & (ys_arr <= ymax)

    if mode == "nearest":
        col = np.clip(np.floor((xs_arr - xmin) / span_x * w).astype(int), 0, w - 1)
        row = np.clip(np.floor((ymax - ys_arr) / span_y * h).astype(int), 0, h - 1)
        vals = arr[row, col].astype(np.float64, copy=True)
        return np.where(in_bounds, vals, np.nan)

    # Pixel-center aligned bilinear interpolation matching GDAL geotransform conventions.
    if w == 1:
        col_f = np.zeros_like(xs_arr, dtype=np.float64)
    else:
        col_f = np.clip((xs_arr - xmin) / span_x * w - 0.5, 0.0, w - 1.000001)
    if h == 1:
        row_f = np.zeros_like(ys_arr, dtype=np.float64)
    else:
        row_f = np.clip((ymax - ys_arr) / span_y * h - 0.5, 0.0, h - 1.000001)

    c0 = col_f.astype(int)
    r0 = row_f.astype(int)
    c1 = np.minimum(c0 + 1, w - 1)
    r1 = np.minimum(r0 + 1, h - 1)
    dc = col_f - c0
    dr = row_f - r0

    v00 = arr[r0, c0]
    v01 = arr[r0, c1]
    v10 = arr[r1, c0]
    v11 = arr[r1, c1]

    vals = (
        v00 * (1.0 - dc) * (1.0 - dr)
        + v01 * dc * (1.0 - dr)
        + v10 * (1.0 - dc) * dr
        + v11 * dc * dr
    )
    return np.where(in_bounds, vals, np.nan)


class DEMProvider:
    """Manages DEM and optional DSM raster caching, interpolation, and fallback point queries."""

    def __init__(
        self,
        image_server_base: str,
        wkid: int,
        dem_file: Optional[str] = None,
        unit_scale: float = 1.0,
        sampling_mode: str = "bilinear",
        dsm_file: Optional[str] = None,
    ):
        self.image_server_base = image_server_base.rstrip("/")
        self.export_image_url = f"{self.image_server_base}/exportImage"
        self.samples_url = f"{self.image_server_base}/getSamples"
        self.wkid = wkid
        self.dem_file = dem_file
        self.dsm_file = dsm_file
        self.unit_scale = float(unit_scale)
        self.sampling_mode = sampling_mode.strip().lower()
        self.cache: Optional[RasterCache] = None
        self.surface_cache: Optional[RasterCache] = None
        self.pixel_res_m: Optional[float] = None

    @property
    def has_separate_surface(self) -> bool:
        return self.surface_cache is not None

    def set_surface_raster(
        self,
        surface_arr: np.ndarray,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
    ) -> None:
        """Attaches an external surface elevation grid (e.g. DEM + rasterized buildings)."""
        arr = np.asarray(surface_arr, dtype=np.float64)
        h, w = arr.shape
        self.surface_cache = (arr, float(xmin), float(ymin), float(xmax), float(ymax), w, h)
        self.pixel_res_m = min((xmax - xmin) / max(1, w), (ymax - ymin) / max(1, h))

    def load_raster(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        resolution_m: float = 3.0,
        max_px: int = 2500,
    ) -> None:
        """Loads a 32/64-bit elevation raster for the study bounding box (plus optional DSM)."""
        if self.dem_file:
            ground_mode = "bilinear" if self.dsm_file else self.sampling_mode
            ground_label = "DEM" if (self.dsm_file or self.sampling_mode == "bilinear") else "DSM"
            self.cache = self._load_geotiff_to_cache(
                self.dem_file,
                xmin,
                ymin,
                xmax,
                ymax,
                max_px=max(max_px, 4000),
                resample_mode=ground_mode,
                label=ground_label,
            )
            if self.cache is not None:
                _, c_xmin, c_ymin, c_xmax, c_ymax, w, h = self.cache
                self.pixel_res_m = min((c_xmax - c_xmin) / max(1, w), (c_ymax - c_ymin) / max(1, h))
        else:
            self._stream_arcgis_raster(xmin, ymin, xmax, ymax, resolution_m=resolution_m, max_px=max_px)

        if self.dsm_file:
            self.surface_cache = self._load_geotiff_to_cache(
                self.dsm_file,
                xmin,
                ymin,
                xmax,
                ymax,
                max_px=max(max_px, 4000),
                resample_mode="nearest",
                label="DSM",
            )
            if self.surface_cache is not None:
                _, s_xmin, s_ymin, s_xmax, s_ymax, w, h = self.surface_cache
                self.pixel_res_m = min((s_xmax - s_xmin) / max(1, w), (s_ymax - s_ymin) / max(1, h))

    def _stream_arcgis_raster(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        resolution_m: float = 3.0,
        max_px: int = 2500,
    ) -> None:
        """Streams a 32-bit float elevation raster from an ArcGIS ImageServer."""
        span_x = max(1.0, float(xmax - xmin))
        span_y = max(1.0, float(ymax - ymin))
        caps_to_try = []
        for c in (max_px, 2500, 2000, 1500):
            if c <= max_px and c not in caps_to_try:
                caps_to_try.append(c)

        last_exc = None
        for cap in caps_to_try:
            eff_res = max(float(resolution_m), span_x / cap, span_y / cap)
            width = max(1, int(round(span_x / eff_res)))
            height = max(1, int(round(span_y / eff_res)))
            params = urllib.parse.urlencode({
                "bbox": f"{xmin},{ymin},{xmax},{ymax}",
                "bboxSR": str(self.wkid),
                "imageSR": str(self.wkid),
                "size": f"{width},{height}",
                "adjustAspectRatio": "false",
                "format": "tiff",
                "pixelType": "F32",
                "f": "image",
            })
            url = f"{self.export_image_url}?{params}"
            try:
                print(
                    f"Streaming high-resolution elevation grid ({width}x{height} px, ~{eff_res:.1f}m/px)...",
                    flush=True,
                )
                with urllib.request.urlopen(url, timeout=25.0) as resp:
                    tiff_bytes = resp.read()
                img = Image.open(io.BytesIO(tiff_bytes))
                dem_arr = np.array(img, dtype=np.float64)
                dem_arr = np.where(np.isfinite(dem_arr) & (dem_arr > -9000.0), dem_arr * self.unit_scale, np.nan)
                self.cache = (dem_arr, xmin, ymin, xmax, ymax, dem_arr.shape[1], dem_arr.shape[0])
                self.pixel_res_m = eff_res
                valid_vals = dem_arr[np.isfinite(dem_arr)]
                if valid_vals.size > 0:
                    print(
                        f"Loaded elevation grid ({dem_arr.shape[1]}x{dem_arr.shape[0]} px, "
                        f"Elev range: {valid_vals.min():.1f}m - {valid_vals.max():.1f}m).",
                        flush=True,
                    )
                return
            except Exception as exc:
                last_exc = exc
                print(
                    f"  DEM request at {width}x{height} px failed ({exc}); retrying at lower resolution...",
                    flush=True,
                )

        print(f"Warning: DEM raster stream failed ({last_exc}), falling back to point queries.", flush=True)
        self.cache = None

    def _load_geotiff_to_cache(
        self,
        file_path: str,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        max_px: int = 4000,
        resample_mode: str = "bilinear",
        label: str = "DEM",
    ) -> RasterCache:
        """
        Loads a local GeoTIFF with true GDAL georeferencing, reprojecting and clipping
        to the active UTM CRS and study bounding box. Falls back to PIL only for
        ungeoreferenced raw TIFF files.
        """
        try:
            from osgeo import gdal, osr
            if gdal.GetDriverCount() == 0:
                gdal.AllRegister()
            gdal.UseExceptions()
        except ImportError:
            return self._load_local_geotiff_pil(file_path, xmin, ymin, xmax, ymax, label=label)

        ds = gdal.Open(file_path, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Failed to open GeoTIFF '{file_path}' with GDAL.")

        proj_wkt = ds.GetProjection() or ""
        gt = ds.GetGeoTransform(can_return_null=True)
        has_georef = bool(proj_wkt.strip()) and gt is not None and (gt != (0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
        if not has_georef:
            print(
                f"Warning: '{file_path}' lacks GeoTIFF georeferencing metadata; "
                f"falling back to study bounding box extent.",
                flush=True,
            )
            ds = None
            return self._load_local_geotiff_pil(file_path, xmin, ymin, xmax, ymax, label=label)

        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromEPSG(int(self.wkid))
        dst_wkt = dst_srs.ExportToWkt()

        vrt = gdal.AutoCreateWarpedVRT(ds, None, dst_wkt)
        if vrt is None:
            ds = None
            raise RuntimeError(f"Failed to reproject GeoTIFF '{file_path}' to EPSG:{self.wkid}.")

        vgt = vrt.GetGeoTransform()
        vw, vh = vrt.RasterXSize, vrt.RasterYSize
        r_xmin = float(vgt[0])
        r_xmax = float(vgt[0] + vgt[1] * vw)
        r_ymax = float(vgt[3])
        r_ymin = float(vgt[3] + vgt[5] * vh)
        if r_xmin > r_xmax:
            r_xmin, r_xmax = r_xmax, r_xmin
        if r_ymin > r_ymax:
            r_ymin, r_ymax = r_ymax, r_ymin
        nat_res_x = max(1e-6, abs(float(vgt[1])))
        nat_res_y = max(1e-6, abs(float(vgt[5])))
        vrt = None

        # Clip to the overlap between the GeoTIFF and requested study bounding box
        ixmin = max(r_xmin, float(xmin))
        iymin = max(r_ymin, float(ymin))
        ixmax = min(r_xmax, float(xmax))
        iymax = min(r_ymax, float(ymax))

        if ixmin >= ixmax or iymin >= iymax:
            ds = None
            raise ValueError(
                f"Local {label} GeoTIFF '{file_path}' (EPSG:{self.wkid} bounds "
                f"[{r_xmin:.1f}, {r_ymin:.1f}, {r_xmax:.1f}, {r_ymax:.1f}]) "
                f"does not overlap the study bounding box "
                f"[{xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f}]."
            )

        span_x = ixmax - ixmin
        span_y = iymax - iymin
        eff_res_x = max(nat_res_x, span_x / max_px)
        eff_res_y = max(nat_res_y, span_y / max_px)
        out_w = max(1, int(round(span_x / eff_res_x)))
        out_h = max(1, int(round(span_y / eff_res_y)))

        src_band = ds.GetRasterBand(1)
        src_nodata = src_band.GetNoDataValue()

        resample_alg = gdal.GRA_NearestNeighbour if resample_mode == "nearest" else gdal.GRA_Bilinear
        warp_opts = gdal.WarpOptions(
            format="MEM",
            dstSRS=f"EPSG:{self.wkid}",
            outputBounds=(ixmin, iymin, ixmax, iymax),
            width=out_w,
            height=out_h,
            resampleAlg=resample_alg,
            outputType=gdal.GDT_Float64,
            dstNodata=float("nan"),
        )
        warped = gdal.Warp("", ds, options=warp_opts)
        ds = None
        if warped is None:
            raise RuntimeError(f"GDAL warp failed for GeoTIFF '{file_path}'.")

        arr = warped.GetRasterBand(1).ReadAsArray().astype(np.float64, copy=False)
        warped = None

        if src_nodata is not None and np.isfinite(src_nodata):
            arr = np.where(np.isclose(arr, src_nodata, rtol=0.0, atol=1e-6), np.nan, arr)
        arr = np.where(np.isfinite(arr) & (arr > -9000.0), arr * self.unit_scale, np.nan)

        valid_vals = arr[np.isfinite(arr)]
        elev_summary = (
            f"Elev range: {valid_vals.min():.1f}m - {valid_vals.max():.1f}m"
            if valid_vals.size > 0
            else "No valid pixels"
        )
        print(
            f"Loaded georeferenced {label} GeoTIFF '{file_path}' "
            f"({out_w}x{out_h} px, ~{min(eff_res_x, eff_res_y):.2f}m/px, {elev_summary}).",
            flush=True,
        )
        return (arr, ixmin, iymin, ixmax, iymax, out_w, out_h)

    def _load_local_geotiff_pil(
        self,
        file_path: str,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        label: str = "DEM",
    ) -> RasterCache:
        """Fallback raw TIFF loader via PIL when GDAL or georeferencing is unavailable."""
        img = Image.open(file_path)
        arr = np.array(img, dtype=np.float64)
        arr = np.where(np.isfinite(arr) & (arr > -9000.0), arr * self.unit_scale, np.nan)
        print(
            f"Loaded local {label} TIFF '{file_path}' via PIL ({arr.shape[1]}x{arr.shape[0]} px).",
            flush=True,
        )
        return (arr, xmin, ymin, xmax, ymax, arr.shape[1], arr.shape[0])

    def _load_local_geotiff(self, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
        """Backwards-compatible helper wrapping georeferenced GeoTIFF loading."""
        assert self.dem_file is not None
        self.cache = self._load_geotiff_to_cache(
            self.dem_file,
            xmin,
            ymin,
            xmax,
            ymax,
            resample_mode=self.sampling_mode,
            label="DEM" if self.sampling_mode == "bilinear" else "DSM",
        )

    def sample_bilinear(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Bilinearly interpolates ground elevations (meters) from the cached DEM grid."""
        assert self.cache is not None
        return _sample_raster(self.cache, xs, ys, mode="bilinear")

    def sample_nearest(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Samples elevations (meters) via nearest-neighbor from the active surface/DEM grid."""
        target = self.surface_cache if self.surface_cache is not None else self.cache
        assert target is not None
        return _sample_raster(target, xs, ys, mode="nearest")

    def sample_ground(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Samples bare-earth ground elevation (meters) from `self.cache`."""
        assert self.cache is not None
        mode = "bilinear" if self.surface_cache is not None else self.sampling_mode
        return _sample_raster(self.cache, xs, ys, mode=mode)

    def sample_surface(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Samples top-of-surface elevation (buildings/trees/terrain in meters)."""
        if self.surface_cache is not None:
            return _sample_raster(self.surface_cache, xs, ys, mode="nearest")
        assert self.cache is not None
        return _sample_raster(self.cache, xs, ys, mode=self.sampling_mode)

    def fetch_elevations(self, points: List[Tuple[float, float]]) -> List[float]:
        """Returns ground elevation values (meters) from cached grid or HTTP point stream."""
        if len(points) == 0:
            return []
        if self.cache is not None:
            _, xmin, ymin, xmax, ymax, _, _ = self.cache
            xs = np.array([p[0] for p in points], dtype=np.float64)
            ys = np.array([p[1] for p in points], dtype=np.float64)
            if np.all((xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)):
                vals = self.sample_ground(xs, ys)
                if np.all(np.isfinite(vals)):
                    return vals.tolist()

        elevations: List[float] = []
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            multipoint_json = {
                "points": [[float(p[0]), float(p[1])] for p in batch],
                "spatialReference": {"wkid": self.wkid},
            }
            payload = {
                "geometry": json.dumps(multipoint_json),
                "geometryType": "esriGeometryMultipoint",
                "returnFirstValueOnly": "true",
                "f": "json",
            }
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(self.samples_url, data=data)
            try:
                with urllib.request.urlopen(req, timeout=5.0) as response:
                    res_json = json.loads(response.read().decode("utf-8"))
                    batch_vals = [-9999.0] * len(batch)
                    for idx_s, s in enumerate(res_json.get("samples", [])):
                        loc_id = s.get("locationId", idx_s)
                        if isinstance(loc_id, int) and 0 <= loc_id < len(batch):
                            try:
                                raw_v = float(s.get("value"))
                                batch_vals[loc_id] = raw_v * self.unit_scale if raw_v > -9000.0 else -9999.0
                            except (TypeError, ValueError):
                                batch_vals[loc_id] = -9999.0
                    elevations.extend(batch_vals)
            except Exception:
                elevations.extend([-9999.0] * len(batch))

        if len(elevations) < len(points):
            elevations.extend([-9999.0] * (len(points) - len(elevations)))
        return elevations
