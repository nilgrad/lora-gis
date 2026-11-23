# CLI & JSON Configuration Reference

Run `python3 -m lora_gis --help` (or `lora-gis --help`) at any time to view grouped help output.

---

## CLI Options Reference

### Topology & Locations

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--config`, `-c` | Path to a JSON configuration file | None |
| `--route`, `-r` | Ordered sequence of 2+ locations forming a route | None |
| `--links`, `--link`, `-l` | Explicit `LOC1:LOC2` point-to-point link pairs (`:`, `->`, `<->`) | None |
| `--candidates`, `--candidate-relays` | Explicit candidate relay locations (`slug` or `name=lat,lon`) evaluated alongside the grid search or city ranking | None |
| `--auto-candidates` | Auto-select top `N` tallest structures from `--buildings` as candidate relays in route/link mode | `0` |
| `--min-building-height` | Minimum structure height for `--auto-candidates` and city filtering (`m` or `ft`) | `15m` |
| `--state` | Default 2-letter US state code for USGS GeoNames lookups | None |

### Antenna & Relay Heights

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--height`, `-H` | Override antenna height per location (`LOC=30ft` or `LOC=10m`) | None |
| `--observer-height` | Default endpoint antenna height (`ft` or `m`) | `33ft` (`10.0 m`) |
| `--repeater-height` | Default hub repeater height in multi-leg routes (`ft` or `m`) | `30ft` (`9.14 m`) |
| `--relay-height` | Intermediate candidate relay height (`ft` or `m`) | `60ft` (`18.3 m`) |
| `--candidate-height` | Mount height override for explicit/auto candidate relays (`ft` or `m`) | Predefined height, `10ft` (auto-rooftop), or `--relay-height` |

### RF & Grid Search

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--hops` | Maximum intermediate relays per link (`1` or `2`) | `2` (single link), `1` (multi-link) |
| `--freq-mhz`, `--freq` | LoRa operating frequency in MHz (`915.0`, `868.0`, `433.0`) | `915.0` |
| `--min-fresnel` | Target 1st Fresnel Zone ($F_1$) clearance ratio | `0.60` (`60%`) |
| `--grid-step` | Starting coarse search grid step in meters | `500.0` |
| `--min-grid-step` | Finest search grid step in meters | `150.0` |

### Elevation, Surface & DSM

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--dem` | DEM preset (`usgs-3dep`, `usgs-3dep-dsm`, `ny-gis`) or custom ArcGIS ImageServer URL | `usgs-3dep` |
| `--dem-file` | Local georeferenced GeoTIFF DEM/DSM file path | None |
| `--dsm-file` | Optional separate local georeferenced DSM GeoTIFF (buildings/trees) overlaid for path obstructions | None |
| `--dem-units` | Vertical elevation units of the DEM/DSM source (`m`, `ft`, `us-ft`) | `m` |
| `--surface-mode` | Surface sampling mode: `dem` (bare-earth bilinear) or `dsm` (nearest-neighbor + dense urban sampling) | `dem` |
| `--buildings` | Building overlay source: `none`, `osm` (Overpass), `overture` (Overture GeoParquet), or `hybrid` (Overture + OSM names/towers) | `none` (`osm` in `--city` without local raster) |
| `--default-building-height` | Fallback height for untagged buildings (`m` or `ft`) | `6m` |
| `--overpass-url` | Custom Overpass API interpreter URL for `--buildings osm` / `hybrid` | Public Overpass mirrors |
| `--lidar-ept` | Stream 1-2 m USGS 3DEP LiDAR DSM (buildings + tree canopy) on the fly via optional PDAL backend | `False` |
| `--lidar-resolution` | Target pixel resolution in meters for `--lidar-ept` DSM rasterization | `2.0` |
| `--ept-url` | Explicit Entwine `ept.json` URL for `--lidar-ept` (skips USGS index lookup) | Auto from USGS index |
| `--sample-step` | Sightline ray sample spacing in meters | `5.0` (DSM) / `25.0` (DEM) |
| `--rooftop-margin` | Near-field exclusion radius around endpoints in DSM mode (`m` or `ft`) | `12m` (DSM) / `0m` (DEM) |
| `--crs` | Explicit metric EPSG code (auto-detected UTM zone if omitted) | Auto UTM |

### City Viewshed Mode

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--city` | Center place or `name=lat,lon` for city rooftop ranking & viewshed coverage mode | None |
| `--radius` | Study radius around `--city` (`km`, `mi`, `m`, or `ft`) | `3km` |
| `--top` | Number of top-ranked rooftop structures shown in the report & map | `10` |
| `--rx-height` | Target receiver antenna height AGL across the city (`ft` or `m`) | `6ft` (`1.83 m`) |
| `--mast-height` | Antenna mast height above candidate rooftops (`ft` or `m`) | `10ft` (`3.05 m`) |
| `--max-sites` | Maximum candidate structures evaluated before ranking `--top N` | `25` |
| `--viewshed-grid` | Cartesian target grid samples per axis for viewshed scoring | `61` |

### Map & Output

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--basemap` | Map backdrop preset (`topo`, `osm`, `satellite`) or custom QGIS XYZ/WMS URI | `topo` (`osm` in `--city`) |
| `--output-dir`, `-o` | Output directory for `YYYY-MM-DD_HH-MM-SS/map.png` & `report.md` | `results` |
| `--title` | Report title prefix | `LoRa-GIS` |

---

## JSON Configuration Schema (`--config`)

All major CLI options can be saved in a JSON file. CLI flags passed on the command line override values from the JSON file.

### Unit Strings

- **Height strings**: `"30ft"`, `"30 feet"`, `"30'"`, `"10m"`, `"10 meters"`, or a bare number in meters (`10.0`).
- **Distance strings** (`radius`): `"3km"`, `"2mi"`, `"2500m"`, `"5000ft"`, or a bare number in meters (`3000.0`).

### Example Terrain & Mesh Config

```json
{
  "title": "HudsonValleyMesh",
  "default_state": "NY",
  "freq_mhz": 915.0,
  "min_fresnel_clearance": 0.60,
  "observer_height": "33ft",
  "repeater_height": "30ft",
  "relay_height": "60ft",
  "candidate_height": "30ft",
  "dem_source": "usgs-3dep",
  "basemap": "topo",
  "output_dir": "results",
  "locations": {
    "beacon":    { "name": "Beacon",    "lat": 41.5048, "lon": -73.9696, "height": "33ft" },
    "new-paltz": { "name": "New Paltz", "lat": 41.7476, "lon": -74.0868, "height": "30ft" },
    "ridge-1":   { "name": "Ridge 1",   "lat": 41.6100, "lon": -73.9900, "height_m": 12.0 }
  },
  "route": ["beacon", "new-paltz"],
  "candidate_relays": ["ridge-1"]
}
```

### Example City Viewshed Config

```json
{
  "title": "SalinaCityMesh",
  "city": "Salina, KS",
  "radius": "3km",
  "top": 10,
  "rx_height": "6ft",
  "mast_height": "10ft",
  "max_sites": 25,
  "viewshed_grid": 61,
  "buildings": "osm",
  "default_building_height": "6m",
  "min_building_height": "15m",
  "rooftop_margin": "12m",
  "basemap": "osm"
}
```

Additional supported JSON keys: `"links"` (array of `[loc1, loc2]` pairs), `"dem_file"`, `"dsm_file"`, `"dem_units"`, `"surface_mode"`, `"overpass_url"`, `"lidar_ept"`, `"lidar_resolution_m"`, `"ept_url"`, `"auto_candidates"`, `"sample_step_m"`, `"initial_grid_step_m"`, `"min_grid_step_m"`, `"crs_epsg"`.
