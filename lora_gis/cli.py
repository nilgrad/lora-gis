"""Command-line interface and orchestration pipeline for lora-gis."""

import argparse
from datetime import datetime
import os
import sys
import tempfile
from typing import Dict, List, Optional
import numpy as np

from .cartography import render_candidate_profiles, render_topographic_map
from .config import LoRaGISConfig, parse_height_value_m
from .dem import DEMProvider
from .geonames import parse_link_pair, resolve_location
from .report import export_markdown_report
from .rf import analyze_link, compute_link_padding
from .utm import detect_utm_crs, parse_crs_wkid


def build_arg_parser(prog_title: str = "LoRa-GIS") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"{prog_title}: PyQGIS LoRa / MeshCore RF Line-of-Sight & Repeater Pathfinder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  lora-gis --route "Beacon, NY" "New Paltz, NY"\n'
            '  lora-gis --route "Boulder, CO" "Nederland, CO" --relay-height 40ft\n'
            "  lora-gis --links site_a=41.885,-74.555:site_b=41.920,-74.660 --hops 2\n"
            "  lora-gis --route a=38.840,-97.625 b=38.840,-97.595 --dem-file city_dsm.tif --surface-mode dsm --basemap osm\n"
            "  lora-gis --config network.json\n"
        ),
    )

    topo_group = parser.add_argument_group("Topology & Locations")
    topo_group.add_argument(
        "--config", "-c",
        metavar="FILE",
        help="Path to a JSON configuration file defining locations, route/links, and RF parameters",
    )
    topo_group.add_argument(
        "--route", "-r",
        nargs="+",
        metavar="LOCATION",
        help="Ordered sequence of locations forming a multi-leg route (e.g., --route 'Beacon, NY' 'New Paltz, NY')",
    )
    topo_group.add_argument(
        "--links", "--link", "-l",
        nargs="+",
        metavar="LOC1:LOC2",
        help="Explicit point-to-point link pairs (e.g., --links node1:node2 node2:node3)",
    )
    topo_group.add_argument(
        "--candidates", "--candidate-relays",
        nargs="+",
        metavar="LOCATION",
        help="Explicit candidate relay locations to evaluate alongside the grid search (catalog slug or 'name=lat,lon')",
    )
    topo_group.add_argument(
        "--state",
        default=None,
        help="Default 2-letter US state code for USGS GeoNames lookups (e.g. 'NY', 'CO')",
    )

    height_group = parser.add_argument_group("Antenna & Relay Heights")
    height_group.add_argument(
        "--height", "-H",
        nargs="+",
        metavar="LOC=HEIGHT",
        help="Set antenna/repeater height for specific locations (e.g., --height node1=30ft node2=10m)",
    )
    height_group.add_argument(
        "--observer-height",
        default=None,
        help="Default endpoint antenna height, e.g. '33ft' or '10m' (default: 33ft / 10.0m)",
    )
    height_group.add_argument(
        "--repeater-height",
        default=None,
        help="Default hub repeater height in multi-leg topologies, e.g. '30ft' or '9.14m'",
    )
    height_group.add_argument(
        "--relay-height",
        default=None,
        help="Intermediate candidate relay mount height, e.g. '60ft' or '18.3m' (default: 60ft / 18.3m)",
    )
    height_group.add_argument(
        "--candidate-height",
        default=None,
        help="Mount height override for explicit candidate relays, e.g. '30ft' or '9.14m'",
    )

    rf_group = parser.add_argument_group("RF & Grid Search")
    rf_group.add_argument(
        "--hops",
        type=int,
        choices=[1, 2],
        default=None,
        help="Max intermediate relays per link (default: 2 for single-link mode, 1 for multi-link topologies)",
    )
    rf_group.add_argument(
        "--freq-mhz", "--freq",
        type=float,
        default=None,
        help="Operating frequency in MHz (default: 915.0 for US915, or e.g. 868.0 for EU868)",
    )
    rf_group.add_argument(
        "--min-fresnel",
        type=float,
        default=None,
        help="Target 1st Fresnel Zone clearance ratio (default: 0.60 for 60%% F1)",
    )
    rf_group.add_argument(
        "--grid-step",
        type=float,
        default=None,
        help="Initial coarse candidate grid step in meters (default: 500.0)",
    )
    rf_group.add_argument(
        "--min-grid-step",
        type=float,
        default=None,
        help="Minimum refined candidate grid step in meters (default: 150.0)",
    )

    elev_group = parser.add_argument_group("Elevation, Surface & DSM")
    elev_group.add_argument(
        "--dem",
        default=None,
        help="DEM source preset ('usgs-3dep', 'ny-gis') or custom ArcGIS ImageServer URL",
    )
    elev_group.add_argument(
        "--dem-file",
        default=None,
        help="Local georeferenced GeoTIFF DEM/DSM file path for offline or regional elevation data",
    )
    elev_group.add_argument(
        "--dsm-file",
        default=None,
        help="Optional local georeferenced DSM GeoTIFF (buildings/trees) overlaid for path obstructions",
    )
    elev_group.add_argument(
        "--dem-units",
        choices=["m", "ft", "us-ft"],
        default=None,
        help="Vertical elevation units of the DEM/DSM source ('m', 'ft', or 'us-ft'; default: 'm')",
    )
    elev_group.add_argument(
        "--surface-mode",
        choices=["dem", "dsm"],
        default=None,
        help="Elevation surface sampling mode: 'dem' (bare-earth bilinear) or 'dsm' (nearest-neighbor + dense urban sampling)",
    )
    elev_group.add_argument(
        "--sample-step",
        type=float,
        default=None,
        help="Sightline ray sample spacing in meters (default: 5m in DSM mode, 25m in DEM mode)",
    )
    elev_group.add_argument(
        "--rooftop-margin",
        default=None,
        help="Near-field exclusion radius around endpoints in DSM mode, e.g. '12m' or '40ft' (default: 12m in DSM mode)",
    )
    elev_group.add_argument(
        "--crs",
        default=None,
        help="Override metric projection EPSG code (e.g. 'EPSG:26918'); auto-detected from lat/lon by default",
    )

    output_group = parser.add_argument_group("Map & Output")
    output_group.add_argument(
        "--basemap",
        default=None,
        help="Map backdrop preset ('topo', 'osm', 'satellite') or custom QGIS XYZ/WMS URI (default: 'topo')",
    )
    output_group.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Directory for timestamped map.png and report.md outputs (default: results)",
    )
    output_group.add_argument(
        "--title",
        default=None,
        help="Project title prefix used in generated Markdown reports",
    )
    return parser


def _resolve_candidate_token(tok: str, config: LoRaGISConfig) -> str:
    """Resolves a candidate relay location token and applies candidate height defaults."""
    existing_keys = set(config.locations.keys())
    key = resolve_location(tok, config)
    if key not in config.custom_height_keys:
        if config.candidate_height_m is not None:
            config.locations[key]["height_m"] = config.candidate_height_m
        elif key not in existing_keys:
            config.locations[key]["height_m"] = config.relay_height_m
    return key


def apply_cli_args(config: LoRaGISConfig, argv: Optional[List[str]] = None) -> LoRaGISConfig:
    """Parses CLI arguments and applies overrides to `config`."""
    parser = build_arg_parser(config.title)
    args, _ = parser.parse_known_args(argv)

    if args.config:
        config.load_json_config(args.config)

    if args.title is not None:
        config.title = args.title
    if args.state is not None:
        config.default_state = args.state
    if args.freq_mhz is not None:
        config.freq_mhz = args.freq_mhz
    if args.relay_height is not None:
        config.relay_height_m = parse_height_value_m(args.relay_height)
    if args.candidate_height is not None:
        config.candidate_height_m = parse_height_value_m(args.candidate_height)
    if args.observer_height is not None:
        old_obs = config.default_observer_height_m
        new_obs = parse_height_value_m(args.observer_height)
        config.default_observer_height_m = new_obs
        for loc in config.locations.values():
            if loc.get("height_m") == old_obs:
                loc["height_m"] = new_obs
    if args.repeater_height is not None:
        config.default_repeater_height_m = parse_height_value_m(args.repeater_height)
    if args.min_fresnel is not None:
        config.min_fresnel_clearance = args.min_fresnel
    if args.grid_step is not None:
        config.initial_grid_step_m = args.grid_step
    if args.min_grid_step is not None:
        config.min_grid_step_m = args.min_grid_step
    if args.dem is not None:
        config.dem_source = args.dem
    if args.dem_file is not None:
        config.dem_file = args.dem_file
    if args.dsm_file is not None:
        config.dsm_file = args.dsm_file
    if args.dem_units is not None:
        config.dem_units = args.dem_units
    if args.surface_mode is not None:
        config.surface_mode = args.surface_mode
    if args.sample_step is not None:
        config.sample_step_m = args.sample_step
    if args.rooftop_margin is not None:
        config.rooftop_margin_m = parse_height_value_m(args.rooftop_margin)
    if args.basemap is not None:
        config.basemap = args.basemap
    if args.crs is not None:
        config.crs_epsg = args.crs
    if args.output_dir is not None:
        config.output_dir = args.output_dir
    if args.hops is not None:
        config.hops_override = args.hops

    if args.route:
        if len(args.route) < 2:
            raise SystemExit("Error: --route requires at least 2 locations.")
        resolved_route = [resolve_location(tok, config) for tok in args.route]
        for i in range(len(resolved_route) - 1):
            pair = (resolved_route[i], resolved_route[i + 1])
            if pair not in config.active_links and (pair[1], pair[0]) not in config.active_links:
                config.active_links.append(pair)

    if args.links:
        for pair_tok in args.links:
            pair = parse_link_pair(pair_tok, config)
            if pair not in config.active_links and (pair[1], pair[0]) not in config.active_links:
                config.active_links.append(pair)

    if args.candidates:
        for cand_tok in args.candidates:
            cand_key = _resolve_candidate_token(cand_tok, config)
            if cand_key not in config.active_candidate_keys:
                config.active_candidate_keys.append(cand_key)

    if args.height:
        for h_item in args.height:
            if "=" not in h_item:
                raise SystemExit(
                    f"Error: Invalid --height '{h_item}'. Expected 'location=height' (e.g. 'site_a=30ft')."
                )
            loc_tok, h_val_str = h_item.split("=", 1)
            loc_key = resolve_location(loc_tok, config)
            config.locations[loc_key]["height_m"] = parse_height_value_m(h_val_str)
            config.custom_height_keys.add(loc_key)

    return config


def run_analysis(config: LoRaGISConfig) -> Dict:
    """Executes the full DEM streaming, RF LOS pathfinding, PyQGIS map rendering, and report generation."""
    if not config.active_links:
        if config.default_links:
            for u_tok, v_tok in config.default_links:
                config.active_links.append((resolve_location(u_tok, config), resolve_location(v_tok, config)))
        elif config.default_route:
            resolved_default = [resolve_location(tok, config) for tok in config.default_route]
            for i in range(len(resolved_default) - 1):
                config.active_links.append((resolved_default[i], resolved_default[i + 1]))
        else:
            raise SystemExit(
                "Error: No route or links specified. Pass '--route LOC1 LOC2', '--links LOC1:LOC2', or '--config FILE'."
            )

    if not config.active_candidate_keys and config.candidate_relays:
        for cand_tok in config.candidate_relays:
            cand_key = _resolve_candidate_token(cand_tok, config)
            if cand_key not in config.active_candidate_keys:
                config.active_candidate_keys.append(cand_key)

    node_degree: Dict[str, int] = {}
    active_location_keys: List[str] = []
    for u_key, v_key in config.active_links:
        node_degree[u_key] = node_degree.get(u_key, 0) + 1
        node_degree[v_key] = node_degree.get(v_key, 0) + 1
        if u_key not in active_location_keys:
            active_location_keys.append(u_key)
        if v_key not in active_location_keys:
            active_location_keys.append(v_key)

    endpoint_custom_heights = {k for k in config.custom_height_keys if k in active_location_keys}
    multi_link_mode = len(config.active_links) > 1 or len(endpoint_custom_heights) > 0
    enable_2hop = (
        (config.hops_override == 2) if config.hops_override is not None else (not multi_link_mode)
    )

    hub_repeater_keys = set(endpoint_custom_heights)
    if len(config.active_links) > 1:
        for k, deg in node_degree.items():
            if deg >= 2:
                hub_repeater_keys.add(k)
                if k not in config.custom_height_keys:
                    config.locations[k]["height_m"] = config.default_repeater_height_m

    os.environ.setdefault("QGIS_CUSTOM_CONFIG_PATH", os.path.join(tempfile.gettempdir(), "qgis_los_config"))
    if sys.platform.startswith("linux"):
        xdg_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        wl_disp = os.environ.get("WAYLAND_DISPLAY", "")
        has_wayland = bool(wl_disp) and bool(xdg_dir) and os.path.exists(os.path.join(xdg_dir, wl_disp))
        if not os.environ.get("DISPLAY") and not has_wayland:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsPointXY,
        QgsProject,
    )
    from qgis.PyQt.QtCore import QCoreApplication

    qgs_app = None
    headless_cli = False
    if QgsApplication.instance() is None:
        headless_cli = True
        qgis_prefix = os.environ.get("QGIS_PREFIX_PATH")
        if not qgis_prefix:
            if os.environ.get("CONDA_PREFIX"):
                conda_p = os.environ["CONDA_PREFIX"]
                qgis_prefix = os.path.join(conda_p, "Library") if sys.platform == "win32" else conda_p
            elif sys.platform == "darwin":
                for app_cand in (
                    "/Applications/QGIS.app/Contents/MacOS",
                    "/Applications/QGIS-LTR.app/Contents/MacOS",
                ):
                    if os.path.isdir(app_cand):
                        qgis_prefix = app_cand
                        break
            elif os.path.isdir("/usr"):
                qgis_prefix = "/usr"
        if qgis_prefix:
            QgsApplication.setPrefixPath(qgis_prefix, True)
        qgs_app = QgsApplication([], False)
        qgs_app.initQgis()

    try:
        # Auto-detect UTM CRS from the centroid of active locations unless overridden
        mean_lat = float(np.mean([config.locations[k]["lat"] for k in active_location_keys]))
        mean_lon = float(np.mean([config.locations[k]["lon"] for k in active_location_keys]))
        if config.crs_epsg:
            epsg_str, wkid, zone_label = parse_crs_wkid(config.crs_epsg)
        else:
            epsg_str, wkid, zone_label = detect_utm_crs(mean_lat, mean_lon)

        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        expanded_out = os.path.expanduser(config.output_dir)
        base_output_dir = (
            expanded_out if os.path.isabs(expanded_out) else os.path.join(config.base_dir, expanded_out)
        )
        run_output_dir = os.path.join(base_output_dir, timestamp_str)
        os.makedirs(run_output_dir, exist_ok=True)

        png_filename = "map.png"
        md_filename = "report.md"
        png_output_path = os.path.join(run_output_dir, png_filename)
        md_output_path = os.path.join(run_output_dir, md_filename)

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_utm = QgsCoordinateReferenceSystem(epsg_str)
        transform = QgsCoordinateTransform(crs_wgs84, crs_utm, QgsProject.instance())
        inv_transform = QgsCoordinateTransform(crs_utm, crs_wgs84, QgsProject.instance())

        for k in active_location_keys:
            loc = config.locations[k]
            pt_utm = transform.transform(QgsPointXY(loc["lon"], loc["lat"]))
            loc["x"] = float(pt_utm.x())
            loc["y"] = float(pt_utm.y())
            loc["xy"] = (loc["x"], loc["y"])
            role_tag = "Repeater Hub" if k in hub_repeater_keys else "Observer"
            print(
                f"Projected {loc['name']:<16} ({zone_label}): E {loc['x']:.2f}, N {loc['y']:.2f} "
                f"({role_tag} Height: {loc['height_m']:.2f} m / {loc['height_m']*3.28084:.0f} ft)",
                flush=True,
            )

        for k in config.active_candidate_keys:
            if k in active_location_keys:
                continue
            loc = config.locations[k]
            pt_utm = transform.transform(QgsPointXY(loc["lon"], loc["lat"]))
            loc["x"] = float(pt_utm.x())
            loc["y"] = float(pt_utm.y())
            loc["xy"] = (loc["x"], loc["y"])
            print(
                f"Projected {loc['name']:<16} ({zone_label}): E {loc['x']:.2f}, N {loc['y']:.2f} "
                f"(Candidate Relay Height: {loc['height_m']:.2f} m / {loc['height_m']*3.28084:.0f} ft)",
                flush=True,
            )

        for u_key, v_key in config.active_links:
            u_loc, v_loc = config.locations[u_key], config.locations[v_key]
            dist_km = np.hypot(v_loc["x"] - u_loc["x"], v_loc["y"] - u_loc["y"]) / 1000.0
            print(
                f"Link {u_loc['name']} <-> {v_loc['name']}: {dist_km:.2f} km | "
                f"Frequency: {config.freq_mhz:.1f} MHz | "
                f"Relay Height: {config.relay_height_m:.1f} m ({config.relay_height_m*3.28084:.0f} ft)",
                flush=True,
            )
        print(f"Target Output PNG: {png_output_path}", flush=True)
        print(f"Target Output MD:  {md_output_path}", flush=True)
        QCoreApplication.processEvents()

        dem = DEMProvider(
            image_server_base=config.image_server_base,
            wkid=wkid,
            dem_file=config.dem_file,
            unit_scale=config.dem_unit_scale,
            sampling_mode="nearest" if config.is_dsm_mode else "bilinear",
            dsm_file=config.dsm_file,
        )

        all_dem_keys = list(active_location_keys) + [
            k for k in config.active_candidate_keys if k not in active_location_keys
        ]
        all_xs = [config.locations[k]["x"] for k in all_dem_keys]
        all_ys = [config.locations[k]["y"] for k in all_dem_keys]
        max_link_pad = max(
            compute_link_padding(config.locations[u], config.locations[v], config)
            for u, v in config.active_links
        )
        dem_padding = max_link_pad + 500.0

        dem.load_raster(
            min(all_xs) - dem_padding,
            min(all_ys) - dem_padding,
            max(all_xs) + dem_padding,
            max(all_ys) + dem_padding,
            resolution_m=1.5 if config.is_dsm_mode else (6.0 if multi_link_mode else 3.0),
            max_px=4000 if config.is_dsm_mode else 2500,
        )

        link_results = []
        all_viable_relays = set()
        user_cancelled = False

        for u_key, v_key in config.active_links:
            res = analyze_link(
                u_key=u_key,
                v_key=v_key,
                config=config,
                dem=dem,
                inv_transform=inv_transform,
                hub_repeater_keys=hub_repeater_keys,
                multi_link_mode=multi_link_mode,
                allow_2hop=enable_2hop,
                headless_cli=headless_cli,
                candidate_keys=config.active_candidate_keys,
            )
            link_results.append(res)
            all_viable_relays.update(res["viable_relays"])
            if res["user_cancelled"]:
                user_cancelled = True
                break

        any_solution = any(
            r["best_1hop"] is not None or r["best_2hop"] is not None or r["direct_clear"]
            for r in link_results
        ) or bool(config.active_candidate_keys)

        if any_solution and not user_cancelled:
            peaks_list, towns_list, peak_elevs = render_topographic_map(
                config=config,
                dem=dem,
                link_results=link_results,
                all_viable_relays=all_viable_relays,
                hub_repeater_keys=hub_repeater_keys,
                multi_link_mode=multi_link_mode,
                crs_utm=crs_utm,
                epsg_str=epsg_str,
                wkid=wkid,
                inv_transform=inv_transform,
                timestamp_str=timestamp_str,
                png_output_path=png_output_path,
                candidate_keys=config.active_candidate_keys,
            )

            profiles_filename = None
            if config.active_candidate_keys:
                profiles_path = os.path.join(run_output_dir, "candidate_profiles.png")
                if render_candidate_profiles(config=config, link_results=link_results, png_output_path=profiles_path):
                    profiles_filename = "candidate_profiles.png"

            export_markdown_report(
                config=config,
                dem=dem,
                active_location_keys=active_location_keys,
                link_results=link_results,
                hub_repeater_keys=hub_repeater_keys,
                multi_link_mode=multi_link_mode,
                enable_2hop=enable_2hop,
                zone_label=zone_label,
                inv_transform=inv_transform,
                peaks_list=peaks_list,
                towns_list=towns_list,
                peak_elevs=peak_elevs,
                timestamp_str=timestamp_str,
                png_filename=png_filename,
                md_output_path=md_output_path,
                candidate_keys=config.active_candidate_keys,
                profiles_filename=profiles_filename,
            )

        return {
            "run_output_dir": run_output_dir,
            "png_output_path": png_output_path,
            "md_output_path": md_output_path,
            "link_results": link_results,
        }
    finally:
        if qgs_app is not None:
            qgs_app.exitQgis()


def main(default_config: Optional[LoRaGISConfig] = None, argv: Optional[List[str]] = None) -> Dict:
    """CLI entry point supporting both standalone `lora-gis` and preconfigured project wrappers."""
    cfg = default_config if default_config is not None else LoRaGISConfig()
    apply_cli_args(cfg, argv=argv)
    return run_analysis(cfg)
