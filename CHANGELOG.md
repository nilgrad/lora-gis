# Changelog

All notable changes to `lora-gis` are documented in this file.

## [1.3.0] - 2026-11-24

### Added
- **Canada Elevation & 1 m LiDAR DSM Support (NRCan CanElevation Series)**:
  - Added STAC + GDAL `/vsicurl/` Cloud-Optimized GeoTIFF streaming backend (`lora_gis/nrcan.py`) with zero new Python dependencies (no PDAL required for 1 m Canadian LiDAR DSMs).
  - Added `--dem` presets `canada-hrdem` (1 m bare-earth DTM), `canada-hrdem-dsm` (1 m DTM + 1 m LiDAR DSM including buildings and tree canopy), `canada-mrdem` (30 m nationwide DTM), and `canada-mrdem-dsm` (plus `nrcan-*` aliases).
  - Added multi-tile GDAL VRT stitching, local temp-dir caching of warped grids, and automatic NoData (`-32767.0`) gap-filling across `hrdem-mosaic-1m`, `hrdem-mosaic-2m`, and nationwide `mrdem-30`.
- **Canadian Place & Terrain Feature Lookups (NRCan CGNDB)**:
  - Added `lookup_cgndb_place()` and `fetch_cgndb_features()` against NRCan's Canadian Geographical Names Data Base (CGNDB) API, mapping all 13 Canadian province/territory codes (`AB, BC, MB, NB, NL, NS, NT, NU, ON, PE, QC, SK, YT`) to Statistics Canada SGC codes.
  - Added `--province` CLI alias alongside `--state` (and `"default_province"` in JSON configs), automatic routing of Canadian province codes to CGNDB, and smart Canadian DEM/basemap defaults when not explicitly overridden.
- **Basemaps, Northern UTM & Offline Tests**:
  - Added `world-topo` (Esri World Topographic) and `canada-topo` (NRCan CBMT WMS) basemap presets.
  - Expanded NAD83 UTM (`EPSG:269xx`) auto-detection to zones `7N..22N` (`14°N..84°N`) to cover Yukon, coastal/northern BC, and northern Canada.
  - Added 13 offline unit and headless PyQGIS tests in `tests/test_canada_nrcan.py` (81 total tests).

### Fixed
- **Non-ArcGIS Elevation Lookups & Map Peak Labels**:
  - Guarded `DEMProvider.fetch_elevations()` so local GeoTIFF and NRCan backends do not attempt ArcGIS `getSamples` requests for out-of-bounds points.
  - Omitted `-9999 m` sentinel elevation text on map peak labels and report entries outside the cached DEM grid, and filtered CGNDB features strictly to the rendered map extent.

## [1.2.0] - 2026-11-23

### Added
- **City Rooftop Ranking & Viewshed Coverage Mode (`--city`)**:
  - Added `--city`, `--radius`, `--top`, `--rx-height`, `--mast-height`, `--max-sites`, and `--viewshed-grid` (plus matching JSON keys) to rank the top buildings, water towers, grain silos, and DSM peaks across a city radius by optical LOS and `>= 60%` 1st Fresnel Zone ($F_1$) area coverage.
  - Added greedy multi-site set-cover optimization (`optimize_site_combinations`) to recommend the highest-coverage 1-site, 2-site, and 3-site rooftop combinations with marginal coverage gains.
  - Added urban viewshed cartography (`map.png` with georeferenced RGBA coverage heatmap, study radius ring, height-differentiated building footprints, and numbered candidate pins) and dedicated city Markdown reports (`report.md`).
- **OpenStreetMap Building & Tall-Structure Overlay (`--buildings osm`)**:
  - Added zero-dependency Overpass API client (`lora_gis/buildings.py`) querying buildings, water towers, grain silos, towers, and masts with height parsing (`height`, `building:levels`, structure defaults, `--default-building-height`) and street address metadata.
  - Added fast Pillow float32 surface rasterization (`dsm_surface = dem_ground + building_heights`) and `--auto-candidates N` to automatically test the top tall structures as candidate relays in route/link mode.
- **Georeferenced DSM GeoTIFFs, Vertical Units & Urban Sampling**:
  - Upgraded local GeoTIFF loading (`--dem-file` and optional separate `--dsm-file`) to use GDAL georeferencing (CRS, geotransform, extent, NoData, and UTM reprojection).
  - Added `--dem-units {m,ft,us-ft}`, `--surface-mode {dem,dsm}` (nearest-neighbor sampling + dense `5 m` ray steps), `--sample-step`, `--rooftop-margin` (near-field host roofline exclusion), and `--basemap {topo,osm,satellite}`.
- **Optional High-Completeness Urban Backends**:
  - Added optional Overture Maps GeoParquet backend (`--buildings overture` and `--buildings hybrid` merging Overture ML heights with OSM names, addresses, and tall towers) via `pip install "lora-gis[overture]"`.
  - Added optional USGS 3DEP LiDAR EPT streaming (`--lidar-ept` / `--dem usgs-3dep-dsm`, `--lidar-resolution`, `--ept-url`) via `pdal` (`lora-gis[lidar]`) for on-the-fly 1-2 m DSMs including tree canopy.
- **Offline Unit Test Suite & GitHub Actions CI**:
  - Added 68 offline unit and headless PyQGIS integration tests under `tests/` and automated CI in `.github/workflows/tests.yml`.

### Changed
- **Grouped CLI Help & Modular Documentation**:
  - Organized `lora-gis --help` into 6 logical argument groups (`Topology & Locations`, `Antenna & Relay Heights`, `RF & Grid Search`, `Elevation, Surface & DSM`, `City Viewshed Mode`, and `Map & Output`).
  - Refactored `README.md` into a concise landing page and moved detailed guides into `docs/` (`installation.md`, `repeater-discovery.md`, `city-and-dsm-analysis.md`, `cli-reference.md`, and `python-api.md`).
- **Managed Headless PyQGIS Singleton**: Reused a process-wide headless `QgsApplication` across repeated `run_analysis()` calls in the same Python process (clearing `QgsProject` between headless runs and shutting down cleanly via `atexit`).

## [1.1.1] - 2026-11-23

### Changed
- **Candidate Sightline & Label Cartography**:
  - Rendered clear explicit candidate legs as green dashed sightlines alongside green diamond markers displaying 1-hop, 2-hop, or clear-leg status on `map.png`.
  - Disabled partial edge-clipped labels (`UsePartialCandidates = False`) and prioritized explicit candidate labels so callouts stay inside the map frame without clipping.
- **Updated Sample Output**:
  - Replaced the sample output with `examples/roscoe-livingston-manor-liberty/` (`Roscoe ↔ Livingston Manor ↔ Liberty`) evaluating three spaced-out candidate relays (`Shandelee Ridge`, `Ferndale Ridge`, `Willowemoc Ridge`) with `map.png`, `candidate_profiles.png`, `report.md`, and updated `README.md` documentation.

### Fixed
- **Duplicate Candidate Markers on Shared Hub Legs**: Deduplicated undirected `(endpoint, candidate)` sightlines and worst-blockage `✕` markers across multi-leg routes sharing an intermediate hub node.
- **ArcGIS DEM Sample Ordering**: Indexed `getSamples` responses by `locationId` in `DEMProvider.fetch_elevations` so out-of-order multi-raster responses do not shift summit elevations.

## [1.1.0] - 2026-11-19

### Added
- **Explicit Candidate Relay Evaluation (`--candidates` / `--candidate-relays`, `--candidate-height`)**:
  - Evaluate specific named locations (catalog slugs or inline `name=lat,lon`) at their exact coordinates alongside the grid-based repeater search.
  - Added `candidate_relays` and `candidate_height` configuration fields to `LoRaGISConfig` and JSON config support.
  - Automatically projects explicit candidates to UTM and expands the DEM raster bounding box and map extent to include all candidate sites.
  - Evaluates 1-hop viability (leg-by-leg clearance, 1st Fresnel zone $F_1$ %, FSPL), candidate-to-candidate 2-hop pairs, hybrid 2-hop pairs (1 explicit candidate + 1 grid relay), and hub height sensitivity tables.
- **Terrain Blockage Visualization**:
  - Added `candidate_profiles.png` cross-sectional terrain elevation profiles (`K = 4/3` Earth curvature) showing direct line-of-sight, 1st Fresnel zone envelope, red-shaded terrain obstructions, and worst-blockage callouts (in meters, feet, and km) for every candidate leg.
  - Added dotted candidate sightlines, green/purple diamond candidate markers, and red `✕` markers at the exact ridge coordinate of each leg's worst terrain blockage on `map.png`.
- **Report & Documentation Updates**:
  - Embedded `candidate_profiles.png` and added explicit candidate evaluation, hub height sensitivity, 2-hop pair, and hybrid 2-hop tables to `report.md` when candidates are specified.
  - Documented `--candidates` and `--candidate-height` usage and CLI options in `README.md`.

## [1.0.0] - 2026-11-15

### Added
- Initial release of `lora-gis`, a PyQGIS Line-of-Sight (LOS) and LoRa / MeshCore RF repeater pathfinder and topographic map renderer.
- Multi-resolution 1-hop and 2-hop repeater discovery (`500 m` down to `150 m` grid steps) with 1st Fresnel Zone ($F_1$) clearance, 4/3 effective Earth curvature, and Free-Space Path Loss (FSPL) modeling at `915 MHz`, `868 MHz`, or `433 MHz`.
- Topology-based multi-leg routes (`--route`), explicit point-to-point mesh links (`--links`), JSON configuration (`--config`), and automatic hub repeater height sensitivity sweeps (`30 ft` to `90 ft`).
- Multi-source DEM streaming (`usgs-3dep`, `ny-gis`, custom ArcGIS ImageServer URLs, or local GeoTIFF files) with automatic UTM zone detection and USGS GeoNames place/summit lookups.
- Automated `1920x1080` topographic map PNG rendering (`map.png`) and Markdown RF report export (`report.md`).
- Cross-platform installation instructions and QGIS prefix auto-detection for Linux, macOS, and Windows.
- Sample output for Livingston Manor, Liberty, and Monticello, NY.
