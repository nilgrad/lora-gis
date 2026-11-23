"""DEM elevation raster streaming, local GeoTIFF loading, and bilinear interpolation."""

import io
import json
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple
import numpy as np
from PIL import Image


class DEMProvider:
    """Manages DEM raster caching, bilinear interpolation, and fallback point queries."""

    def __init__(self, image_server_base: str, wkid: int, dem_file: Optional[str] = None):
        self.image_server_base = image_server_base.rstrip("/")
        self.export_image_url = f"{self.image_server_base}/exportImage"
        self.samples_url = f"{self.image_server_base}/getSamples"
        self.wkid = wkid
        self.dem_file = dem_file
        self.cache: Optional[Tuple[np.ndarray, float, float, float, float, int, int]] = None

    def load_raster(
        self,
        xmin: float,
        ymin: float,
        xmax: float,
        ymax: float,
        resolution_m: float = 3.0,
        max_px: int = 2500,
    ) -> None:
        """Loads a 32-bit float elevation raster for the study bounding box."""
        if self.dem_file:
            self._load_local_geotiff(xmin, ymin, xmax, ymax)
            return

        span_x = max(1.0, float(xmax - xmin))
        span_y = max(1.0, float(ymax - ymin))
        caps_to_try = []
        for c in (max_px, 2000, 1500):
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
                    f"Streaming high-resolution DEM elevation grid ({width}x{height} px, ~{eff_res:.1f}m/px)...",
                    flush=True,
                )
                with urllib.request.urlopen(url, timeout=25.0) as resp:
                    tiff_bytes = resp.read()
                img = Image.open(io.BytesIO(tiff_bytes))
                dem_arr = np.array(img, dtype=np.float64)
                self.cache = (dem_arr, xmin, ymin, xmax, ymax, dem_arr.shape[1], dem_arr.shape[0])
                print(
                    f"Loaded DEM grid ({dem_arr.shape[1]}x{dem_arr.shape[0]} px, "
                    f"Elev range: {dem_arr.min():.1f}m - {dem_arr.max():.1f}m).",
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

    def _load_local_geotiff(self, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
        """Loads a local GeoTIFF file via PIL."""
        img = Image.open(self.dem_file)
        dem_arr = np.array(img, dtype=np.float64)
        self.cache = (dem_arr, xmin, ymin, xmax, ymax, dem_arr.shape[1], dem_arr.shape[0])
        print(
            f"Loaded local DEM GeoTIFF '{self.dem_file}' ({dem_arr.shape[1]}x{dem_arr.shape[0]} px).",
            flush=True,
        )

    def sample_bilinear(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Bilinearly interpolates ground elevations (meters) from the cached DEM grid."""
        assert self.cache is not None
        dem_arr, xmin, ymin, xmax, ymax, w, h = self.cache
        col_f = np.clip((xs - xmin) / (xmax - xmin) * (w - 1), 0.0, w - 1.0001)
        row_f = np.clip((ymax - ys) / (ymax - ymin) * (h - 1), 0.0, h - 1.0001)
        c0 = col_f.astype(int)
        r0 = row_f.astype(int)
        c1 = np.minimum(c0 + 1, w - 1)
        r1 = np.minimum(r0 + 1, h - 1)
        dc = col_f - c0
        dr = row_f - r0
        return (
            dem_arr[r0, c0] * (1.0 - dc) * (1.0 - dr)
            + dem_arr[r0, c1] * dc * (1.0 - dr)
            + dem_arr[r1, c0] * (1.0 - dc) * dr
            + dem_arr[r1, c1] * dc * dr
        )

    def fetch_elevations(self, points: List[Tuple[float, float]]) -> List[float]:
        """Returns elevation values (meters) from cached DEM grid or HTTP point stream."""
        if len(points) == 0:
            return []
        if self.cache is not None:
            _, xmin, ymin, xmax, ymax, _, _ = self.cache
            xs = np.array([p[0] for p in points], dtype=np.float64)
            ys = np.array([p[1] for p in points], dtype=np.float64)
            if np.all((xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)):
                return self.sample_bilinear(xs, ys).tolist()

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
                                batch_vals[loc_id] = float(s.get("value"))
                            except (TypeError, ValueError):
                                batch_vals[loc_id] = -9999.0
                    elevations.extend(batch_vals)
            except Exception:
                elevations.extend([-9999.0] * len(batch))

        if len(elevations) < len(points):
            elevations.extend([-9999.0] * (len(points) - len(elevations)))
        return elevations
