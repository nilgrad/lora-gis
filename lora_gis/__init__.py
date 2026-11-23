"""lora-gis: PyQGIS Line-of-Sight (LOS) and LoRa / MeshCore RF Repeater Pathfinder."""

from .buildings import (
    BuildingFeature,
    fetch_osm_buildings,
    parse_osm_height_m,
    rasterize_buildings_onto_dem,
    select_tall_structure_candidates,
)
from .cli import apply_cli_args, main, run_analysis
from .config import BASEMAP_PRESETS, DEM_PRESETS, DEM_UNIT_SCALES, LoRaGISConfig, normalize_loc_key, parse_height_value_m
from .dem import DEMProvider
from .geonames import lookup_geonames_place, resolve_location
from .utm import detect_utm_crs

__version__ = "1.1.1"
__all__ = [
    "BASEMAP_PRESETS",
    "BuildingFeature",
    "DEM_PRESETS",
    "DEM_UNIT_SCALES",
    "DEMProvider",
    "LoRaGISConfig",
    "apply_cli_args",
    "detect_utm_crs",
    "fetch_osm_buildings",
    "lookup_geonames_place",
    "main",
    "normalize_loc_key",
    "parse_height_value_m",
    "parse_osm_height_m",
    "rasterize_buildings_onto_dem",
    "resolve_location",
    "run_analysis",
    "select_tall_structure_candidates",
]
