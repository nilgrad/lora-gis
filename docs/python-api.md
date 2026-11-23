# Using `lora-gis` as a Python Library

You can import `lora_gis` directly in project-specific wrapper scripts, batch automation pipelines, or custom RF analysis notebooks.

---

## 1. Preconfigured CLI Wrapper (`LoRaGISConfig` + `main`)

Pre-populate a regional catalog and defaults in Python while keeping full CLI flag support:

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

## 2. Programmatic Headless Runs (`apply_cli_args` + `run_analysis`)

`run_analysis()` manages a process-wide headless `QgsApplication` singleton automatically, so you can invoke it multiple times inside one Python process to sweep parameters or evaluate several towns in a loop.

### Route / Link Discovery

```python
from lora_gis import LoRaGISConfig, apply_cli_args, run_analysis

cfg = LoRaGISConfig(title="BatchRouteCheck", output_dir="results")
apply_cli_args(
    cfg,
    argv=[
        "--route", "Beacon, NY", "New Paltz, NY",
        "--hops", "2",
        "--relay-height", "50ft",
    ],
)

result = run_analysis(cfg)
print("Map:", result["png_output_path"])
print("Report:", result["md_output_path"])

for link in result["link_results"]:
    best_1h = link["best_1hop"]
    print(link["u_loc"]["name"], "<->", link["v_loc"]["name"], "direct clear:", link["direct_clear"])
    if best_1h:
        print("  Best 1-hop min F1:", f"{best_1h['min_fresnel'] * 100:.0f}%")
```

### City Viewshed Analysis

```python
from lora_gis import LoRaGISConfig, run_analysis

cfg = LoRaGISConfig(
    title="SalinaMesh",
    city_target="Salina, KS",
    city_radius_m=3000.0,
    city_top_n=10,
    city_rx_height_m=1.83,     # 6 ft handheld
    city_mast_height_m=3.05,   # 10 ft rooftop mast
    buildings_source="osm",    # or 'overture' / 'hybrid'
)

result = run_analysis(cfg)
city = result["city_result"]

for rank, site in enumerate(city["top_results"], 1):
    print(f"#{rank} {site.name}: {site.f1_pct:.1f}% F1, {site.los_pct:.1f}% LOS ({site.lat:.5f}, {site.lon:.5f})")

for combo in city["combos"]:
    names = " + ".join(s.name for s in combo["sites"])
    print(f"{combo['size']}-site combo ({names}): {combo['cumulative_f1_pct']:.1f}% F1")
```

---

## 3. Low-Level Module APIs

Every computational component can also be imported directly without running full map rendering.

### DEM / DSM Loading & Single-Link RF Profiles

```python
from lora_gis import DEMProvider, LoRaGISConfig, detect_utm_crs
from lora_gis.rf import analyze_link_profile, calc_fspl_db

epsg_str, wkid, zone = detect_utm_crs(38.8403, -97.6114)
cfg = LoRaGISConfig(freq_mhz=915.0, surface_mode="dsm")

dem = DEMProvider(
    image_server_base=cfg.image_server_base,
    wkid=wkid,
    dem_file="salina_ground.tif",
    dsm_file="salina_dsm.tif",
    sampling_mode="nearest",
)
dem.load_raster(619000.0, 4299000.0, 623000.0, 4303000.0)

prof = analyze_link_profile(
    dem,
    cfg,
    p1=(620000.0, 4300000.0),
    h1=10.0,
    p2=(622000.0, 4301500.0),
    h2=10.0,
    include_profile=True,
)
print("Clear:", prof["clear"], "Min F1:", f"{prof['min_fresnel_ratio']*100:.0f}%", "FSPL:", f"{prof['fspl_db']:.1f} dB")
```

### Building Overlays & Viewshed Scoring

```python
from lora_gis import (
    fetch_osm_buildings,
    fetch_overture_buildings,
    merge_building_datasets,
    rasterize_buildings_onto_dem,
    select_tall_structure_candidates,
    evaluate_candidate_viewshed,
    optimize_site_combinations,
)
```

- `fetch_osm_buildings(bbox_wgs84, proj_fn, ...)`: Zero-dependency Overpass client returning `List[BuildingFeature]`.
- `fetch_overture_buildings(bbox_wgs84, proj_fn, ...)`: Optional Overture Maps GeoParquet client.
- `merge_building_datasets(overture_buildings, osm_buildings, match_radius_m=25.0)`: Combines Overture heights with OSM names, addresses, and tall `man_made` structures.
- `rasterize_buildings_onto_dem(dem, buildings, target_res_m=2.0)`: Burns building footprints onto `dem.cache` and attaches `dem.surface_cache`.
- `evaluate_candidate_viewshed(dem, config, candidate_xy, mast_height_m, target_xy, rx_height_m)`: Vectorized LOS and $F_1$ coverage scoring returning `(los_mask, f1_mask, max_los_range_m, max_f1_range_m)`.
- `optimize_site_combinations(ranked_results, max_combo_size=3)`: Greedy multi-site set-cover optimizer.

### Optional USGS 3DEP LiDAR EPT Streaming

```python
from lora_gis import build_pdal_dsm_pipeline, match_ept_resources_for_bbox, stream_3dep_lidar_dsm
```

- `stream_3dep_lidar_dsm(dem, bbox_wgs84, utm_bounds, wkid, resolution_m=2.0)`: Discovers intersecting USGS 3DEP EPT datasets, streams via optional `pdal`, caches the max-Z DSM GeoTIFF, and attaches it to `dem.surface_cache`.
