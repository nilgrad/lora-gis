"""RF propagation, Line-of-Sight (LOS), Fresnel Zone, FSPL, and 1-Hop/2-Hop grid solver."""

from typing import Dict, Set, Tuple
import numpy as np

from .config import HEIGHT_SENSITIVITY_SCENARIOS, LoRaGISConfig
from .dem import DEMProvider


class _NoOpProgress:
    def setWindowModality(self, *args): pass
    def show(self): pass
    def setValue(self, *args): pass
    def setLabelText(self, *args): pass
    def wasCanceled(self): return False
    def close(self): pass


def calc_fspl_db(dist_m: float, freq_mhz: float) -> float:
    """Computes Free-Space Path Loss (dB) for a distance in meters and frequency in MHz."""
    if dist_m <= 0.0:
        return 0.0
    dist_km = dist_m / 1000.0
    return float(20.0 * np.log10(dist_km) + 20.0 * np.log10(freq_mhz) + 32.44)


def analyze_link_profile(
    dem: DEMProvider,
    config: LoRaGISConfig,
    p1: Tuple[float, float],
    h1: float,
    p2: Tuple[float, float],
    h2: float,
    multi_link_mode: bool = False,
) -> Dict:
    """
    Evaluates a single link segment (p1 -> p2) including:
      - Earth curvature + 4/3 atmospheric refraction bulge
      - Optical Line-of-Sight clearance (meters)
      - 1st Fresnel Zone radius & minimum clearance ratio (F1 %)
      - Free-Space Path Loss (FSPL in dB)
    """
    dist_m = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    num_samples = config.los_num_samples
    samples = num_samples if multi_link_mode else max(num_samples, int(round(dist_m / 25.0)))
    t = np.linspace(0.0, 1.0, samples)
    xs = p1[0] + (p2[0] - p1[0]) * t
    ys = p1[1] + (p2[1] - p1[1]) * t

    if dem.cache is not None:
        ground = dem.sample_bilinear(xs, ys)
    else:
        ground = np.array(dem.fetch_elevations(list(zip(xs, ys))), dtype=np.float64)

    if np.any(ground <= 0.0):
        return {
            "clear": False,
            "min_clearance_m": -9999.0,
            "min_fresnel_ratio": -99.0,
            "dist_m": dist_m,
            "fspl_db": calc_fspl_db(dist_m, config.freq_mhz),
            "start_elev_m": 0.0,
            "end_elev_m": 0.0,
        }

    z1 = ground[0] + h1
    z2 = ground[-1] + h2
    sightline = z1 + (z2 - z1) * t

    d1 = dist_m * t
    d2 = dist_m * (1.0 - t)
    earth_bulge = (d1 * d2) / (2.0 * config.earth_radius_eff_m)

    clearance = sightline - (ground + earth_bulge)
    interior_clear = clearance[1:-1]
    min_clearance_m = float(np.min(interior_clear))

    f1_radius = np.sqrt(config.wavelength_m * d1[1:-1] * d2[1:-1] / max(dist_m, 1.0))
    min_fresnel_ratio = float(np.min(interior_clear / np.maximum(f1_radius, 0.01)))

    return {
        "clear": min_clearance_m > 0.0,
        "min_clearance_m": min_clearance_m,
        "min_fresnel_ratio": min_fresnel_ratio,
        "dist_m": dist_m,
        "fspl_db": calc_fspl_db(dist_m, config.freq_mhz),
        "start_elev_m": float(ground[0]),
        "end_elev_m": float(ground[-1]),
    }


def evaluate_segments_vectorized(
    dem: DEMProvider,
    config: LoRaGISConfig,
    p1_arr: np.ndarray,
    h1: float,
    p2_arr: np.ndarray,
    h2: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized batch evaluation of N sightline segments against the cached DEM grid.
    Returns (los_ok_bool_array, min_clearance_m_array, min_fresnel_ratio_array).
    """
    n_segs = len(p1_arr)
    if n_segs == 0:
        return np.array([], dtype=bool), np.array([]), np.array([])

    if dem.cache is None:
        ok_list, clr_list, fr_list = [], [], []
        for i in range(n_segs):
            res = analyze_link_profile(dem, config, tuple(p1_arr[i]), h1, tuple(p2_arr[i]), h2)
            ok_list.append(res["clear"])
            clr_list.append(res["min_clearance_m"])
            fr_list.append(res["min_fresnel_ratio"])
        return np.array(ok_list, dtype=bool), np.array(clr_list), np.array(fr_list)

    t = np.linspace(0.0, 1.0, config.los_num_samples)[None, :]
    xs = p1_arr[:, 0:1] + (p2_arr[:, 0:1] - p1_arr[:, 0:1]) * t
    ys = p1_arr[:, 1:2] + (p2_arr[:, 1:2] - p1_arr[:, 1:2]) * t
    ground = dem.sample_bilinear(xs, ys)
    valid_dem = np.all(ground > 0.0, axis=1)

    z1 = ground[:, 0:1] + h1
    z2 = ground[:, -1:] + h2
    sightline = z1 + (z2 - z1) * t

    dists = np.hypot(p2_arr[:, 0] - p1_arr[:, 0], p2_arr[:, 1] - p1_arr[:, 1])[:, None]
    d1 = dists * t
    d2 = dists * (1.0 - t)
    bulge = (d1 * d2) / (2.0 * config.earth_radius_eff_m)

    clearance = sightline - (ground + bulge)
    min_clear = np.min(clearance[:, 1:-1], axis=1)

    f1_rad = np.sqrt(config.wavelength_m * d1[:, 1:-1] * d2[:, 1:-1] / np.maximum(dists, 1.0))
    fresnel_ratio = np.min(clearance[:, 1:-1] / np.maximum(f1_rad, 0.01), axis=1)

    los_ok = valid_dem & (min_clear > 0.0)
    return los_ok, min_clear, fresnel_ratio


def compute_link_padding(u_loc: Dict, v_loc: Dict, config: LoRaGISConfig) -> float:
    """Returns search padding (meters) around the (u, v) bounding box."""
    dx = abs(v_loc["x"] - u_loc["x"])
    dist = float(np.hypot(v_loc["x"] - u_loc["x"], v_loc["y"] - u_loc["y"]))
    if dx < 0.5 * dist:
        return max(config.grid_padding_m, config.narrow_axis_padding_m)
    return config.grid_padding_m


def rank_solution_key(sol: Dict, config: LoRaGISConfig, multi_link_mode: bool) -> Tuple:
    """Prioritizes solutions meeting >= min_fresnel_clearance, then shortest total path."""
    if not multi_link_mode:
        meets_fresnel = 0 if sol["min_fresnel"] >= config.min_fresnel_clearance else 1
        return (meets_fresnel, sol["total_dist"], -sol["min_fresnel"])
    if sol["min_fresnel"] >= config.min_fresnel_clearance:
        return (0, sol["total_dist"], -sol["min_fresnel"])
    return (1, -round(sol["min_fresnel"], 3), sol["total_dist"])


def analyze_link(
    u_key: str,
    v_key: str,
    config: LoRaGISConfig,
    dem: DEMProvider,
    inv_transform,
    hub_repeater_keys: Set[str],
    multi_link_mode: bool,
    allow_2hop: bool = False,
    headless_cli: bool = True,
) -> Dict:
    """Runs multi-resolution 1-hop (and optional 2-hop) relay discovery and hub height sensitivity."""
    from qgis.core import QgsPointXY
    from qgis.PyQt.QtCore import QCoreApplication, Qt
    from qgis.PyQt.QtWidgets import QProgressDialog

    u_loc = config.locations[u_key]
    v_loc = config.locations[v_key]
    ux, uy = u_loc["x"], u_loc["y"]
    vx, vy = v_loc["x"], v_loc["y"]
    hu, hv = u_loc["height_m"], v_loc["height_m"]
    dist_uv = float(np.hypot(vx - ux, vy - uy))
    pad = compute_link_padding(u_loc, v_loc, config)

    print(f"\n==========================================", flush=True)
    print(
        f"Evaluating Link: {u_loc['name']} ({hu*3.28084:.0f} ft) <-> "
        f"{v_loc['name']} ({hv*3.28084:.0f} ft) [{dist_uv/1000.0:.2f} km]...",
        flush=True,
    )
    QCoreApplication.processEvents()

    direct_prof = analyze_link_profile(dem, config, (ux, uy), hu, (vx, vy), hv, multi_link_mode)
    direct_prof_60ft_u = analyze_link_profile(
        dem, config, (ux, uy), config.relay_height_m, (vx, vy), hv, multi_link_mode
    )
    direct_clear = direct_prof["clear"]

    print(
        f"Direct {u_loc['name']} <-> {v_loc['name']}: {'CLEAR' if direct_clear else 'BLOCKED'} "
        f"(Min clearance: {direct_prof['min_clearance_m']:.1f} m / {direct_prof['min_clearance_m']*3.28084:.0f} ft)",
        flush=True,
    )

    discovered_1hop = {}
    discovered_2hop = {}
    viable_relays = set()
    step_stats = []
    combined_unique_pts = {}
    user_cancelled = False

    min_x, max_x = min(ux, vx), max(ux, vx)
    min_y, max_y = min(uy, vy), max(uy, vy)

    current_grid_step = config.initial_grid_step_m
    while current_grid_step >= config.min_grid_step_m and not user_cancelled:
        x_range = np.arange(min_x - pad, max_x + pad, current_grid_step)
        y_range = np.arange(min_y - pad, max_y + pad, current_grid_step)
        candidate_grid = [(float(x), float(y)) for x in x_range for y in y_range]
        for pt in candidate_grid:
            combined_unique_pts[(round(pt[0], 1), round(pt[1], 1))] = pt

        grid_arr = np.array(candidate_grid, dtype=np.float64)
        total_candidates = len(candidate_grid)

        progress = (
            _NoOpProgress()
            if headless_cli
            else QProgressDialog(f"{u_loc['name']} <-> {v_loc['name']} ({current_grid_step:.0f}m)", "Cancel", 0, 3)
        )
        progress.setWindowModality(getattr(Qt, "WindowModal", Qt.WindowModality.WindowModal))
        progress.show()

        progress.setValue(1)
        progress.setLabelText(f"Step {current_grid_step:.0f}m - Phase 1: {u_loc['name']} ({total_candidates} pts)")
        QCoreApplication.processEvents()
        if progress.wasCanceled():
            user_cancelled = True
            break

        pt_u_arr = np.repeat([[ux, uy]], total_candidates, axis=0)
        ok_u, clr_u, f1_u = evaluate_segments_vectorized(
            dem, config, pt_u_arr, hu, grid_arr, config.relay_height_m
        )

        progress.setValue(2)
        progress.setLabelText(f"Step {current_grid_step:.0f}m - Phase 2: {v_loc['name']} ({total_candidates} pts)")
        QCoreApplication.processEvents()
        if progress.wasCanceled():
            user_cancelled = True
            break

        pt_v_arr = np.repeat([[vx, vy]], total_candidates, axis=0)
        ok_v, clr_v, f1_v = evaluate_segments_vectorized(
            dem, config, grid_arr, config.relay_height_m, pt_v_arr, hv
        )

        one_hop_indices = np.where(ok_u & ok_v)[0]
        step_1hop_count = len(one_hop_indices)
        for idx in one_hop_indices:
            pt = candidate_grid[idx]
            viable_relays.add(pt)
            d_tot = float(np.hypot(pt[0] - ux, pt[1] - uy) + np.hypot(vx - pt[0], vy - pt[1]))
            key = (round(pt[0], 1), round(pt[1], 1))
            discovered_1hop[key] = {
                "relay": pt,
                "total_dist": d_tot,
                "min_fresnel": float(min(f1_u[idx], f1_v[idx])),
                "min_clear_m": float(min(clr_u[idx], clr_v[idx])),
                "f1_u": float(f1_u[idx]),
                "f1_v": float(f1_v[idx]),
                "clr_u": float(clr_u[idx]),
                "clr_v": float(clr_v[idx]),
            }

        r1_indices = np.where(ok_u)[0]
        r2_indices = np.where(ok_v)[0]
        total_pairs = 0
        step_2hop_count = 0

        if allow_2hop and not direct_clear and not user_cancelled and len(r1_indices) > 0 and len(r2_indices) > 0:
            r1_pts = grid_arr[r1_indices]
            r2_pts = grid_arr[r2_indices]
            d_u_r1 = np.hypot(r1_pts[:, 0] - ux, r1_pts[:, 1] - uy)
            d_r2_v = np.hypot(vx - r2_pts[:, 0], vy - r2_pts[:, 1])

            candidate_pairs_meta = []
            for i_pos, r1_idx in enumerate(r1_indices):
                p1 = r1_pts[i_pos]
                d12 = np.hypot(r2_pts[:, 0] - p1[0], r2_pts[:, 1] - p1[1])
                valid_mask = (d12 >= config.min_relay_separation_m) & (d12 <= dist_uv)
                for j_pos in np.where(valid_mask)[0]:
                    r2_idx = r2_indices[j_pos]
                    tot_d = float(d_u_r1[i_pos] + d12[j_pos] + d_r2_v[j_pos])
                    candidate_pairs_meta.append((tot_d, r1_idx, r2_idx))

            candidate_pairs_meta.sort(key=lambda x: x[0])
            candidate_pairs_meta = candidate_pairs_meta[: config.max_candidate_pairs]
            total_pairs = len(candidate_pairs_meta)

            progress.setValue(3)
            progress.setLabelText(f"Step {current_grid_step:.0f}m - Phase 3: {total_pairs} pairs")
            QCoreApplication.processEvents()

            if total_pairs > 0 and not progress.wasCanceled():
                p1_batch = np.array([candidate_grid[m[1]] for m in candidate_pairs_meta], dtype=np.float64)
                p2_batch = np.array([candidate_grid[m[2]] for m in candidate_pairs_meta], dtype=np.float64)
                ok_12, clr_12, f1_12 = evaluate_segments_vectorized(
                    dem, config, p1_batch, config.relay_height_m, p2_batch, config.relay_height_m
                )

                for p_i in np.where(ok_12)[0]:
                    tot_d, r1_idx, r2_idx = candidate_pairs_meta[p_i]
                    r1_pt = candidate_grid[r1_idx]
                    r2_pt = candidate_grid[r2_idx]
                    viable_relays.add(r1_pt)
                    viable_relays.add(r2_pt)
                    step_2hop_count += 1
                    pair_key = (round(r1_pt[0], 1), round(r1_pt[1], 1), round(r2_pt[0], 1), round(r2_pt[1], 1))
                    discovered_2hop[pair_key] = {
                        "r1": r1_pt,
                        "r2": r2_pt,
                        "total_dist": tot_d,
                        "min_fresnel": float(min(f1_u[r1_idx], f1_12[p_i], f1_v[r2_idx])),
                        "min_clear_m": float(min(clr_u[r1_idx], clr_12[p_i], clr_v[r2_idx])),
                        "f1_u": float(f1_u[r1_idx]),
                        "f1_12": float(f1_12[p_i]),
                        "f1_v": float(f1_v[r2_idx]),
                    }

            print(
                f"  [Step {current_grid_step:.1f}m] Grid: {total_candidates} pts | "
                f"Vis {u_loc['name']}: {len(r1_indices)} | Vis {v_loc['name']}: {len(r2_indices)} | "
                f"1-Hop: {step_1hop_count} | 2-Hop: {step_2hop_count}",
                flush=True,
            )
        else:
            print(
                f"  [Step {current_grid_step:.1f}m] Grid: {total_candidates} pts | "
                f"Vis {u_loc['name']} ({hu*3.28084:.0f}ft): {len(r1_indices)} | "
                f"Vis {v_loc['name']} ({hv*3.28084:.0f}ft): {len(r2_indices)} | "
                f"1-Hop found: {step_1hop_count}",
                flush=True,
            )

        if not user_cancelled:
            step_stats.append({
                "step_m": current_grid_step,
                "grid_points": total_candidates,
                "u_visible": len(r1_indices),
                "v_visible": len(r2_indices),
                "one_hop_found": step_1hop_count,
                "pairs_evaluated": total_pairs,
                "valid_solutions": step_2hop_count,
            })

        progress.close()
        current_grid_step *= config.step_factor

    ranked_1hop = sorted(discovered_1hop.values(), key=lambda s: rank_solution_key(s, config, multi_link_mode))
    best_1hop = ranked_1hop[0] if ranked_1hop else None
    if best_1hop is not None:
        r_ll = inv_transform.transform(QgsPointXY(*best_1hop["relay"]))
        print(
            f"Optimal 1-Hop Repeater ({u_loc['name']} <-> {v_loc['name']}): "
            f"Lat {r_ll.y():.6f}, Lon {r_ll.x():.6f} "
            f"(Path: {best_1hop['total_dist']/1000.0:.2f} km, Min F1: {best_1hop['min_fresnel']*100:.0f}%)",
            flush=True,
        )

    ranked_2hop = sorted(discovered_2hop.values(), key=lambda s: rank_solution_key(s, config, multi_link_mode))
    best_2hop = ranked_2hop[0] if ranked_2hop else None
    if best_2hop is not None:
        r1_ll = inv_transform.transform(QgsPointXY(*best_2hop["r1"]))
        r2_ll = inv_transform.transform(QgsPointXY(*best_2hop["r2"]))
        print(
            f"Optimal 2-Hop Repeater Pair ({u_loc['name']} <-> {v_loc['name']}, "
            f"{best_2hop['total_dist']/1000.0:.2f} km, Min F1: {best_2hop['min_fresnel']*100:.0f}%):",
            flush=True,
        )
        print(f"  Relay 1: Lat {r1_ll.y():.6f}, Lon {r1_ll.x():.6f}", flush=True)
        print(f"  Relay 2: Lat {r2_ll.y():.6f}, Lon {r2_ll.x():.6f}", flush=True)

    sensitivity_tables = []
    if multi_link_mode and not user_cancelled:
        full_list = list(combined_unique_pts.values())
        full_arr = np.array(full_list, dtype=np.float64)
        pt_u_full = np.repeat([[ux, uy]], len(full_list), axis=0)
        pt_v_full = np.repeat([[vx, vy]], len(full_list), axis=0)

        hub_targets = []
        if u_key in hub_repeater_keys:
            hub_targets.append(("u", u_key, u_loc, v_loc))
        if v_key in hub_repeater_keys:
            hub_targets.append(("v", v_key, v_loc, u_loc))
        if not hub_targets:
            hub_targets.append(("u", u_key, u_loc, v_loc))

        for side, h_key, varied_loc, fixed_loc in hub_targets:
            rows = []
            if side == "u":
                ok_fixed, clr_fixed, f1_fixed = evaluate_segments_vectorized(
                    dem, config, full_arr, config.relay_height_m, pt_v_full, hv
                )
            else:
                ok_fixed, clr_fixed, f1_fixed = evaluate_segments_vectorized(
                    dem, config, pt_u_full, hu, full_arr, config.relay_height_m
                )

            for s_label, h_val in HEIGHT_SENSITIVITY_SCENARIOS:
                if side == "u":
                    ok_var, clr_var, f1_var = evaluate_segments_vectorized(
                        dem, config, pt_u_full, h_val, full_arr, config.relay_height_m
                    )
                    ok_u_s, clr_u_s, f1_u_s = ok_var, clr_var, f1_var
                    ok_v_s, clr_v_s, f1_v_s = ok_fixed, clr_fixed, f1_fixed
                else:
                    ok_var, clr_var, f1_var = evaluate_segments_vectorized(
                        dem, config, full_arr, config.relay_height_m, pt_v_full, h_val
                    )
                    ok_u_s, clr_u_s, f1_u_s = ok_fixed, clr_fixed, f1_fixed
                    ok_v_s, clr_v_s, f1_v_s = ok_var, clr_var, f1_var

                both_idx = np.where(ok_u_s & ok_v_s)[0]
                sols = []
                for idx in both_idx:
                    pt = full_list[idx]
                    d_tot = float(np.hypot(pt[0] - ux, pt[1] - uy) + np.hypot(vx - pt[0], vy - pt[1]))
                    sols.append({
                        "relay": pt,
                        "total_dist": d_tot,
                        "min_fresnel": float(min(f1_u_s[idx], f1_v_s[idx])),
                        "min_clear_m": float(min(clr_u_s[idx], clr_v_s[idx])),
                        "f1_u": float(f1_u_s[idx]),
                        "f1_v": float(f1_v_s[idx]),
                        "clr_u": float(clr_u_s[idx]),
                        "clr_v": float(clr_v_s[idx]),
                    })
                sols.sort(key=lambda s: rank_solution_key(s, config, multi_link_mode))
                rows.append({
                    "label": f"{s_label} at {varied_loc['name']}",
                    "h_m": h_val,
                    "u_visible": int(np.sum(ok_u_s)),
                    "v_visible": int(np.sum(ok_v_s)),
                    "total_1hop": len(sols),
                    "fresnel_60_count": sum(1 for s in sols if s["min_fresnel"] >= config.min_fresnel_clearance),
                    "best": sols[0] if sols else None,
                })
            sensitivity_tables.append({
                "varied_key": h_key,
                "varied_name": varied_loc["name"],
                "fixed_name": fixed_loc["name"],
                "rows": rows,
            })

    return {
        "u_key": u_key,
        "v_key": v_key,
        "u_loc": u_loc,
        "v_loc": v_loc,
        "dist_m": dist_uv,
        "direct_prof": direct_prof,
        "direct_prof_60ft_u": direct_prof_60ft_u,
        "direct_clear": direct_clear,
        "discovered_1hop": discovered_1hop,
        "ranked_1hop": ranked_1hop,
        "best_1hop": best_1hop,
        "discovered_2hop": discovered_2hop,
        "ranked_2hop": ranked_2hop,
        "best_2hop": best_2hop,
        "viable_relays": viable_relays,
        "step_stats": step_stats,
        "sensitivity_tables": sensitivity_tables,
        "user_cancelled": user_cancelled,
    }
