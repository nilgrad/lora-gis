"""Markdown RF propagation and repeater analysis report generator."""

from typing import Dict, List, Set

from .config import LoRaGISConfig
from .dem import DEMProvider
from .rf import analyze_link_profile


def export_markdown_report(
    config: LoRaGISConfig,
    dem: DEMProvider,
    active_location_keys: List[str],
    link_results: List[Dict],
    hub_repeater_keys: Set[str],
    multi_link_mode: bool,
    enable_2hop: bool,
    zone_label: str,
    inv_transform,
    peaks_list: List,
    towns_list: List,
    peak_elevs: List[float],
    timestamp_str: str,
    png_filename: str,
    md_output_path: str,
) -> None:
    """Exports the complete Markdown RF link & repeater report to `md_output_path`."""
    from qgis.core import QgsPointXY

    loc_elev_list = dem.fetch_elevations([config.locations[k]["xy"] for k in active_location_keys])
    for k, elev_m in zip(active_location_keys, loc_elev_list):
        config.locations[k]["elev_m"] = elev_m

    route_names = " ↔ ".join(config.locations[k]["name"] for k in active_location_keys)
    freq_label = f"{config.freq_mhz:.0f}" if config.freq_mhz.is_integer() else f"{config.freq_mhz:.1f}"
    relay_ft = config.relay_height_m * 3.28084

    md_lines = [
        f"# {config.title} {freq_label} MHz LoRa (MeshCore) Relay Report — {route_names} ({timestamp_str})",
        "",
        f"![Topographic Relay Map]({png_filename})",
        "",
        "## 1. RF Link & Topology Overview",
        "",
        "| Parameter | Value |",
        "| :--- | :--- |",
        f"| **Operating Frequency** | `{config.freq_mhz:.1f} MHz` (LoRa / MeshCore, $\\lambda = {config.wavelength_m*100:.1f}\\text{{ cm}}$) |",
        f"| **Target Fresnel Clearance** | `>= {config.min_fresnel_clearance*100:.0f}%` of 1st Fresnel Zone ($F_1$), $K = 4/3$ Earth Curvature |",
        f"| **Intermediate Relay Height** | `{config.relay_height_m:.1f} m` (`{relay_ft:.1f} ft`) AGL |",
    ]

    for k in active_location_keys:
        loc = config.locations[k]
        role_label = f"{loc['name']} (Repeater Hub)" if (multi_link_mode and k in hub_repeater_keys) else loc["name"]
        md_lines.append(
            f"| **{role_label}** | `{loc['lat']:.6f}, {loc['lon']:.6f}` — "
            f"Ground Elev `{loc['elev_m']:.1f} m` (`{loc['elev_m']*3.28084:,.0f} ft`), "
            f"Mount `{loc['height_m']:.2f} m` (`{loc['height_m']*3.28084:.1f} ft`) AGL |"
        )

    for res in link_results:
        u_loc, v_loc = res["u_loc"], res["v_loc"]
        pair_name = f"{u_loc['name']} ↔ {v_loc['name']}"
        min_clr = res["direct_prof"]["min_clearance_m"]
        status_str = (
            "CLEAR"
            if res["direct_clear"]
            else f"BLOCKED BY TERRAIN ({min_clr:.1f} m / {min_clr*3.28084:.0f} ft deficit)"
        )
        md_lines.append(f"| **Direct Link ({pair_name}, `{res['dist_m']/1000.0:.2f} km`)** | {status_str} |")
        md_lines.append(
            f"| **Viable 1-Hop Sites ({pair_name})** | `{len(res['discovered_1hop'])}` "
            f"(`{u_loc['name']}` at `{u_loc['height_m']*3.28084:.0f} ft`, "
            f"`{v_loc['name']}` at `{v_loc['height_m']*3.28084:.0f} ft`) |"
        )
        if enable_2hop:
            md_lines.append(f"| **Viable 2-Hop Pairs ({pair_name})** | `{len(res['discovered_2hop'])}` |")
    md_lines.append("")

    sec_idx = 2
    for res in link_results:
        u_loc, v_loc = res["u_loc"], res["v_loc"]
        hu, hv = u_loc["height_m"], v_loc["height_m"]
        eu, ev = u_loc["elev_m"], v_loc["elev_m"]
        pair_name = f"{u_loc['name']} ↔ {v_loc['name']}"

        md_lines.extend([
            f"## {sec_idx}. {pair_name} Link Analysis (`{res['dist_m']/1000.0:.2f} km` Direct)",
            "",
            f"- **Direct Distance**: `{res['dist_m']/1000.0:.2f} km` (`{res['dist_m']*0.000621371:.2f} mi`)",
            f"- **Direct Line-of-Sight (`{hu*3.28084:.0f} ft` at {u_loc['name']} → `{hv*3.28084:.0f} ft` at {v_loc['name']})**: "
            f"**{'CLEAR' if res['direct_clear'] else 'BLOCKED BY TERRAIN'}** — Minimum terrain clearance is "
            f"`{res['direct_prof']['min_clearance_m']:.1f} m` (`{res['direct_prof']['min_clearance_m']*3.28084:.0f} ft`), "
            f"Min $F_1$ ratio `{res['direct_prof']['min_fresnel_ratio']*100:.0f}%`.",
            "",
        ])

        if res["best_2hop"] is not None:
            r1_pt, r2_pt = res["best_2hop"]["r1"], res["best_2hop"]["r2"]
            r1_ll = inv_transform.transform(QgsPointXY(*r1_pt))
            r2_ll = inv_transform.transform(QgsPointXY(*r2_pt))
            hop1_prof = analyze_link_profile(dem, config, u_loc["xy"], hu, r1_pt, config.relay_height_m, multi_link_mode)
            hop2_prof = analyze_link_profile(dem, config, r1_pt, config.relay_height_m, r2_pt, config.relay_height_m, multi_link_mode)
            hop3_prof = analyze_link_profile(dem, config, r2_pt, config.relay_height_m, v_loc["xy"], hv, multi_link_mode)
            e_r1, e_r2 = hop1_prof["end_elev_m"], hop2_prof["end_elev_m"]
            tot_2h_dist = hop1_prof["dist_m"] + hop2_prof["dist_m"] + hop3_prof["dist_m"]

            md_lines.extend([
                f"### Optimal 2-Hop Repeater Solution ({pair_name}, Solid Red Path)",
                "",
                f"| Node | Latitude, Longitude (WGS84) | {zone_label} (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
                f"| **{u_loc['name']}** | `{u_loc['lat']:.6f}, {u_loc['lon']:.6f}` | `E {u_loc['x']:.1f}, N {u_loc['y']:.1f}` | `{eu:.1f} m` (`{eu*3.28084:,.0f} ft`) | `{hu:.2f} m` (`{hu*3.28084:.0f} ft`) | `{eu+hu:.1f} m` (`{(eu+hu)*3.28084:,.0f} ft`) |",
                f"| **2-Hop Relay 1** | `{r1_ll.y():.6f}, {r1_ll.x():.6f}` | `E {r1_pt[0]:.1f}, N {r1_pt[1]:.1f}` | `{e_r1:.1f} m` (`{e_r1*3.28084:,.0f} ft`) | `{config.relay_height_m:.1f} m` (`{relay_ft:.0f} ft`) | `{e_r1+config.relay_height_m:.1f} m` (`{(e_r1+config.relay_height_m)*3.28084:,.0f} ft`) |",
                f"| **2-Hop Relay 2** | `{r2_ll.y():.6f}, {r2_ll.x():.6f}` | `E {r2_pt[0]:.1f}, N {r2_pt[1]:.1f}` | `{e_r2:.1f} m` (`{e_r2*3.28084:,.0f} ft`) | `{config.relay_height_m:.1f} m` (`{relay_ft:.0f} ft`) | `{e_r2+config.relay_height_m:.1f} m` (`{(e_r2+config.relay_height_m)*3.28084:,.0f} ft`) |",
                f"| **{v_loc['name']}** | `{v_loc['lat']:.6f}, {v_loc['lon']:.6f}` | `E {v_loc['x']:.1f}, N {v_loc['y']:.1f}` | `{ev:.1f} m` (`{ev*3.28084:,.0f} ft`) | `{hv:.2f} m` (`{hv*3.28084:.0f} ft`) | `{ev+hv:.1f} m` (`{(ev+hv)*3.28084:,.0f} ft`) |",
                "",
                f"| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | {freq_label} MHz Free-Space Path Loss (FSPL) |",
                "| :--- | :--- | :--- | :--- | :--- |",
                f"| **Hop 1: {u_loc['name']} → Relay 1** | `{hop1_prof['dist_m']/1000.0:.2f} km` (`{hop1_prof['dist_m']*0.000621371:.2f} mi`) | `{hop1_prof['min_clearance_m']:.1f} m` (`{hop1_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop1_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop1_prof['fspl_db']:.1f} dB` |",
                f"| **Hop 2: Relay 1 → Relay 2** | `{hop2_prof['dist_m']/1000.0:.2f} km` (`{hop2_prof['dist_m']*0.000621371:.2f} mi`) | `{hop2_prof['min_clearance_m']:.1f} m` (`{hop2_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop2_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop2_prof['fspl_db']:.1f} dB` |",
                f"| **Hop 3: Relay 2 → {v_loc['name']}** | `{hop3_prof['dist_m']/1000.0:.2f} km` (`{hop3_prof['dist_m']*0.000621371:.2f} mi`) | `{hop3_prof['min_clearance_m']:.1f} m` (`{hop3_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop3_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop3_prof['fspl_db']:.1f} dB` |",
                f"| **Total 2-Hop Link** | **`{tot_2h_dist/1000.0:.2f} km`** (`{tot_2h_dist*0.000621371:.2f} mi`, `+{(tot_2h_dist/res['dist_m'] - 1.0)*100:.1f}%`) | `{min(hop1_prof['min_clearance_m'], hop2_prof['min_clearance_m'], hop3_prof['min_clearance_m']):.1f} m` worst-case | **`{min(hop1_prof['min_fresnel_ratio'], hop2_prof['min_fresnel_ratio'], hop3_prof['min_fresnel_ratio'])*100:.0f}%`** worst-case | Max hop: `{max(hop1_prof['fspl_db'], hop2_prof['fspl_db'], hop3_prof['fspl_db']):.1f} dB` |",
                "",
            ])

        if res["best_1hop"] is not None:
            oh_pt = res["best_1hop"]["relay"]
            oh_ll = inv_transform.transform(QgsPointXY(*oh_pt))
            oh_leg1 = analyze_link_profile(dem, config, u_loc["xy"], hu, oh_pt, config.relay_height_m, multi_link_mode)
            oh_leg2 = analyze_link_profile(dem, config, oh_pt, config.relay_height_m, v_loc["xy"], hv, multi_link_mode)
            e_oh = oh_leg1["end_elev_m"]
            tot_1h_dist = oh_leg1["dist_m"] + oh_leg2["dist_m"]

            md_lines.extend([
                f"### Optimal 1-Hop Single-Repeater Solution ({pair_name}, Dashed Blue Path)",
                "",
                f"| Node | Latitude, Longitude (WGS84) | {zone_label} (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
                f"| **{u_loc['name']}** | `{u_loc['lat']:.6f}, {u_loc['lon']:.6f}` | `E {u_loc['x']:.1f}, N {u_loc['y']:.1f}` | `{eu:.1f} m` (`{eu*3.28084:,.0f} ft`) | `{hu:.2f} m` (`{hu*3.28084:.0f} ft`) | `{eu+hu:.1f} m` (`{(eu+hu)*3.28084:,.0f} ft`) |",
                f"| **1-Hop Relay ({pair_name})** | `{oh_ll.y():.6f}, {oh_ll.x():.6f}` | `E {oh_pt[0]:.1f}, N {oh_pt[1]:.1f}` | `{e_oh:.1f} m` (`{e_oh*3.28084:,.0f} ft`) | `{config.relay_height_m:.1f} m` (`{relay_ft:.0f} ft`) | `{e_oh+config.relay_height_m:.1f} m` (`{(e_oh+config.relay_height_m)*3.28084:,.0f} ft`) |",
                f"| **{v_loc['name']}** | `{v_loc['lat']:.6f}, {v_loc['lon']:.6f}` | `E {v_loc['x']:.1f}, N {v_loc['y']:.1f}` | `{ev:.1f} m` (`{ev*3.28084:,.0f} ft`) | `{hv:.2f} m` (`{hv*3.28084:.0f} ft`) | `{ev+hv:.1f} m` (`{(ev+hv)*3.28084:,.0f} ft`) |",
                "",
                f"| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | {freq_label} MHz Free-Space Path Loss (FSPL) |",
                "| :--- | :--- | :--- | :--- | :--- |",
                f"| **Leg 1: {u_loc['name']} (`{hu*3.28084:.0f} ft`) → Relay** | `{oh_leg1['dist_m']/1000.0:.2f} km` (`{oh_leg1['dist_m']*0.000621371:.2f} mi`) | `{oh_leg1['min_clearance_m']:.1f} m` (`{oh_leg1['min_clearance_m']*3.28084:.0f} ft`) | **`{oh_leg1['min_fresnel_ratio']*100:.0f}%`** | `{oh_leg1['fspl_db']:.1f} dB` |",
                f"| **Leg 2: Relay → {v_loc['name']} (`{hv*3.28084:.0f} ft`)** | `{oh_leg2['dist_m']/1000.0:.2f} km` (`{oh_leg2['dist_m']*0.000621371:.2f} mi`) | `{oh_leg2['min_clearance_m']:.1f} m` (`{oh_leg2['min_clearance_m']*3.28084:.0f} ft`) | **`{oh_leg2['min_fresnel_ratio']*100:.0f}%`** | `{oh_leg2['fspl_db']:.1f} dB` |",
                f"| **Total 1-Hop Link ({pair_name})** | **`{tot_1h_dist/1000.0:.2f} km`** (`{tot_1h_dist*0.000621371:.2f} mi`, `+{(tot_1h_dist/res['dist_m'] - 1.0)*100:.1f}%`) | `{min(oh_leg1['min_clearance_m'], oh_leg2['min_clearance_m']):.1f} m` worst-case | **`{min(oh_leg1['min_fresnel_ratio'], oh_leg2['min_fresnel_ratio'])*100:.0f}%`** worst-case | Max leg: `{max(oh_leg1['fspl_db'], oh_leg2['fspl_db']):.1f} dB` |",
                "",
            ])

        for tbl in res["sensitivity_tables"]:
            md_lines.extend([
                f"### {pair_name} 1-Hop Sensitivity to {tbl['varied_name']} Repeater Height (with `{relay_ft:.0f} ft` Intermediate Relay)",
                "",
                f"| {tbl['varied_name']} Repeater Height | Visible from {u_loc['name']} | Visible from {v_loc['name']} | Viable 1-Hop Sites | Fresnel-Clear (`>= {config.min_fresnel_clearance*100:.0f}% F1`) | Best 1-Hop Relay (Lat, Lon) | Worst-Case $F_1$ (Min Clear) |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for row in tbl["rows"]:
                b_sol = row["best"]
                if b_sol is not None:
                    b_ll = inv_transform.transform(QgsPointXY(*b_sol["relay"]))
                    md_lines.append(
                        f"| **{row['label']}** | `{row['u_visible']}` | `{row['v_visible']}` | **`{row['total_1hop']}`** | **`{row['fresnel_60_count']}`** | `{b_ll.y():.6f}, {b_ll.x():.6f}` | **`{b_sol['min_fresnel']*100:.0f}%`** (`{b_sol['min_clear_m']:.1f} m`) |"
                    )
                else:
                    md_lines.append(
                        f"| **{row['label']}** | `{row['u_visible']}` | `{row['v_visible']}` | `0` | `0` | *None* | — |"
                    )
            md_lines.append("")

        if res["ranked_1hop"]:
            top_1h = res["ranked_1hop"][:10]
            oh_elevs = dem.fetch_elevations([s["relay"] for s in top_1h])
            md_lines.extend([
                f"### Top Discovered 1-Hop Candidate Sites ({pair_name})",
                "",
                f"| Rank | Relay Coordinate (Lat, Lon) | Ground Elev | Leg 1 ({u_loc['name']} → R) $F_1$ (Clear) | Leg 2 (R → {v_loc['name']}) $F_1$ (Clear) | Worst-Case $F_1$ | Total Path Length |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for idx_r, (sol, e_r) in enumerate(zip(top_1h, oh_elevs), 1):
                r_ll = inv_transform.transform(QgsPointXY(*sol["relay"]))
                md_lines.append(
                    f"| `#{idx_r}` | `{r_ll.y():.6f}, {r_ll.x():.6f}` | `{e_r:.1f} m` (`{e_r*3.28084:,.0f} ft`) | `{sol['f1_u']*100:.0f}%` (`{sol['clr_u']:.1f} m`) | `{sol['f1_v']*100:.0f}%` (`{sol['clr_v']:.1f} m`) | **`{sol['min_fresnel']*100:.0f}%`** | `{sol['total_dist']/1000.0:.2f} km` (`{sol['total_dist']*0.000621371:.2f} mi`) |"
                )
            md_lines.append("")

        if res["ranked_2hop"]:
            top_10 = res["ranked_2hop"][:10]
            top_pts = []
            for sol in top_10:
                top_pts.extend([sol["r1"], sol["r2"]])
            top_elevs = dem.fetch_elevations(top_pts)

            md_lines.extend([
                f"### Top 10 Ranked 2-Relay Solutions ({pair_name})",
                "",
                "| Rank | Relay 1 (Lat, Lon) | Relay 1 Elev | Relay 2 (Lat, Lon) | Relay 2 Elev | Worst-Case $F_1$ Clear | Min Clear (m) | Total Path Length |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for rank_idx, sol in enumerate(top_10, 1):
                p1, p2 = sol["r1"], sol["r2"]
                p1_ll = inv_transform.transform(QgsPointXY(*p1))
                p2_ll = inv_transform.transform(QgsPointXY(*p2))
                e1 = top_elevs[(rank_idx - 1) * 2]
                e2 = top_elevs[(rank_idx - 1) * 2 + 1]
                t_len = sol["total_dist"]
                md_lines.append(
                    f"| `#{rank_idx}` | `{p1_ll.y():.6f}, {p1_ll.x():.6f}` | `{e1:.0f} m` (`{e1*3.28084:,.0f} ft`) | `{p2_ll.y():.6f}, {p2_ll.x():.6f}` | `{e2:.0f} m` (`{e2*3.28084:,.0f} ft`) | **`{sol['min_fresnel']*100:.0f}%`** | `{sol['min_clear_m']:.1f} m` | `{t_len / 1000.0:.2f} km` (`{t_len * 0.000621371:.2f} mi`) |"
                )
            md_lines.append("")

        sec_idx += 1

    md_lines.extend([
        f"## {sec_idx}. Grid Resolution Scan Summary",
        "",
    ])
    if enable_2hop:
        md_lines.extend([
            "| Link | Grid Step (m) | Candidate Grid Points | Visible from Node 1 | Visible from Node 2 | Valid 1-Hop Sites | 2-Hop Pairs Evaluated | Valid 2-Hop Solutions |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for res in link_results:
            pair_name = f"{res['u_loc']['name']} ↔ {res['v_loc']['name']}"
            for st in res["step_stats"]:
                md_lines.append(
                    f"| **{pair_name}** | `{st['step_m']:.1f} m` | `{st['grid_points']}` | `{st['u_visible']}` | `{st['v_visible']}` | **`{st['one_hop_found']}`** | `{st['pairs_evaluated']}` | **`{st['valid_solutions']}`** |"
                )
    else:
        md_lines.extend([
            "| Link | Grid Step (m) | Candidate Grid Points | Visible from Node 1 | Visible from Node 2 | Valid 1-Hop Sites |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for res in link_results:
            pair_name = f"{res['u_loc']['name']} ↔ {res['v_loc']['name']}"
            for st in res["step_stats"]:
                md_lines.append(
                    f"| **{pair_name}** | `{st['step_m']:.1f} m` | `{st['grid_points']}` | `{st['u_visible']}` | `{st['v_visible']}` | **`{st['one_hop_found']}`** |"
                )
    sec_idx += 1

    if peaks_list or towns_list:
        md_lines.extend([
            "",
            f"## {sec_idx}. Surrounding Terrain Features (USGS GeoNames)",
            "",
        ])
        if peaks_list:
            md_lines.append("### Mountain Summits & Peaks")
            for (p_name, p_coords), p_elev_m in zip(peaks_list, peak_elevs):
                p_ll = inv_transform.transform(QgsPointXY(*p_coords))
                md_lines.append(
                    f"- **{p_name}**: `{p_elev_m:.0f} m` (`{p_elev_m * 3.28084:,.0f} ft`) — `{p_ll.y():.5f}, {p_ll.x():.5f}`"
                )
            md_lines.append("")
        if towns_list:
            md_lines.append("### Populated Places & Towns")
            for t_name, t_coords in towns_list:
                t_ll = inv_transform.transform(QgsPointXY(*t_coords))
                md_lines.append(f"- **{t_name}**: `{t_ll.y():.5f}, {t_ll.x():.5f}`")
            md_lines.append("")

    with open(md_output_path, "w", encoding="utf-8") as md_file:
        md_file.write("\n".join(md_lines) + "\n")

    print(f"Markdown Analysis Report exported to:                {md_output_path}", flush=True)
