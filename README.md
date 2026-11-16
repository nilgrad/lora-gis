# lora-gis

A **PyQGIS** Line-of-Sight (LOS) and **LoRa / MeshCore RF repeater pathfinder** and automated topographic map renderer. Designed to route off-grid radio links across mountainous terrain using high-resolution Digital Elevation Models (DEMs).

- **1-Hop & 2-Hop Repeater Discovery**: Scans candidate grids from coarse (`500 m`) down to fine (`150 m`) resolution to discover both **single-repeater (`1-hop`)** and **two-repeater (`2-hop`)** sightline paths when direct line-of-sight is blocked by terrain.
- **Topology-Based Multi-Leg & Mesh Routing**: Define sequential routes (`--route`), explicit point-to-point mesh links (`--links`), or JSON topology configs (`--config`), with automatic repeater mount-height sensitivity tables (`30 ft` to `90 ft`) for intermediate hub nodes.
- **LoRa RF Propagation Modeling**: Evaluates **1st Fresnel Zone ($F_1$) clearance** at `915 MHz` (US915), `868 MHz` (EU868), or `433 MHz`, **4/3 effective Earth curvature + atmospheric refraction**, minimum terrain clearance, and **Free-Space Path Loss (FSPL in dB)** along every hop.
- **Multi-Source DEM & Automatic UTM Projection**: Automatically detects the local metric UTM zone (`EPSG:269xx` / `326xx` / `327xx`) and streams 32-bit float elevation grids from **USGS 3DEP** (nationwide US), state GIS servers (`ny-gis`), custom ArcGIS ImageServers, or local GeoTIFF DEM files.
- **Automated Topographic Cartography & Markdown Reports**: Exports both a high-resolution (`1920×1080`) PNG topographic map and a detailed Markdown RF report (`results/YYYY-MM-DD_HH-MM-SS/`) containing link metrics, node elevations, hop-by-hop Fresnel clearances, FSPL, top candidate relay sites, and surrounding USGS GeoNames mountain summits and towns.

---

## Requirements

- **Python 3** (`>= 3.10`)
- **QGIS & PyQGIS** (`qgis.core`)
- **PyQt5** (`PyQt5.QtCore`, `PyQt5.QtGui`, `PyQt5.QtWidgets`)
- **NumPy** (`numpy`)
- **Pillow** (`PIL`)

Install system dependencies on Linux:

```bash
# Debian / Ubuntu
sudo apt install qgis python3-qgis python3-pyqt5 python3-numpy python3-pil

# Fedora / RHEL
sudo dnf install qgis python3-qgis python3-qt5 python3-numpy python3-pillow

# Arch Linux
sudo pacman -S qgis python-pyqt5 python-numpy python-pillow
```

Install `lora-gis` in editable or user mode:

```bash
pip install --no-build-isolation --user -e .
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

### CLI Options Reference

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--route`, `-r` | Ordered sequence of 2+ locations forming a route | — |
| `--links`, `-l` | Explicit `LOC1:LOC2` point-to-point link pairs | — |
| `--height`, `-H` | Override antenna height per location (`LOC=30ft` or `LOC=10m`) | — |
| `--hops` | Maximum intermediate relays per link (`1` or `2`) | `2` (single link), `1` (multi-link) |
| `--freq-mhz` | LoRa operating frequency in MHz (`915.0`, `868.0`, `433.0`) | `915.0` |
| `--relay-height` | Intermediate candidate relay height (`ft` or `m`) | `60ft` (`18.3 m`) |
| `--observer-height` | Default endpoint antenna height (`ft` or `m`) | `33ft` (`10.0 m`) |
| `--repeater-height` | Default hub repeater height in multi-leg routes (`ft` or `m`) | `30ft` (`9.14 m`) |
| `--min-fresnel` | Target 1st Fresnel Zone ($F_1$) clearance ratio | `0.60` (`60%`) |
| `--grid-step` | Starting coarse search grid step in meters | `500.0` |
| `--min-grid-step` | Finest search grid step in meters | `150.0` |
| `--dem` | DEM preset (`usgs-3dep`, `ny-gis`) or ArcGIS ImageServer URL | `usgs-3dep` |
| `--dem-file` | Local GeoTIFF DEM file path | — |
| `--crs` | Explicit metric EPSG code (auto-detected UTM zone if omitted) | Auto UTM |
| `--state` | Default 2-letter US state code for USGS GeoNames lookups | — |
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

## License

Released under the [MIT License](LICENSE).
