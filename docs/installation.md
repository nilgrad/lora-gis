# Installation & Setup

`lora-gis` requires Python 3.10+ and PyQGIS (which also bundles GDAL/OGR for georeferenced GeoTIFF loading).

## Core Requirements

- **Python 3** (`>= 3.10`)
- **QGIS & PyQGIS** (`qgis.core`, `osgeo.gdal`)
- **PyQt5** (`PyQt5.QtCore`, `PyQt5.QtGui`, `PyQt5.QtWidgets`)
- **NumPy** (`numpy`)
- **Pillow** (`PIL`)
- **Matplotlib** (`matplotlib`, optional, used for cross-sectional candidate terrain profile charts)

---

## Option 1: Cross-Platform via Conda / Mamba (Recommended)

The easiest way to install `qgis` and `PyQGIS` across **macOS (Apple Silicon & Intel)**, **Windows**, and **Linux** is via [`conda-forge`](https://conda-forge.org/) using [Miniforge](https://github.com/conda-forge/miniforge) or [Miniconda](https://docs.anaconda.com/miniconda/):

```bash
conda create -n lora-gis -c conda-forge python=3.11 qgis numpy pillow matplotlib
conda activate lora-gis
pip install --no-build-isolation -e .
```

---

## Option 2: Native OS Packages

### Linux

```bash
# Debian / Ubuntu
sudo apt install qgis python3-qgis python3-pyqt5 python3-numpy python3-pil python3-matplotlib python3-gdal

# Fedora / RHEL
sudo dnf install qgis python3-qgis python3-qt5 python3-numpy python3-pillow python3-matplotlib python3-gdal

# Arch Linux
sudo pacman -S qgis python-pyqt5 python-numpy python-pillow python-matplotlib python-gdal

# Install lora-gis
pip install --no-build-isolation --user -e .
```

### macOS (Official `QGIS.app` or Homebrew)

1. Install QGIS via Homebrew (`brew install --cask qgis`) or download the official macOS disk image from [qgis.org](https://qgis.org/download/).
2. Install and run `lora-gis` using the Python environment bundled inside `QGIS.app`:

```bash
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m pip install --no-build-isolation -e .
/Applications/QGIS.app/Contents/MacOS/bin/python3 -m lora_gis --route "Boulder, CO" "Nederland, CO"
```

### Windows (OSGeo4W / Standalone QGIS Installer)

1. Install QGIS from [qgis.org](https://qgis.org/download/).
2. Open the **OSGeo4W Shell** from the Start Menu (which pre-configures `python` and `QGIS_PREFIX_PATH` for PyQGIS) and run:

```bat
python -m pip install --no-build-isolation -e .
python -m lora_gis --route "Boulder, CO" "Nederland, CO"
```

---

## Optional High-Completeness Urban Backends

Core urban features (OpenStreetMap Overpass `--buildings osm`, local georeferenced DSM GeoTIFFs, and `--city` viewshed mode) require **no extra dependencies**.

If you want ML-estimated building heights from **Overture Maps** or nationwide **USGS 3DEP LiDAR EPT** point cloud streaming, install the optional extras:

```bash
# Overture Maps GeoParquet building heights (--buildings overture / --buildings hybrid)
pip install --no-build-isolation -e ".[overture]"

# USGS 3DEP LiDAR EPT streaming (--lidar-ept / --dem usgs-3dep-dsm)
# Recommended via conda-forge for binary PDAL bindings:
conda install -c conda-forge python-pdal
# Or via pip extra:
pip install --no-build-isolation -e ".[lidar]"

# Both optional backends
pip install --no-build-isolation -e ".[all]"
```

---

## Running the Unit Test Suite

All unit tests run completely offline using Python's built-in `unittest` module:

```bash
python3 -m unittest discover -s tests -v
```
