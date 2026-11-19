"""Configuration model and unit parsing utilities for lora-gis."""

from dataclasses import dataclass, field
import json
import os
import re
from typing import Dict, List, Optional, Tuple


DEM_PRESETS = {
    "usgs-3dep": "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer",
    "ny-gis": "https://elevation.its.ny.gov/arcgis/rest/services/Latest_DEM/ImageServer",
}

DEFAULT_GEONAMES_URL = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
DEFAULT_TOPO_BASEMAP_URL = (
    "type=xyz&url=https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}&zmax=16&zmin=0"
)
DEFAULT_FALLBACK_BASEMAP_URL = (
    "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0"
)

HEIGHT_SENSITIVITY_SCENARIOS = [
    ("30 ft (9.14 m)", 9.14),
    ("33 ft (10.0 m)", 10.0),
    ("45 ft (13.7 m)", 13.72),
    ("60 ft (18.3 m)", 18.29),
    ("63 ft (19.14 m = 10m + 30ft)", 19.14),
    ("90 ft (27.4 m)", 27.43),
]


def normalize_loc_key(raw_name: str) -> str:
    """Normalizes a location name or slug to lowercase hyphenated form."""
    cleaned = raw_name.split(",")[0].strip().lower()
    return re.sub(r"[\s_]+", "-", cleaned)


def parse_height_value_m(val_str: str | float | int) -> float:
    """Parses a height string like '30ft', '10m', or '9.14' into meters."""
    if isinstance(val_str, (int, float)):
        return float(val_str)
    s = str(val_str).strip().lower()
    if s.endswith("ft") or s.endswith("feet") or s.endswith("'"):
        num = float(re.sub(r"[^0-9.+-]", "", s))
        return num / 3.28084
    if s.endswith("m") or s.endswith("meters"):
        num = float(re.sub(r"[^0-9.+-]", "", s))
        return num
    return float(s)


@dataclass
class LoRaGISConfig:
    """Complete configuration for a LoRa / MeshCore GIS RF pathfinding analysis."""

    title: str = "LoRa-GIS"
    # Named locations catalog: slug -> {"name": str, "lat": float, "lon": float, "height_m": float}
    locations: Dict[str, Dict] = field(default_factory=dict)
    default_route: List[str] = field(default_factory=list)
    default_links: List[Tuple[str, str]] = field(default_factory=list)
    candidate_relays: List[str] = field(default_factory=list)
    default_state: Optional[str] = None

    # Antenna & repeater heights (meters)
    default_observer_height_m: float = 10.0   # ~33 ft
    default_repeater_height_m: float = 9.14   # ~30 ft (intermediate hub repeater)
    relay_height_m: float = 18.3              # ~60 ft (tree/mast intermediate relay)
    candidate_height_m: Optional[float] = None  # Optional override for explicit candidate relays

    # RF propagation parameters
    freq_mhz: float = 915.0
    min_fresnel_clearance: float = 0.60
    earth_radius_eff_m: float = 8495000.0     # 4/3 effective Earth radius (m)

    # Grid search & LOS parameters
    initial_grid_step_m: float = 500.0
    min_grid_step_m: float = 150.0
    step_factor: float = 0.6
    grid_padding_m: float = 1000.0
    narrow_axis_padding_m: float = 2500.0
    los_num_samples: int = 80
    min_relay_separation_m: float = 500.0
    max_candidate_pairs: int = 1500
    hops_override: Optional[int] = None

    # Map & Report export settings
    output_dir: str = "results"
    base_dir: str = field(default_factory=os.getcwd)
    map_width: int = 1920
    map_height: int = 1080
    map_dpi: int = 144
    map_extent_scale: float = 1.45

    # GIS & DEM settings
    dem_source: str = "usgs-3dep"             # Preset key ('usgs-3dep', 'ny-gis') or custom URL
    dem_file: Optional[str] = None            # Optional local GeoTIFF path
    crs_epsg: Optional[str] = None            # Auto-detected UTM zone if None
    geonames_url: str = DEFAULT_GEONAMES_URL
    topo_basemap_url: str = DEFAULT_TOPO_BASEMAP_URL
    fallback_basemap_url: str = DEFAULT_FALLBACK_BASEMAP_URL

    # Runtime populated fields
    active_links: List[Tuple[str, str]] = field(default_factory=list)
    active_candidate_keys: List[str] = field(default_factory=list)
    custom_height_keys: set = field(default_factory=set)

    @property
    def wavelength_m(self) -> float:
        return 299.792458 / self.freq_mhz

    @property
    def image_server_base(self) -> str:
        return DEM_PRESETS.get(self.dem_source, self.dem_source)

    def load_json_config(self, path: str) -> None:
        """Merges settings and locations from a JSON configuration file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "title" in data:
            self.title = str(data["title"])
        if "default_state" in data:
            self.default_state = str(data["default_state"])
        if "freq_mhz" in data:
            self.freq_mhz = float(data["freq_mhz"])
        if "min_fresnel_clearance" in data:
            self.min_fresnel_clearance = float(data["min_fresnel_clearance"])
        if "relay_height" in data:
            self.relay_height_m = parse_height_value_m(data["relay_height"])
        if "candidate_height" in data:
            self.candidate_height_m = parse_height_value_m(data["candidate_height"])
        if "observer_height" in data:
            self.default_observer_height_m = parse_height_value_m(data["observer_height"])
        if "repeater_height" in data:
            self.default_repeater_height_m = parse_height_value_m(data["repeater_height"])
        if "dem_source" in data:
            self.dem_source = str(data["dem_source"])
        if "dem_file" in data:
            self.dem_file = str(data["dem_file"])
        if "crs_epsg" in data:
            self.crs_epsg = str(data["crs_epsg"])
        if "output_dir" in data:
            self.output_dir = str(data["output_dir"])

        for raw_key, loc_info in data.get("locations", {}).items():
            k = normalize_loc_key(raw_key)
            h_m = (
                parse_height_value_m(loc_info["height"])
                if "height" in loc_info
                else float(loc_info.get("height_m", self.default_observer_height_m))
            )
            self.locations[k] = {
                "name": loc_info.get("name", raw_key.replace("-", " ").title()),
                "lat": float(loc_info["lat"]),
                "lon": float(loc_info["lon"]),
                "height_m": h_m,
            }

        if "route" in data:
            self.default_route = [str(x) for x in data["route"]]
        if "links" in data:
            self.default_links = [(str(pair[0]), str(pair[1])) for pair in data["links"]]
        if "candidate_relays" in data:
            self.candidate_relays = [str(x) for x in data["candidate_relays"]]
