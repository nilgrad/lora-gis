"""lora-gis: PyQGIS Line-of-Sight (LOS) and LoRa / MeshCore RF Repeater Pathfinder."""

from .cli import apply_cli_args, main, run_analysis
from .config import BASEMAP_PRESETS, DEM_PRESETS, DEM_UNIT_SCALES, LoRaGISConfig, normalize_loc_key, parse_height_value_m
from .dem import DEMProvider
from .geonames import lookup_geonames_place, resolve_location
from .utm import detect_utm_crs

__version__ = "1.1.1"
__all__ = [
    "BASEMAP_PRESETS",
    "DEM_PRESETS",
    "DEM_UNIT_SCALES",
    "DEMProvider",
    "LoRaGISConfig",
    "apply_cli_args",
    "detect_utm_crs",
    "lookup_geonames_place",
    "main",
    "normalize_loc_key",
    "parse_height_value_m",
    "resolve_location",
    "run_analysis",
]
