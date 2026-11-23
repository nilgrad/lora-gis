"""Vectorized city viewshed coverage engine, DSM peak extraction, and multi-site optimizer."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .buildings import BuildingFeature, select_tall_structure_candidates
from .config import LoRaGISConfig
from .dem import DEMProvider


@dataclass
class CityCandidateResult:
    """Viewshed coverage metrics and masks for a single candidate rooftop/structure."""

    key: str
    name: str
    structure_type: str
    address: Optional[str]
    lat: float
    lon: float
    x: float
    y: float
    ground_elev_m: float
    structure_height_m: float
    mast_height_m: float
    height_source: str
    los_pct: float
    f1_pct: float
    los_count: int
    f1_count: int
    total_targets: int
    max_los_range_m: float
    max_f1_range_m: float
    los_mask: np.ndarray  # 1D bool mask over in-circle target cells
    f1_mask: np.ndarray   # 1D bool mask over in-circle target cells


def extract_dsm_peak_candidates(
    dem: DEMProvider,
    center_xy: Tuple[float, float],
    radius_m: float,
    inv_transform,
    count: int = 25,
    min_height_m: float = 12.0,
    min_separation_m: float = 150.0,
) -> List[BuildingFeature]:
    """
    Extracts prominent rooftop/tower local maxima directly from a DSM raster when
    vector building footprints are not loaded.
    """
    from qgis.core import QgsPointXY

    target_cache = dem.surface_cache if dem.surface_cache is not None else dem.cache
    if target_cache is None or count <= 0:
        return []

    surf_arr, xmin, ymin, xmax, ymax, w, h = target_cache
    span_x = max(1e-9, xmax - xmin)
    span_y = max(1e-9, ymax - ymin)
    px_x = span_x / max(1, w)
    px_y = span_y / max(1, h)

    cx, cy = center_xy
    # Build pixel center coordinates inside the study circle (strided if raster is very dense)
    stride = max(1, int(round(max(w, h) / 400.0)))
    rows = np.arange(0, h, stride)
    cols = np.arange(0, w, stride)
    xs_1d = xmin + (cols + 0.5) * px_x
    ys_1d = ymax - (rows + 0.5) * px_y
    xx, yy = np.meshgrid(xs_1d, ys_1d)

    sub_surf = surf_arr[np.ix_(rows, cols)]
    in_circle = (np.hypot(xx - cx, yy - cy) <= radius_m) & np.isfinite(sub_surf) & (sub_surf > -500.0)
    if not np.any(in_circle):
        return []

    if dem.has_separate_surface:
        sub_ground = dem.sample_ground(xx, yy)
        rel_h = sub_surf - np.where(np.isfinite(sub_ground), sub_ground, sub_surf)
    else:
        valid_vals = sub_surf[in_circle]
        baseline = float(np.percentile(valid_vals, 25))
        rel_h = sub_surf - baseline

    cand_mask = in_circle & np.isfinite(rel_h) & (rel_h >= min_height_m)
    if not np.any(cand_mask):
        # Fall back to the highest elevated points in the circle
        cand_mask = in_circle

    r_idx, c_idx = np.where(cand_mask)
    heights = rel_h[r_idx, c_idx]
    elevs = sub_surf[r_idx, c_idx]
    order = np.argsort(-(elevs + 0.1 * heights))

    selected: List[BuildingFeature] = []
    for idx in order:
        px = float(xx[r_idx[idx], c_idx[idx]])
        py = float(yy[r_idx[idx], c_idx[idx]])
        if any(np.hypot(px - s.x, py - s.y) < min_separation_m for s in selected):
            continue
        ll = inv_transform.transform(QgsPointXY(px, py))
        h_est = max(0.0, float(heights[idx]))
        rank_num = len(selected) + 1
        selected.append(
            BuildingFeature(
                osm_id=f"dsm-peak/{rank_num}",
                name=f"DSM Peak #{rank_num}",
                structure_type="dsm_peak",
                lat=float(ll.y()),
                lon=float(ll.x()),
                x=px,
                y=py,
                height_m=h_est,
                height_source="dsm",
            )
        )
        if len(selected) >= count:
            break

    return selected


def build_city_target_grid(
    center_xy: Tuple[float, float],
    radius_m: float,
    grid_size: int = 61,
) -> Dict:
    """
    Constructs a shared Cartesian target grid covering the study circle of `radius_m`
    centered at `center_xy`. Returns coordinates, 2D circle mask, and bounds.
    """
    n = max(11, int(grid_size))
    cx, cy = center_xy
    xmin = cx - radius_m
    xmax = cx + radius_m
    ymin = cy - radius_m
    ymax = cy + radius_m

    step_x = (xmax - xmin) / n
    step_y = (ymax - ymin) / n
    xs_1d = xmin + (np.arange(n, dtype=np.float64) + 0.5) * step_x
    ys_1d = ymax - (np.arange(n, dtype=np.float64) + 0.5) * step_y
    xx, yy = np.meshgrid(xs_1d, ys_1d)

    dists_center = np.hypot(xx - cx, yy - cy)
    in_circle_2d = dists_center <= radius_m
    target_rows, target_cols = np.where(in_circle_2d)
    target_xy = np.column_stack([xx[target_rows, target_cols], yy[target_rows, target_cols]])

    return {
        "grid_size": n,
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "cell_size_m": step_x,
        "in_circle_2d": in_circle_2d,
        "target_rows": target_rows,
        "target_cols": target_cols,
        "target_xy": target_xy,
    }


def evaluate_candidate_viewshed(
    dem: DEMProvider,
    config: LoRaGISConfig,
    candidate_xy: Tuple[float, float],
    mast_height_m: float,
    target_xy: np.ndarray,
    rx_height_m: float,
    chunk_size: int = 512,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """
    Vectorized LOS and 1st Fresnel Zone viewshed evaluation from `candidate_xy`
    to all `target_xy` receiver points across the city.

    Returns (los_mask, f1_mask, max_los_range_m, max_f1_range_m).
    """
    n_targets = len(target_xy)
    if n_targets == 0 or dem.cache is None:
        empty = np.zeros(n_targets, dtype=bool)
        return empty, empty.copy(), 0.0, 0.0

    cx, cy = float(candidate_xy[0]), float(candidate_xy[1])
    tx_surf = float(dem.sample_surface(np.array([cx]), np.array([cy]))[0])
    if not np.isfinite(tx_surf) or tx_surf <= -500.0:
        empty = np.zeros(n_targets, dtype=bool)
        return empty, empty.copy(), 0.0, 0.0
    z_tx = tx_surf + float(mast_height_m)

    dists_all = np.hypot(target_xy[:, 0] - cx, target_xy[:, 1] - cy)
    los_mask = np.zeros(n_targets, dtype=bool)
    f1_mask = np.zeros(n_targets, dtype=bool)

    step_m = max(2.0, config.effective_sample_step_m)
    margin_m = config.effective_rooftop_margin_m
    use_separate_ground = dem.has_separate_surface
    f1_thresh = config.min_fresnel_clearance

    for start in range(0, n_targets, chunk_size):
        end = min(n_targets, start + chunk_size)
        pts = target_xy[start:end]
        dists = dists_all[start:end][:, None]
        max_d = float(np.max(dists)) if len(dists) > 0 else 0.0
        n_samples = int(min(600, max(40, int(np.ceil(max_d / step_m)) + 1)))

        t = np.linspace(0.0, 1.0, n_samples)[None, :]
        xs = cx + (pts[:, 0:1] - cx) * t
        ys = cy + (pts[:, 1:2] - cy) * t
        surface = dem.sample_surface(xs, ys)
        valid = np.all(np.isfinite(surface) & (surface > -500.0), axis=1)

        if use_separate_ground:
            rx_ground = dem.sample_ground(pts[:, 0], pts[:, 1])
            rx_valid = np.isfinite(rx_ground) & (rx_ground > -500.0)
            valid = valid & rx_valid
            z_rx = np.where(rx_valid, rx_ground + rx_height_m, 0.0)[:, None]
            # Target pixel is occluded if a structure at the target exceeds rx antenna tip
            rx_not_buried = surface[:, -1] <= (z_rx[:, 0] + 0.5)
        else:
            z_rx = (surface[:, -1:] + rx_height_m)
            rx_not_buried = np.ones(end - start, dtype=bool)

        sightline = z_tx + (z_rx - z_tx) * t
        d1 = dists * t
        d2 = dists * (1.0 - t)
        bulge = (d1 * d2) / (2.0 * config.earth_radius_eff_m)

        clearance = sightline - (surface + bulge)
        interior_clear = clearance[:, 1:-1]
        f1_rad = np.sqrt(config.wavelength_m * d1[:, 1:-1] * d2[:, 1:-1] / np.maximum(dists, 1.0))
        f1_ratios = interior_clear / np.maximum(f1_rad, 0.01)

        if margin_m > 0.0:
            in_margin = d1[:, 1:-1] < margin_m
            has_outside = np.any(~in_margin, axis=1)[:, None]
            apply_mask = in_margin & has_outside
            interior_clear = np.where(apply_mask, np.inf, interior_clear)
            f1_ratios = np.where(apply_mask, np.inf, f1_ratios)

        min_clr = np.min(interior_clear, axis=1)
        min_f1 = np.min(f1_ratios, axis=1)

        # Ultra-close points inside the host margin (dist <= margin_m) are trivially reachable if not buried
        near_self = dists[:, 0] <= max(margin_m, 5.0)
        chunk_los = valid & rx_not_buried & ((min_clr > 0.0) | near_self)
        chunk_f1 = valid & rx_not_buried & ((min_f1 >= f1_thresh) | near_self)

        los_mask[start:end] = chunk_los
        f1_mask[start:end] = chunk_f1

    max_los_range = float(np.max(dists_all[los_mask])) if np.any(los_mask) else 0.0
    max_f1_range = float(np.max(dists_all[f1_mask])) if np.any(f1_mask) else 0.0
    return los_mask, f1_mask, max_los_range, max_f1_range


def optimize_site_combinations(
    ranked_results: Sequence[CityCandidateResult],
    max_combo_size: int = 3,
) -> List[Dict]:
    """
    Greedy set-cover over candidate viewsheds to find the highest-coverage
    1-site, 2-site, and 3-site combinations (maximizing >=60% F1 coverage first,
    then optical LOS coverage).
    """
    if not ranked_results:
        return []

    total_targets = max(1, ranked_results[0].total_targets)
    k_limit = min(int(max_combo_size), len(ranked_results))

    chosen_indices: List[int] = []
    cum_f1 = np.zeros(total_targets, dtype=bool)
    cum_los = np.zeros(total_targets, dtype=bool)
    combos: List[Dict] = []

    for step in range(1, k_limit + 1):
        best_idx = -1
        best_score = (-1, -1, -1)
        for idx, cand in enumerate(ranked_results):
            if idx in chosen_indices:
                continue
            gain_f1 = int(np.sum((~cum_f1) & cand.f1_mask))
            gain_los = int(np.sum((~cum_los) & cand.los_mask))
            score = (gain_f1, gain_los, cand.f1_count)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx < 0:
            break

        picked = ranked_results[best_idx]
        chosen_indices.append(best_idx)
        prev_f1_pct = float(np.sum(cum_f1)) / total_targets * 100.0
        prev_los_pct = float(np.sum(cum_los)) / total_targets * 100.0
        cum_f1 = cum_f1 | picked.f1_mask
        cum_los = cum_los | picked.los_mask
        new_f1_pct = float(np.sum(cum_f1)) / total_targets * 100.0
        new_los_pct = float(np.sum(cum_los)) / total_targets * 100.0

        combos.append({
            "size": step,
            "added": picked,
            "sites": [ranked_results[i] for i in chosen_indices],
            "marginal_f1_pct": new_f1_pct - prev_f1_pct,
            "cumulative_f1_pct": new_f1_pct,
            "marginal_los_pct": new_los_pct - prev_los_pct,
            "cumulative_los_pct": new_los_pct,
            "f1_mask": cum_f1.copy(),
            "los_mask": cum_los.copy(),
        })

    return combos


def build_coverage_grid_2d(
    target_grid: Dict,
    los_mask: np.ndarray,
    f1_mask: np.ndarray,
) -> np.ndarray:
    """
    Converts 1D target masks into a 2D uint8 coverage classification array:
      0 = outside circle or blocked
      1 = optical LOS clear (< target F1)
      2 = >= target F1 clear
    """
    n = target_grid["grid_size"]
    cov = np.zeros((n, n), dtype=np.uint8)
    rows = target_grid["target_rows"]
    cols = target_grid["target_cols"]
    cov[rows[los_mask], cols[los_mask]] = 1
    cov[rows[f1_mask], cols[f1_mask]] = 2
    return cov


def analyze_city_viewshed(
    center_loc: Dict,
    config: LoRaGISConfig,
    dem: DEMProvider,
    inv_transform,
    buildings: Sequence[BuildingFeature] = (),
    explicit_candidate_keys: Sequence[str] = (),
) -> Dict:
    """
    Executes full city rooftop ranking and viewshed coverage analysis around `center_loc`.
    """
    center_xy = center_loc["xy"]
    radius_m = config.city_radius_m
    target_grid = build_city_target_grid(center_xy, radius_m, grid_size=config.viewshed_grid_size)
    target_xy = target_grid["target_xy"]
    total_targets = len(target_xy)

    study_bbox = (
        center_xy[0] - radius_m,
        center_xy[1] - radius_m,
        center_xy[0] + radius_m,
        center_xy[1] + radius_m,
    )

    candidate_specs: List[Dict] = []
    seen_xy: List[Tuple[float, float]] = []

    # 1. Include user-specified explicit --candidates first
    for c_key in explicit_candidate_keys:
        c_loc = config.locations[c_key]
        c_xy = c_loc["xy"]
        c_mast = (
            c_loc["height_m"]
            if c_key in config.custom_height_keys
            else config.city_mast_height_m
        )
        candidate_specs.append({
            "key": c_key,
            "name": c_loc["name"],
            "structure_type": c_loc.get("structure_type", "explicit_candidate"),
            "address": c_loc.get("address"),
            "lat": c_loc["lat"],
            "lon": c_loc["lon"],
            "x": c_xy[0],
            "y": c_xy[1],
            "structure_height_m": float(c_loc.get("building_height_m", 0.0)),
            "mast_height_m": float(c_mast),
            "height_source": "explicit",
        })
        seen_xy.append(c_xy)

    # 2. Extract tall structures from OSM buildings or DSM local peaks
    needed = max(0, config.city_max_sites - len(candidate_specs))
    if needed > 0:
        if buildings:
            pool = select_tall_structure_candidates(
                buildings=buildings,
                dem=dem,
                count=needed + len(seen_xy),
                min_height_m=config.min_building_height_m,
                min_separation_m=150.0,
                study_bbox=study_bbox,
            )
            if not pool:
                # Fall back to the tallest available structures even if below min_building_height_m
                pool = select_tall_structure_candidates(
                    buildings=buildings,
                    dem=dem,
                    count=needed + len(seen_xy),
                    min_height_m=0.1,
                    min_separation_m=150.0,
                    study_bbox=study_bbox,
                )
        else:
            pool = extract_dsm_peak_candidates(
                dem=dem,
                center_xy=center_xy,
                radius_m=radius_m,
                inv_transform=inv_transform,
                count=needed + len(seen_xy),
                min_height_m=min(12.0, config.min_building_height_m),
                min_separation_m=150.0,
            )

        for feat in pool:
            if len(candidate_specs) >= config.city_max_sites:
                break
            if any(np.hypot(feat.x - sx, feat.y - sy) < 100.0 for sx, sy in seen_xy):
                continue
            candidate_specs.append({
                "key": feat.osm_id,
                "name": feat.name,
                "structure_type": feat.structure_type,
                "address": feat.address,
                "lat": feat.lat,
                "lon": feat.lon,
                "x": feat.x,
                "y": feat.y,
                "structure_height_m": feat.height_m,
                "mast_height_m": config.city_mast_height_m,
                "height_source": feat.height_source,
            })
            seen_xy.append((feat.x, feat.y))

    print(
        f"\nEvaluating viewshed coverage for {len(candidate_specs)} candidate site(s) "
        f"across {total_targets:,} city target points (radius {radius_m/1000.0:.2f} km, "
        f"RX {config.city_rx_height_m*3.28084:.0f} ft, mast {config.city_mast_height_m*3.28084:.0f} ft)...",
        flush=True,
    )

    results: List[CityCandidateResult] = []
    for spec in candidate_specs:
        g_elev = float(dem.sample_ground(np.array([spec["x"]]), np.array([spec["y"]]))[0]) if dem.cache is not None else 0.0
        if not np.isfinite(g_elev):
            g_elev = 0.0
        s_elev = float(dem.sample_surface(np.array([spec["x"]]), np.array([spec["y"]]))[0]) if dem.cache is not None else g_elev
        struct_h = spec["structure_height_m"]
        if struct_h <= 0.0 and np.isfinite(s_elev) and s_elev > g_elev:
            struct_h = s_elev - g_elev

        los_mask, f1_mask, max_los_r, max_f1_r = evaluate_candidate_viewshed(
            dem=dem,
            config=config,
            candidate_xy=(spec["x"], spec["y"]),
            mast_height_m=spec["mast_height_m"],
            target_xy=target_xy,
            rx_height_m=config.city_rx_height_m,
        )
        los_cnt = int(np.sum(los_mask))
        f1_cnt = int(np.sum(f1_mask))
        los_pct = (los_cnt / max(1, total_targets)) * 100.0
        f1_pct = (f1_cnt / max(1, total_targets)) * 100.0

        results.append(
            CityCandidateResult(
                key=spec["key"],
                name=spec["name"],
                structure_type=spec["structure_type"],
                address=spec["address"],
                lat=spec["lat"],
                lon=spec["lon"],
                x=spec["x"],
                y=spec["y"],
                ground_elev_m=g_elev,
                structure_height_m=struct_h,
                mast_height_m=spec["mast_height_m"],
                height_source=spec["height_source"],
                los_pct=los_pct,
                f1_pct=f1_pct,
                los_count=los_cnt,
                f1_count=f1_cnt,
                total_targets=total_targets,
                max_los_range_m=max_los_r,
                max_f1_range_m=max_f1_r,
                los_mask=los_mask,
                f1_mask=f1_mask,
            )
        )

    results.sort(key=lambda r: (r.f1_pct, r.los_pct, r.ground_elev_m + r.structure_height_m), reverse=True)
    top_results = results[: max(1, config.city_top_n)]
    combos = optimize_site_combinations(results, max_combo_size=3)

    if top_results:
        best = top_results[0]
        print(
            f"Top Rooftop Site: #1 {best.name} ({best.structure_height_m:.1f} m) -> "
            f"{best.f1_pct:.1f}% F1 clear, {best.los_pct:.1f}% LOS clear (max {best.max_f1_range_m/1000.0:.2f} km).",
            flush=True,
        )
        if len(combos) >= 2:
            c_last = combos[-1]
            names_str = " + ".join(s.name for s in c_last["sites"])
            print(
                f"Best {c_last['size']}-Site Combo ({names_str}): "
                f"{c_last['cumulative_f1_pct']:.1f}% F1 clear, {c_last['cumulative_los_pct']:.1f}% LOS clear.",
                flush=True,
            )

    # Heatmap uses best #1 site (or multi-site combo if multiple sites exist -> top #1 for clear single-site reading, plus combo stored)
    heatmap_2d = (
        build_coverage_grid_2d(target_grid, top_results[0].los_mask, top_results[0].f1_mask)
        if top_results
        else np.zeros((target_grid["grid_size"], target_grid["grid_size"]), dtype=np.uint8)
    )
    combo_heatmap_2d = (
        build_coverage_grid_2d(target_grid, combos[-1]["los_mask"], combos[-1]["f1_mask"])
        if combos
        else heatmap_2d
    )

    return {
        "center_loc": center_loc,
        "radius_m": radius_m,
        "target_grid": target_grid,
        "all_results": results,
        "top_results": top_results,
        "combos": combos,
        "top1_heatmap_2d": heatmap_2d,
        "combo_heatmap_2d": combo_heatmap_2d,
    }
