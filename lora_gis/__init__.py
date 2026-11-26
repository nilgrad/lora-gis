"""lora-gis: PyQGIS Line-of-Sight (LOS) and LoRa / MeshCore RF Repeater Pathfinder."""

from .buildings import (
    BuildingFeature,
    fetch_osm_buildings,
    fetch_overture_buildings,
    merge_building_datasets,
    parse_osm_height_m,
    parse_overture_records,
    rasterize_buildings_onto_dem,
    select_tall_structure_candidates,
)
from .cartography import render_candidate_profiles, render_path_profiles
from .cli import apply_cli_args, main, run_analysis
from .config import (
    BASEMAP_PRESETS,
    DEM_PRESETS,
    DEM_UNIT_SCALES,
    LoRaGISConfig,
    normalize_loc_key,
    parse_distance_m,
    parse_height_value_m,
)
from .dem import DEMProvider
from .geonames import (
    fetch_cgndb_features,
    is_canada_province,
    lookup_cgndb_place,
    lookup_geonames_place,
    resolve_location,
)
from .lidar import (
    build_pdal_dsm_pipeline,
    match_ept_resources_for_bbox,
    stream_3dep_lidar_dsm,
)
from .nrcan import (
    NRCAN_DEM_PRESETS,
    NRCAN_STAC_SEARCH_URL,
    is_canada_dem_source,
    is_canada_dsm_source,
    load_nrcan_dem,
    search_nrcan_stac_assets,
    stream_nrcan_elevation_grid,
    utm_bounds_to_wgs84_bbox,
)
from .utm import detect_utm_crs
from .viewshed import (
    CityCandidateResult,
    analyze_city_viewshed,
    evaluate_candidate_viewshed,
    extract_dsm_peak_candidates,
    optimize_site_combinations,
)

__version__ = "1.3.1"
__all__ = [
    "BASEMAP_PRESETS",
    "BuildingFeature",
    "CityCandidateResult",
    "DEM_PRESETS",
    "DEM_UNIT_SCALES",
    "DEMProvider",
    "LoRaGISConfig",
    "NRCAN_DEM_PRESETS",
    "NRCAN_STAC_SEARCH_URL",
    "analyze_city_viewshed",
    "apply_cli_args",
    "build_pdal_dsm_pipeline",
    "detect_utm_crs",
    "evaluate_candidate_viewshed",
    "extract_dsm_peak_candidates",
    "fetch_cgndb_features",
    "fetch_osm_buildings",
    "fetch_overture_buildings",
    "is_canada_dem_source",
    "is_canada_dsm_source",
    "is_canada_province",
    "load_nrcan_dem",
    "lookup_cgndb_place",
    "lookup_geonames_place",
    "main",
    "match_ept_resources_for_bbox",
    "merge_building_datasets",
    "normalize_loc_key",
    "optimize_site_combinations",
    "parse_distance_m",
    "parse_height_value_m",
    "parse_osm_height_m",
    "parse_overture_records",
    "rasterize_buildings_onto_dem",
    "render_candidate_profiles",
    "render_path_profiles",
    "resolve_location",
    "run_analysis",
    "search_nrcan_stac_assets",
    "select_tall_structure_candidates",
    "stream_3dep_lidar_dsm",
    "stream_nrcan_elevation_grid",
    "utm_bounds_to_wgs84_bbox",
]
