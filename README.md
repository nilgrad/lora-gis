# lora-gis

[![Unit Tests](https://github.com/nilgrad/lora-gis/actions/workflows/tests.yml/badge.svg)](https://github.com/nilgrad/lora-gis/actions/workflows/tests.yml)

![LoRa-GIS](assets/title.svg)

A **PyQGIS** Line-of-Sight (LOS), **LoRa / MeshCore RF repeater pathfinder**, and **city rooftop viewshed analyzer** with automated map rendering and Markdown RF reporting. Designed for both mountainous terrain routing and flat/urban building coverage planning.

## Key Features

- **1-Hop & 2-Hop Repeater Discovery**: Scans candidate grids from coarse (`500 m`) down to fine (`150 m`) resolution to find single-repeater (`1-hop`) and two-repeater (`2-hop`) paths across terrain, plus explicit candidate relay testing (`--candidates`).
- **City Rooftop Ranking & Viewshed Coverage (`--city`)**: Evaluates buildings, water towers, grain silos, and DSM peaks across a city radius, ranking the best rooftops by `% city area covered` and recommending greedy 2-site and 3-site combinations.
- **Urban Buildings & LiDAR DSM Support**: Overlays OpenStreetMap buildings (`--buildings osm`), optional Overture Maps ML building heights (`--buildings overture` / `hybrid`), local georeferenced GeoTIFF DSMs (`--dem-file` / `--dsm-file`), NRCan CanElevation 1 m Canadian LiDAR DSMs (`--dem canada-hrdem-dsm`, zero extra deps), or on-the-fly USGS 3DEP LiDAR EPT streaming (`--lidar-ept`).
- **LoRa RF Propagation Modeling**: Evaluates **1st Fresnel Zone ($F_1$) clearance** at `915 MHz`, `868 MHz`, or `433 MHz`, **4/3 effective Earth curvature + atmospheric refraction**, minimum terrain/surface clearance, and **Free-Space Path Loss (FSPL in dB)**.
- **Automatic UTM Projection & Multi-Source Elevation**: Auto-detects local metric UTM zones (`EPSG:269xx` / `326xx` / `327xx`) and streams 32-bit float elevation grids from **USGS 3DEP**, **NRCan CanElevation (Canada HRDEM 1m/2m & MRDEM-30)**, state GIS servers (`ny-gis`), custom ArcGIS ImageServers, or local GeoTIFFs.
- **Automated Cartography & Markdown Reports**: Exports high-resolution (`1920x1080`) PNG maps (`topo`, `world-topo`, `canada-topo`, `osm`, or `satellite` basemaps), cross-sectional terrain/building profiles, viewshed coverage heatmaps, and detailed Markdown reports (`results/YYYY-MM-DD_HH-MM-SS/`).

---

## Quick Start

### Install via Conda / Mamba (macOS, Windows, Linux)

```bash
conda create -n lora-gis -c conda-forge python=3.11 qgis numpy pillow
conda activate lora-gis
pip install --no-build-isolation -e .
```

See [docs/installation.md](docs/installation.md) for native Linux, macOS, Windows (OSGeo4W) instructions, and optional `overture` / `lidar` extras.

### Run Your First Analysis

```bash
# 1. Simple point-to-point repeater discovery across terrain (US or Canada)
python3 -m lora_gis --route "Beacon, NY" "New Paltz, NY"
python3 -m lora_gis --route "Banff, AB" "Canmore, AB"

# 2. City rooftop viewshed ranking across a 3 km radius
python3 -m lora_gis --city "Salina, KS" --radius 3km --top 10 --rx-height 6ft
python3 -m lora_gis --city "Ottawa, ON" --dem canada-hrdem-dsm --radius 2km --top 10
```

---

## Documentation

| Guide | What It Covers |
| :--- | :--- |
| **[Installation & Setup](docs/installation.md)** | Conda/Mamba, native Linux/macOS/Windows packages, optional Overture/PDAL extras, and running tests. |
| **[Repeater Discovery](docs/repeater-discovery.md)** | Simple `--route` pathfinding, `--links` mesh topologies, JSON configs, `--candidates` relay evaluation, and interpreting RF metrics. |
| **[City & DSM Analysis](docs/city-and-dsm-analysis.md)** | Urban `--city` rooftop ranking, viewshed heatmaps, OSM/Overture/hybrid building overlays, local LiDAR DSM GeoTIFFs, and USGS 3DEP LiDAR EPT streaming. |
| **[CLI & Config Reference](docs/cli-reference.md)** | Complete categorized CLI option tables (`lora-gis --help`) and JSON configuration schema. |
| **[Python Library Usage](docs/python-api.md)** | Programmatic configs, headless `run_analysis()` calls, and lower-level DEM, RF, building, viewshed, and LiDAR APIs. |

---

## Sample Output (`Roscoe <-> Livingston Manor <-> Liberty`)

Generated with:

```bash
python3 -m lora_gis --state NY --dem ny-gis --route "Roscoe" "Livingston Manor" "Liberty" --hops 2 --candidates "shandelee-ridge=41.8804,-74.8890" "ferndale-ridge=41.7665,-74.6997" "willowemoc-ridge=41.9056,-74.6774"
```

- **Full RF Analysis Report, Topographic Map & Terrain Profiles**: [`examples/roscoe-livingston-manor-liberty/report.md`](examples/roscoe-livingston-manor-liberty/report.md)
  - **Leg 1 (`Roscoe <-> Livingston Manor`, `7.95 km`)**: Direct sightline blocked by terrain (`-185.3 m` deficit); solved by a **2-Hop Repeater Pair** (`7.98 km` total path, `69%` worst-case $F_1$ clearance) or a **Hybrid 2-Hop** pairing **Shandelee Ridge** with a grid relay (`14.77 km`, `56%` $F_1$).
  - **Leg 2 (`Livingston Manor <-> Liberty`, `12.93 km`)**: Direct sightline blocked by terrain (`-188.3 m` deficit); solved by a **2-Hop Repeater Pair** (`13.02 km` total path, `70%` worst-case $F_1$ clearance) or a **Hybrid 2-Hop** pairing a grid relay with **Ferndale Ridge** (`23.90 km`, `58%` $F_1$).
  - **Explicit Candidate Relays & Terrain Blockage (`Shandelee Ridge`, `Ferndale Ridge`, `Willowemoc Ridge`)**: Evaluates three spaced-out ridge sites with cross-sectional terrain profiles ([`candidate_profiles.png`](examples/roscoe-livingston-manor-liberty/candidate_profiles.png)), green clear sightlines, and red `x` ridge blockage markers on [`map.png`](examples/roscoe-livingston-manor-liberty/map.png). **Shandelee Ridge** (`655 m / 2,148 ft`) has an unblocked leg to `Roscoe` (`87%` $F_1$, `+11.1 m`) and **Ferndale Ridge** (`441 m / 1,446 ft`) has an unblocked leg to `Liberty` (`61%` $F_1$, `+5.0 m`), while **Willowemoc Ridge** (`642 m`) is blocked across all legs (`-139.0 m` / `-107.9 m` / `-116.5 m`).

---

## Acknowledgments

Special thanks to [@tectosage](https://github.com/tectosage) for contributions to the original implementation and code review.

---

## License

Released under the [MIT License](LICENSE).
