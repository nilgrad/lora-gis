# City Viewshed & Urban DSM Analysis

In mountainous regions, bare-earth terrain (DEM) dominates line-of-sight. In flat cities and towns (such as across the Great Plains and Midwest), **buildings, water towers, grain elevators, and tree canopy** are what determine coverage.

`lora-gis` supports four progressive ways to model urban surfaces and cherry-pick optimal node placements.

---

## Choosing a Surface Data Source

| Mode / Flag | Includes Buildings | Includes Trees | Extra Deps | Best For |
| :--- | :---: | :---: | :--- | :--- |
| Default bare-earth DEM (`--dem usgs-3dep` / `--dem canada-hrdem`) | No | No | None | Mountain & rural regional routing |
| `--buildings osm` | Yes (OSM tags + heuristics) | No | None | Zero-setup city rooftop ranking, named buildings, water towers, and grain silos |
| `--buildings overture` / `hybrid` | Yes (ML heights + OSM names/towers) | No | `overture` extra | Cities where OSM lacks explicit `height` / `building:levels` tags |
| Local DSM GeoTIFF (`--dem-file` / `--dsm-file`) | Yes (exact rooflines) | Yes | None (GDAL bundled with PyQGIS) | Highest accuracy when you have regional LiDAR DSM tiles |
| `--dem canada-hrdem-dsm` (NRCan CanElevation) | Yes (1 m LiDAR rooflines) | Yes | None (GDAL `/vsicurl/`) | Automated 1 m Canadian LiDAR DTM + DSM (with automatic `hrdem-mosaic-2m` / `mrdem-30` gap-fill) |
| `--lidar-ept` / `--dem usgs-3dep-dsm` | Yes (exact rooflines) | Yes | `lidar` (`pdal`) extra | Automated 1-2 m US LiDAR DSMs without manual downloads |

---

## 1. City Rooftop Ranking & Viewshed Coverage (`--city`)

Use `--city` to answer: *"Which rooftops, water towers, or grain elevators in our city cover the highest percentage of town, and what is the best 2-site or 3-site combination?"*

```bash
# Rank the top 10 rooftops/towers across a 3 km radius for 6 ft handheld receivers
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 3km \
  --top 10 \
  --rx-height 6ft \
  --mast-height 10ft
```

### How `--city` Mode Works

1. **Smart Urban Defaults**: Unless explicitly overridden, `--city` automatically switches the basemap to `osm` (street map) and enables `--buildings osm` when no local DEM/DSM file or `--lidar-ept` flag is supplied.
2. **Candidate Extraction**: Pulls up to `--max-sites` (default `25`) tallest buildings, water towers, grain silos, and communications towers inside the study radius (deduplicated by `150 m` so adjacent wings of one complex do not take multiple slots), plus any explicit `--candidates` you pass. If you provide a local DSM GeoTIFF without `--buildings`, `lora-gis` extracts prominent rooftop/tower local maxima directly from the DSM raster.
3. **Vectorized Viewshed Scoring**: Evaluates every candidate site against a shared Cartesian target grid (`--viewshed-grid 61`, ~2,900 points inside the study circle) at `--rx-height` AGL (e.g., `6ft` handheld or `25ft` home roof) with `--mast-height` above the host rooftop (`10ft` default), checking both optical LOS and `>= 60%` 1st Fresnel Zone ($F_1$) clearance with 4/3 Earth curvature.
4. **Greedy Multi-Site Set-Cover**: Computes the highest-coverage **1-site**, **2-site**, and **3-site** combinations, reporting marginal and cumulative $F_1$ and LOS coverage gains.

### City Outputs

- `map.png`: Street or satellite map showing a semi-transparent coverage heatmap for the `#1` site (emerald green = `>= 60% F1` clear, amber = optical LOS clear), dashed study radius circle, height-differentiated building footprints, and numbered pins (`#1` star + `#2..#N` circles).
- `report.md`:
  - **Section 1: City Study Overview** (center, radius, target grid spacing, frequency, mast/RX heights, surface model, building stats).
  - **Section 2: Top Ranked Rooftops & Tall Structures** (rank, structure name, type & street address, coordinates, ground elevation, structure height, mast height, `>= 60% F1` coverage %, optical LOS %, max clear range).
  - **Section 3: Optimal Multi-Site Combinations** (1-site, 2-site, and 3-site greedy set-cover with marginal $F_1$ gain).

See a full real-world city viewshed report and heatmap for **Salina, KS** (`12,281` OSM structures over USGS 3DEP elevation) in [`examples/salina-ks-city-viewshed/report.md`](../examples/salina-ks-city-viewshed/report.md).

### Testing Specific Target Buildings in `--city` Mode

You can combine `--city` with `--candidates` to force specific rooftops you already have access to into the ranking table alongside discovered tall structures:

```bash
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 3km \
  --candidates "friends-roof=38.8412,-97.6110" "water-dept=38.8465,-97.6042" \
  --height friends-roof=15ft
```

---

## 2. Building-Aware Point-to-Point Routes (`--buildings osm`)

Building overlays also work in standard `--route` and `--links` workflows. Add `--auto-candidates N` to automatically test the top `N` tallest structures in the study area as candidate relays:

```bash
# Stream USGS 3DEP DEM + OSM buildings/towers and test the top 5 tall structures as relays
python3 -m lora_gis \
  --route west=38.840,-97.625 east=38.840,-97.595 \
  --buildings osm \
  --auto-candidates 5 \
  --min-building-height 50ft \
  --basemap osm
```

### How OSM Building Heights Are Resolved

1. Explicit `height`, `est_height`, or `building:height` tags (supports meters, feet, feet'inches", and semicolon multi-values).
2. `building:levels * 3.5 m` (plus `roof:levels * 2.0 m` when tagged).
3. Structure-type defaults for untagged tall structures (`communications_tower`: `45 m`, `water_tower`: `35 m`, `tower`/`chimney`: `30 m`, `silo`/`mast`: `25 m`, `hospital`/`hotel`/`office`/`apartments`: `12 m`, `industrial`/`warehouse`/`commercial`: `8 m`).
4. Fallback `--default-building-height` (default `6 m` / ~20 ft).

---

## 3. Local Georeferenced DSM GeoTIFFs & Regional ImageServers

If you have local LiDAR DSM GeoTIFFs (for example from Kansas DASC, a county GIS portal, or USGS 3DEP) or a regional ArcGIS DSM ImageServer, pass them directly. `lora-gis` uses GDAL to read CRS, geotransform, extent, and NoData values, reprojecting and clipping automatically to your UTM zone.

```bash
# Single local DSM GeoTIFF stored in feet (common for US state GIS portals)
python3 -m lora_gis \
  --city salina=38.8403,-97.6114 \
  --radius 2mi \
  --dem-file salina_dsm_ft.tif \
  --dem-units ft \
  --surface-mode dsm \
  --basemap satellite

# Bare-earth DEM + separate local DSM GeoTIFF (preserves separate ground vs. building elevations)
python3 -m lora_gis \
  --route west=38.840,-97.625 east=38.840,-97.595 \
  --dem-file ground_dem.tif \
  --dsm-file buildings_dsm.tif \
  --rooftop-margin 12m \
  --sample-step 4.0 \
  --basemap osm
```

### Key DSM Sampling Controls

- `--surface-mode dsm`: Switches raster interpolation to **nearest-neighbor** (preserving sharp building walls and rooflines instead of bilinear smoothing) and densifies sightline sampling from `25 m` to `5 m`.
- `--dem-units {m,ft,us-ft}`: Scales vertical elevation values to meters automatically.
- `--rooftop-margin` (default `12m` in DSM mode): Excludes the immediate host-building roofline radius around an endpoint so a parapet or HVAC unit on your own roof does not trigger false self-blockage.
- `--sample-step`: Fine-tunes ray sample spacing in meters (default `5.0 m` in DSM mode).

---

## 4. Optional High-Completeness Backends

### Overture Maps & Hybrid Mode (`--buildings overture` / `hybrid`)

In many small and mid-sized US cities, OpenStreetMap has footprints without explicit height tags. Overture Maps merges OSM with ML-derived and LiDAR-derived building heights in cloud GeoParquet.

- `--buildings overture`: Streams Overture Maps buildings directly for your bounding box.
- `--buildings hybrid`: Streams Overture Maps buildings **and** merges them with OpenStreetMap so you get Overture's ML height completeness alongside OSM's building names, street addresses, and standalone `man_made` structures (water towers, grain silos, communications towers).

```bash
# Requires: pip install -e ".[overture]"
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 3km \
  --buildings hybrid \
  --top 10
```

### Canada HRDEM 1 m LiDAR DSM Streaming (`--dem canada-hrdem-dsm`)

Across Canada, Natural Resources Canada's **CanElevation Series (HRDEM)** distributes both bare-earth **DTM** and full **DSM** (buildings + tree canopy) as Cloud-Optimized GeoTIFFs via a public STAC API. `lora-gis` streams them directly via GDAL `/vsicurl/` with **no extra dependencies** (no PDAL required):

```bash
# Stream NRCan 1 m HRDEM DTM + DSM with OSM building labels/addresses for rooftop ranking
python3 -m lora_gis \
  --city "Ottawa, ON" \
  --dem canada-hrdem-dsm \
  --radius 2km \
  --top 10

# Pure DSM peak extraction (skips Overpass building query)
python3 -m lora_gis \
  --city downtown=45.4215,-75.6972 \
  --dem canada-hrdem-dsm \
  --buildings none \
  --radius 2km
```

- Automatically stitches multi-tile bounding boxes via GDAL VRT and backfills any LiDAR NoData gaps from `hrdem-mosaic-2m` and nationwide `mrdem-30` (30 m).
- Caches warped elevation arrays locally in your temp directory so repeat runs over the same area are fast.

### USGS 3DEP LiDAR EPT Streaming (`--lidar-ept` / `--dem usgs-3dep-dsm`)

To model **both exact rooflines and tree canopy** anywhere in the US without manually downloading LiDAR tiles, stream USGS 3DEP Entwine Point Tiles (EPT) on the fly via PDAL:

```bash
# Requires: conda install -c conda-forge python-pdal  (or pip install -e ".[lidar]")
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 2km \
  --lidar-ept \
  --lidar-resolution 2.0 \
  --basemap satellite

# Shorthand preset equivalent
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 2km \
  --dem usgs-3dep-dsm
```

- Automatically discovers the newest intersecting USGS 3DEP LiDAR project from the public EPT index (`resources.geojson`, cached locally in your temp directory).
- Filters ASPRS noise classes (7 and 18), reprojects to UTM, and caches the resulting max-Z first-return DSM GeoTIFF so repeat runs over the same area are instant.
- Pass `--ept-url <url>` to target a specific `ept.json` dataset directly.
- Keep study areas modest (around `<= 6 km x 6 km` / `radius <= 3 km`) when streaming LiDAR point clouds.
