# Changelog

All notable changes to `lora-gis` are documented in this file.

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
