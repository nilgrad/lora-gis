# lora-gis

[![Unit Tests](https://github.com/nilgrad/lora-gis/actions/workflows/tests.yml/badge.svg)](https://github.com/nilgrad/lora-gis/actions/workflows/tests.yml)

![LoRa-GIS](assets/title.svg)

A **PyQGIS** Line-of-Sight (LOS) and **LoRa / MeshCore RF repeater pathfinder** and automated topographic map renderer. Designed to route off-grid radio links across mountainous terrain using high-resolution Digital Elevation Models (DEMs).

- **1-Hop & 2-Hop Repeater Discovery**: Scans candidate grids from coarse (`500 m`) down to fine (`150 m`) resolution to discover both **single-repeater (`1-hop`)** and **two-repeater (`2-hop`)** sightline paths when direct line-of-sight is blocked by terrain.
- **Explicit Candidate Relay Evaluation**: Test specific known coordinates or properties (`--candidates`) alongside the grid search, with leg-by-leg clearance/Fresnel metrics, candidate-to-candidate 2-hop pairs, hybrid (candidate + grid) 2-hop combinations, and dedicated map markers.
- **Topology-Based Multi-Leg & Mesh Routing**: Define sequential routes (`--route`), explicit point-to-point mesh links (`--links`), or JSON topology configs (`--config`), with automatic repeater mount-height sensitivity tables (`30 ft` to `90 ft`) for intermediate hub nodes.
- **LoRa RF Propagation Modeling**: Evaluates **1st Fresnel Zone ($F_1$) clearance** at `915 MHz` (US915), `868 MHz` (EU868), or `433 MHz`, **4/3 effective Earth curvature + atmospheric refraction**, minimum terrain clearance, and **Free-Space Path Loss (FSPL in dB)** along every hop.
- **Multi-Source DEM & Automatic UTM Projection**: Automatically detects the local metric UTM zone (`EPSG:269xx` / `326xx` / `327xx`) and streams 32-bit float elevation grids from **USGS 3DEP** (nationwide US), state GIS servers (`ny-gis`), custom ArcGIS ImageServers, or local GeoTIFF DEM files.
- **Automated Topographic Cartography & Markdown Reports**: Exports both a high-resolution (`1920×1080`) PNG topographic map and a detailed Markdown RF report (`results/YYYY-MM-DD_HH-MM-SS/`) containing link metrics, node elevations, hop-by-hop Fresnel clearances, FSPL, top candidate relay sites, and surrounding USGS GeoNames mountain summits and towns.

---

## Requirements & Installation

- **Python 3** (`>= 3.10`)
- **QGIS & PyQGIS** (`qgis.core`)
- **PyQt5** (`PyQt5.QtCore`, `PyQt5.QtGui`, `PyQt5.QtWidgets`)
- **NumPy** (`numpy`)
- **Pillow** (`PIL`)

### Option 1: Cross-Platform via Conda / Mamba (macOS, Windows, Linux)

The easiest way to install `qgis` and `PyQGIS` across **macOS (Apple Silicon & Intel)**, **Windows**, and **Linux** is via [`conda-forge`](https://conda-forge.org/) (using [Miniforge](https://github.com/conda-forge/miniforge) or [Miniconda](https://docs.anaconda.com/miniconda/)):

```bash
conda create -n lora-gis -c conda-forge python=3.11 qgis numpy pillow
conda activate lora-gis
pip install --no-build-isolation -e .
```

### Option 2: Native OS Packages

#### Linux

```bash
# Debian / Ubuntu
sudo apt install qgis python3-qgis python3-pyqt5 python3-numpy python3-pil

# Fedora / RHEL
sudo dnf install qgis python3-qgis python3-qt5 python3-numpy python3-pillow

# Arch Linux
sudo pacman -S qgis python-pyqt5 python-numpy python-pillow

# Install lora-gis
pip install --no-build-isolation --user -e .
```

#### macOS (Official `QGIS.app` or Homebrew)

1. Install QGIS via Homebrew (`brew install --cask qgis`) or download the official macOS disk image from [qgis.org](https://qgis.org/download/).
2. Install and run `lora-gis` using the Python environment bundled inside `QGIS.app`:

```bash
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install --no-build-isolation -e .
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m lora_gis --route "Boulder, CO" "Nederland, CO"
```

#### Windows (OSGeo4W / Standalone QGIS Installer)

1. Install QGIS from [qgis.org](https://qgis.org/download/).
2. Open the **OSGeo4W Shell** from the Start Menu (which pre-configures `python` and `QGIS_PREFIX_PATH` for PyQGIS) and run:

```bat
python -m pip install --no-build-isolation -e .
python -m lora_gis --route "Boulder, CO" "Nederland, CO"
```

---

## CLI Usage

### 1. Point-to-Point & Multi-Leg Routes (`--route`)

Pass town names (resolved automatically via USGS GeoNames) or inline `name=lat,lon` coordinates:

```bash
# Nationwide US lookup with state code
python3 -m lora_gis --route "Beacon, NY" "New Paltz, NY"

# Colorado Front Range example with custom relay height
python3 -m lora_gis --route "Boulder, CO" "Nederland, CO" --relay-height 45ft

# Inline coordinates
python3 -m lora_gis --route valley_node=41.504,-73.969 ridge_node=41.747,-74.087
```

### 2. Branching & Mesh Topologies (`--links`)

Pass explicit `node1:node2` pairs to evaluate branching mesh topologies:

```bash
python3 -m lora_gis --state NY \
  --links beacon:new-paltz new-paltz:kingston \
  --height new-paltz=45ft
```

### 3. JSON Configuration File (`--config`)

Create a `network.json` file to store reusable locations, heights, and RF settings:

```json
{
  "title": "HudsonValleyMesh",
  "default_state": "NY",
  "freq_mhz": 915.0,
  "relay_height": "60ft",
  "dem_source": "usgs-3dep",
  "locations": {
    "beacon":    { "name": "Beacon",    "lat": 41.5048, "lon": -73.9696, "height": "33ft" },
    "new-paltz": { "name": "New Paltz", "lat": 41.7476, "lon": -74.0868, "height": "30ft" }
  },
  "route": ["beacon", "new-paltz"]
}
```

Run it with:

```bash
python3 -m lora_gis --config network.json
```

### 4. Explicit Candidate Relay Evaluation (`--candidates`)

Pass known relay candidate locations (catalog slugs or inline `name=lat,lon` coordinates) to evaluate them directly at their exact coordinates alongside the grid search:

```bash
python3 -m lora_gis --state NY \
  --route "Willowemoc, NY" "Livingston Manor, NY" \
  --hops 2 \
  --candidates site1=41.8926,-74.7838 site2=41.8905,-74.6927 \
  --candidate-height 30ft
```

Explicit candidates can also be configured in JSON via `"candidate_relays"` and `"candidate_height"`. The DEM bounding box and map extent automatically expand to cover all candidates, and the report includes leg-by-leg clearance tables, hub height sensitivity, 2-hop candidate pairs, and hybrid (candidate + grid) 2-hop solutions.

### 5. Urban Buildings & Local DSM Analysis (`--buildings osm`, `--surface-mode dsm`)

Overlay OpenStreetMap buildings, water towers, grain silos, and communications towers directly onto the USGS 3DEP bare-earth DEM (zero manual downloads) and optionally auto-evaluate the tallest structures as candidate relays:

```bash
# Stream USGS 3DEP DEM + OpenStreetMap buildings/towers and test top 5 tall structures
python3 -m lora_gis \
  --route west=38.840,-97.625 east=38.840,-97.595 \
  --buildings osm \
  --auto-candidates 5 \
  --basemap osm
```

You can also use a local georeferenced Digital Surface Model (DSM) GeoTIFF or regional DSM ImageServer:

```bash
# Single local DSM GeoTIFF stored in feet over OpenStreetMap
python3 -m lora_gis \
  --route west=38.840,-97.625 east=38.840,-97.595 \
  --dem-file salina_dsm_ft.tif \
  --dem-units ft \
  --surface-mode dsm \
  --basemap osm

# Bare-earth DEM + separate local DSM GeoTIFF with satellite imagery
python3 -m lora_gis \
  --route west=38.840,-97.625 east=38.840,-97.595 \
  --dem-file ground_dem.tif \
  --dsm-file buildings_dsm.tif \
  --rooftop-margin 12m \
  --basemap satellite
```

### 6. City Rooftop Ranking & Viewshed Coverage (`--city`)

In flat or urban areas, use `--city` to automatically rank the tallest buildings, water towers, and grain silos by what percentage of the city they can cover with clear Line-of-Sight and 60% 1st Fresnel Zone clearance, plus greedy 2-site and 3-site combination recommendations:

```bash
# Rank the top 10 rooftops/towers across a 3 km radius for 6 ft handheld receivers
python3 -m lora_gis \
  --city "Salina, KS" \
  --radius 3km \
  --top 10 \
  --rx-height 6ft \
  --mast-height 10ft

# Use a local LiDAR DSM GeoTIFF with satellite imagery instead of OSM buildings
python3 -m lora_gis \
  --city salina=38.8403,-97.6114 \
  --radius 2mi \
  --dem-file salina_dsm_ft.tif \
  --dem-units ft \
  --basemap satellite
```

### CLI Options Reference

#### Topology & Locations

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--config`, `-c` | Path to a JSON configuration file | None |
| `--route`, `-r` | Ordered sequence of 2+ locations forming a route | None |
| `--links`, `-l` | Explicit `LOC1:LOC2` point-to-point link pairs | None |
| `--candidates`, `--candidate-relays` | Explicit candidate relay locations (`slug` or `name=lat,lon`) evaluated alongside the grid search | None |
| `--auto-candidates` | Auto-select top `N` tallest structures from `--buildings` as candidate relays | `0` |
| `--min-building-height` | Minimum structure height for `--auto-candidates` (`m` or `ft`) | `15m` |
| `--state` | Default 2-letter US state code for USGS GeoNames lookups | None |

#### Antenna & Relay Heights

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--height`, `-H` | Override antenna height per location (`LOC=30ft` or `LOC=10m`) | None |
| `--observer-height` | Default endpoint antenna height (`ft` or `m`) | `33ft` (`10.0 m`) |
| `--repeater-height` | Default hub repeater height in multi-leg routes (`ft` or `m`) | `30ft` (`9.14 m`) |
| `--relay-height` | Intermediate candidate relay height (`ft` or `m`) | `60ft` (`18.3 m`) |
| `--candidate-height` | Mount height override for explicit/auto candidate relays (`ft` or `m`) | Predefined height, `10ft` (auto-rooftop), or `--relay-height` |

#### RF & Grid Search

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--hops` | Maximum intermediate relays per link (`1` or `2`) | `2` (single link), `1` (multi-link) |
| `--freq-mhz`, `--freq` | LoRa operating frequency in MHz (`915.0`, `868.0`, `433.0`) | `915.0` |
| `--min-fresnel` | Target 1st Fresnel Zone ($F_1$) clearance ratio | `0.60` (`60%`) |
| `--grid-step` | Starting coarse search grid step in meters | `500.0` |
| `--min-grid-step` | Finest search grid step in meters | `150.0` |

#### Elevation, Surface & DSM

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--dem` | DEM preset (`usgs-3dep`, `ny-gis`) or ArcGIS ImageServer URL | `usgs-3dep` |
| `--dem-file` | Local georeferenced GeoTIFF DEM/DSM file path | None |
| `--dsm-file` | Optional separate local georeferenced DSM GeoTIFF (buildings/trees) overlaid for path obstructions | None |
| `--dem-units` | Vertical elevation units of the DEM/DSM source (`m`, `ft`, `us-ft`) | `m` |
| `--surface-mode` | Surface sampling mode: `dem` (bare-earth bilinear) or `dsm` (nearest-neighbor + dense urban sampling) | `dem` |
| `--buildings` | Building & tall-structure overlay source (`none` or `osm` via Overpass API) | `none` |
| `--default-building-height` | Fallback height for untagged OSM buildings (`m` or `ft`) | `6m` |
| `--overpass-url` | Custom Overpass API interpreter URL for `--buildings osm` | Public Overpass mirrors |
| `--sample-step` | Sightline ray sample spacing in meters | `5.0` (DSM) / `25.0` (DEM) |
| `--rooftop-margin` | Near-field exclusion radius around endpoints in DSM mode (`m` or `ft`) | `12m` (DSM) / `0m` (DEM) |
| `--crs` | Explicit metric EPSG code (auto-detected UTM zone if omitted) | Auto UTM |

#### City Viewshed Mode

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--city` | Center place or `name=lat,lon` for city rooftop ranking & viewshed coverage mode | None |
| `--radius` | Study radius around `--city` (`km`, `mi`, `m`, or `ft`) | `3km` |
| `--top` | Number of top-ranked rooftop structures shown in the report & map | `10` |
| `--rx-height` | Target receiver antenna height AGL across the city (`ft` or `m`) | `6ft` (`1.83 m`) |
| `--mast-height` | Antenna mast height above candidate rooftops (`ft` or `m`) | `10ft` (`3.05 m`) |
| `--max-sites` | Maximum candidate structures evaluated before ranking `--top N` | `25` |
| `--viewshed-grid` | Cartesian target grid samples per axis for viewshed scoring | `61` |

#### Map & Output

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--basemap` | Map backdrop preset (`topo`, `osm`, `satellite`) or custom QGIS XYZ/WMS URI | `topo` |
| `--output-dir`, `-o` | Output directory for `YYYY-MM-DD_HH-MM-SS/map.png` & `report.md` | `results` |
| `--title` | Report title prefix | `LoRa-GIS` |

---

## Using `lora-gis` as a Python Library

You can import `lora_gis` directly in project-specific scripts while retaining full CLI flag support:

```python
from lora_gis import LoRaGISConfig, main

config = LoRaGISConfig(
    title="MyRegionalMesh",
    default_state="NY",
    dem_source="ny-gis",
    locations={
        "site-a": {"name": "Site A", "lat": 41.5048, "lon": -73.9696, "height_m": 10.0},
        "site-b": {"name": "Site B", "lat": 41.7476, "lon": -74.0868, "height_m": 10.0},
    },
    default_route=["site-a", "site-b"],
)

if __name__ == "__main__":
    main(config)
```

---

## Sample Output (`Roscoe ↔ Livingston Manor ↔ Liberty`)

Generated with:

```bash
python3 -m lora_gis --state NY --dem ny-gis --route "Roscoe" "Livingston Manor" "Liberty" --hops 2 --candidates "shandelee-ridge=41.8804,-74.8890" "ferndale-ridge=41.7665,-74.6997" "willowemoc-ridge=41.9056,-74.6774"
```

- **Full RF Analysis Report, Topographic Map & Terrain Profiles**: [`examples/roscoe-livingston-manor-liberty/report.md`](examples/roscoe-livingston-manor-liberty/report.md)
  - **Leg 1 (`Roscoe ↔ Livingston Manor`, `7.95 km`)**: Direct sightline blocked by terrain (`-185.3 m` deficit); solved by a **2-Hop Repeater Pair** (`7.98 km` total path, `69%` worst-case $F_1$ clearance) or a **Hybrid 2-Hop** pairing **Shandelee Ridge** with a grid relay (`14.77 km`, `56%` $F_1$).
  - **Leg 2 (`Livingston Manor ↔ Liberty`, `12.93 km`)**: Direct sightline blocked by terrain (`-188.3 m` deficit); solved by a **2-Hop Repeater Pair** (`13.02 km` total path, `70%` worst-case $F_1$ clearance) or a **Hybrid 2-Hop** pairing a grid relay with **Ferndale Ridge** (`23.90 km`, `58%` $F_1$).
  - **Explicit Candidate Relays & Terrain Blockage (`Shandelee Ridge`, `Ferndale Ridge`, `Willowemoc Ridge`)**: Evaluates three spaced-out ridge sites with cross-sectional terrain profiles ([`candidate_profiles.png`](examples/roscoe-livingston-manor-liberty/candidate_profiles.png)), green clear sightlines, and red `✕` ridge blockage markers on [`map.png`](examples/roscoe-livingston-manor-liberty/map.png). **Shandelee Ridge** (`655 m / 2,148 ft`) has an unblocked leg to `Roscoe` (`87%` $F_1$, `+11.1 m`) and **Ferndale Ridge** (`441 m / 1,446 ft`) has an unblocked leg to `Liberty` (`61%` $F_1$, `+5.0 m`), while **Willowemoc Ridge** (`642 m`) is blocked across all legs (`-139.0 m` / `-107.9 m` / `-116.5 m`).

---

## Acknowledgments

Special thanks to [@tectosage](https://github.com/tectosage) for contributions to the original implementation and code review.

---

## License

Released under the [MIT License](LICENSE).
