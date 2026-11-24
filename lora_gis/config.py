"""Configuration model and unit parsing utilities for lora-gis."""

from dataclasses import dataclass, field
import json
import os
import re
from typing import Dict, List, Optional, Tuple


from .nrcan import NRCAN_DEM_PRESETS, NRCAN_STAC_SEARCH_URL, is_canada_dem_source, is_canada_dsm_source


DEM_PRESETS = {
    "usgs-3dep": "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer",
    "ny-gis": "https://elevation.its.ny.gov/arcgis/rest/services/Latest_DEM/ImageServer",
    "canada-hrdem": NRCAN_STAC_SEARCH_URL,
    "canada-hrdem-dsm": NRCAN_STAC_SEARCH_URL,
    "canada-mrdem": NRCAN_STAC_SEARCH_URL,
    "canada-mrdem-dsm": NRCAN_STAC_SEARCH_URL,
}

FEET_TO_METERS = 0.3048
US_SURVEY_FEET_TO_METERS = 1200.0 / 3937.0

DEM_UNIT_SCALES = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "ft": FEET_TO_METERS,
    "foot": FEET_TO_METERS,
    "feet": FEET_TO_METERS,
    "us-ft": US_SURVEY_FEET_TO_METERS,
    "us_ft": US_SURVEY_FEET_TO_METERS,
}

DEFAULT_GEONAMES_URL = "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer"
DEFAULT_CGNDB_URL = "https://geogratis.gc.ca/services/geoname/en/geonames.json"
DEFAULT_TOPO_BASEMAP_URL = (
    "type=xyz&url=https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}&zmax=16&zmin=0"
)
DEFAULT_FALLBACK_BASEMAP_URL = (
    "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0"
)
DEFAULT_CANADA_TOPO_BASEMAP_URL = (
    "contextualWMSLegend=0&crs=EPSG:3857&dpiMode=7&featureCount=10&format=image/png&layers=CBMT&styles=&url=https://maps.geogratis.gc.ca/wms/CBMT"
)
DEFAULT_OSM_BASEMAP_URL = (
    "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
)
DEFAULT_SATELLITE_BASEMAP_URL = (
    "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0"
)

BASEMAP_PRESETS = {
    "topo": DEFAULT_TOPO_BASEMAP_URL,
    "world-topo": DEFAULT_FALLBACK_BASEMAP_URL,
    "canada-topo": DEFAULT_CANADA_TOPO_BASEMAP_URL,
    "osm": DEFAULT_OSM_BASEMAP_URL,
    "satellite": DEFAULT_SATELLITE_BASEMAP_URL,
}

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


def parse_distance_m(val_str: str | float | int) -> float:
    """Parses a distance string like '3km', '2mi', '2500m', or '5000ft' into meters."""
    if isinstance(val_str, (int, float)):
        return float(val_str)
    s = str(val_str).strip().lower()
    if s.endswith("km") or s.endswith("kilometers") or s.endswith("kilometres"):
        num = float(re.sub(r"[^0-9.+-]", "", s))
        return num * 1000.0
    if s.endswith("mi") or s.endswith("mile") or s.endswith("miles"):
        num = float(re.sub(r"[^0-9.+-]", "", s))
        return num * 1609.344
    if s.endswith("ft") or s.endswith("feet") or s.endswith("'"):
        num = float(re.sub(r"[^0-9.+-]", "", s))
        return num * FEET_TO_METERS
    if s.endswith("m") or s.endswith("meters") or s.endswith("metres"):
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
    dem_source: str = "usgs-3dep"             # Preset key ('usgs-3dep', 'usgs-3dep-dsm', 'ny-gis', 'canada-hrdem', 'canada-hrdem-dsm', 'canada-mrdem') or custom URL
    dem_file: Optional[str] = None            # Optional local GeoTIFF path (bare-earth DEM or DSM)
    dsm_file: Optional[str] = None            # Optional separate local DSM GeoTIFF (buildings/trees)
    dem_units: str = "m"                      # Vertical elevation units ('m', 'ft', 'us-ft')
    surface_mode: str = "dem"                 # 'dem' (bare-earth bilinear) or 'dsm' (nearest + urban sampling)
    buildings_source: str = "none"            # Building overlay source ('none', 'osm', 'overture', 'hybrid')
    default_building_height_m: float = 6.0    # Fallback height (m) for untagged buildings
    overpass_url: Optional[str] = None        # Optional custom Overpass API endpoint
    lidar_ept: bool = False                   # Stream 1-2m USGS 3DEP LiDAR DSM via optional PDAL backend
    lidar_resolution_m: float = 2.0           # Target resolution (m/px) for streamed LiDAR EPT DSM
    ept_url: Optional[str] = None             # Optional explicit EPT ept.json URL
    auto_candidates: int = 0                  # Auto-evaluate top N tall buildings/towers as candidates
    min_building_height_m: float = 15.0       # Minimum structure height (m) for --auto-candidates
    rooftop_mast_height_m: float = 3.05       # Default mast height (~10 ft) on auto-selected rooftops
    sample_step_m: Optional[float] = None     # Optional override for ray sample spacing (m)
    rooftop_margin_m: Optional[float] = None  # Near-field endpoint exclusion margin in DSM mode (m)
    crs_epsg: Optional[str] = None            # Auto-detected UTM zone if None
    geonames_url: str = DEFAULT_GEONAMES_URL
    cgndb_url: str = DEFAULT_CGNDB_URL
    nrcan_stac_url: str = NRCAN_STAC_SEARCH_URL
    basemap: str = "topo"                     # Preset ('topo', 'world-topo', 'canada-topo', 'osm', 'satellite') or custom QGIS URI
    topo_basemap_url: str = DEFAULT_TOPO_BASEMAP_URL
    fallback_basemap_url: str = DEFAULT_FALLBACK_BASEMAP_URL

    # City viewshed & rooftop ranking settings
    city_target: Optional[str] = None         # Center place or 'name=lat,lon' for --city mode
    city_radius_m: float = 3000.0             # Study radius (m) around city center
    city_top_n: int = 10                      # Top N ranked structures in report & map
    city_rx_height_m: float = 1.83            # ~6 ft handheld target receiver height AGL
    city_mast_height_m: float = 3.05          # ~10 ft rooftop mast height above structure
    city_max_sites: int = 25                  # Max candidate structures evaluated before ranking top N
    viewshed_grid_size: int = 61              # Cartesian target grid samples per axis

    # Runtime populated fields
    active_links: List[Tuple[str, str]] = field(default_factory=list)
    active_candidate_keys: List[str] = field(default_factory=list)
    custom_height_keys: set = field(default_factory=set)
    basemap_explicit: bool = False
    buildings_explicit: bool = False
    dem_explicit: bool = False

    @property
    def wavelength_m(self) -> float:
        return 299.792458 / self.freq_mhz

    @property
    def image_server_base(self) -> str:
        if self.dem_source.strip().lower() == "usgs-3dep-dsm":
            return DEM_PRESETS["usgs-3dep"]
        return DEM_PRESETS.get(self.dem_source, self.dem_source)

    @property
    def is_canada_dem(self) -> bool:
        return is_canada_dem_source(self.dem_source)

    @property
    def use_canada_dsm(self) -> bool:
        return is_canada_dsm_source(self.dem_source)

    @property
    def use_lidar_ept(self) -> bool:
        return bool(self.lidar_ept) or self.dem_source.strip().lower() == "usgs-3dep-dsm"

    @property
    def surface_kind_label(self) -> str:
        spec = NRCAN_DEM_PRESETS.get(self.dem_source.strip().lower())
        if spec and spec.get("load_dsm"):
            return str(spec["label"])
        if self.use_lidar_ept:
            return "USGS 3DEP LiDAR EPT DSM"
        return "DSM"

    @property
    def dem_unit_scale(self) -> float:
        key = self.dem_units.strip().lower()
        if key not in DEM_UNIT_SCALES:
            valid = ", ".join(sorted({"m", "ft", "us-ft"}))
            raise ValueError(f"Unsupported dem_units '{self.dem_units}'. Expected one of: {valid}.")
        return DEM_UNIT_SCALES[key]

    @property
    def is_dsm_mode(self) -> bool:
        return (
            self.surface_mode.strip().lower() == "dsm"
            or self.dsm_file is not None
            or self.use_lidar_ept
            or self.use_canada_dsm
            or self.buildings_source.strip().lower() != "none"
            or self.city_target is not None
        )

    @property
    def effective_sample_step_m(self) -> float:
        if self.sample_step_m is not None:
            return max(0.5, float(self.sample_step_m))
        return 5.0 if self.is_dsm_mode else 25.0

    @property
    def effective_rooftop_margin_m(self) -> float:
        if self.rooftop_margin_m is not None:
            return max(0.0, float(self.rooftop_margin_m))
        return 12.0 if self.is_dsm_mode else 0.0

    @property
    def active_basemap_url(self) -> str:
        key = self.basemap.strip().lower()
        if key == "topo" and self.topo_basemap_url != DEFAULT_TOPO_BASEMAP_URL:
            return self.topo_basemap_url
        return BASEMAP_PRESETS.get(key, self.basemap)

    def load_json_config(self, path: str) -> None:
        """Merges settings and locations from a JSON configuration file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "title" in data:
            self.title = str(data["title"])
        if "default_state" in data:
            self.default_state = str(data["default_state"])
        elif "default_province" in data:
            self.default_state = str(data["default_province"])
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
            self.dem_explicit = True
        if "dem_file" in data:
            self.dem_file = str(data["dem_file"])
        if "dsm_file" in data:
            self.dsm_file = str(data["dsm_file"])
        if "dem_units" in data:
            self.dem_units = str(data["dem_units"])
        if "surface_mode" in data:
            self.surface_mode = str(data["surface_mode"])
        if "buildings" in data:
            self.buildings_source = str(data["buildings"])
            self.buildings_explicit = True
        elif "buildings_source" in data:
            self.buildings_source = str(data["buildings_source"])
            self.buildings_explicit = True
        if "default_building_height" in data:
            self.default_building_height_m = parse_height_value_m(data["default_building_height"])
        elif "default_building_height_m" in data:
            self.default_building_height_m = float(data["default_building_height_m"])
        if "overpass_url" in data:
            self.overpass_url = str(data["overpass_url"])
        if "lidar_ept" in data:
            self.lidar_ept = bool(data["lidar_ept"])
        if "lidar_resolution_m" in data:
            self.lidar_resolution_m = float(data["lidar_resolution_m"])
        if "ept_url" in data:
            self.ept_url = str(data["ept_url"])
        if "auto_candidates" in data:
            self.auto_candidates = int(data["auto_candidates"])
        if "min_building_height" in data:
            self.min_building_height_m = parse_height_value_m(data["min_building_height"])
        elif "min_building_height_m" in data:
            self.min_building_height_m = float(data["min_building_height_m"])
        if "city" in data:
            self.city_target = str(data["city"])
        if "radius" in data:
            self.city_radius_m = parse_distance_m(data["radius"])
        elif "city_radius_m" in data:
            self.city_radius_m = float(data["city_radius_m"])
        if "top" in data:
            self.city_top_n = int(data["top"])
        if "rx_height" in data:
            self.city_rx_height_m = parse_height_value_m(data["rx_height"])
        if "mast_height" in data:
            self.city_mast_height_m = parse_height_value_m(data["mast_height"])
        if "max_sites" in data:
            self.city_max_sites = int(data["max_sites"])
        if "viewshed_grid" in data:
            self.viewshed_grid_size = int(data["viewshed_grid"])
        if "sample_step_m" in data:
            self.sample_step_m = float(data["sample_step_m"])
        if "rooftop_margin" in data:
            self.rooftop_margin_m = parse_height_value_m(data["rooftop_margin"])
        elif "rooftop_margin_m" in data:
            self.rooftop_margin_m = float(data["rooftop_margin_m"])
        if "basemap" in data:
            self.basemap = str(data["basemap"])
            self.basemap_explicit = True
        if "initial_grid_step_m" in data:
            self.initial_grid_step_m = float(data["initial_grid_step_m"])
        if "min_grid_step_m" in data:
            self.min_grid_step_m = float(data["min_grid_step_m"])
        if "crs_epsg" in data:
            self.crs_epsg = str(data["crs_epsg"])
        if "cgndb_url" in data:
            self.cgndb_url = str(data["cgndb_url"])
        if "nrcan_stac_url" in data:
            self.nrcan_stac_url = str(data["nrcan_stac_url"])
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
