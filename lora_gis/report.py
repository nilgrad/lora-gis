"""Markdown RF propagation and repeater analysis report generator."""

from typing import Dict, List, Optional, Set

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
    candidate_keys: Optional[List[str]] = None,
    profiles_filename: Optional[str] = None,
    buildings: Optional[List] = None,
) -> None:
    """Exports the complete Markdown RF link & repeater report to `md_output_path`."""
    from qgis.core import QgsPointXY

    loc_elev_list = dem.fetch_elevations([config.locations[k]["xy"] for k in active_location_keys])
    for k, elev_m in zip(active_location_keys, loc_elev_list):
        config.locations[k]["elev_m"] = elev_m

    route_names = " ↔ ".join(config.locations[k]["name"] for k in active_location_keys)
    freq_label = f"{config.freq_mhz:.0f}" if config.freq_mhz.is_integer() else f"{config.freq_mhz:.1f}"
    relay_ft = config.relay_height_m * 3.28084

    surface_kind = config.surface_kind_label
    surface_desc = (
        f"{surface_kind} (nearest-neighbor, `{config.effective_sample_step_m:.1f} m` ray step, "
        f"`{config.effective_rooftop_margin_m:.1f} m` rooftop margin)"
        if config.is_dsm_mode
        else "Bare-earth DEM (bilinear interpolation)"
    )
    if config.dem_units.strip().lower() not in ("m", "meter", "meters"):
        surface_desc += f", input units `{config.dem_units}`"

    b_src_labels = {
        "osm": "OpenStreetMap",
        "overture": "Overture Maps",
        "hybrid": "Overture Maps + OpenStreetMap",
    }
    b_src_label = b_src_labels.get(config.buildings_source.strip().lower(), "Building Overlay")

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
        f"| **Surface Model** | {surface_desc} |",
        f"| **Intermediate Relay Height** | `{config.relay_height_m:.1f} m` (`{relay_ft:.1f} ft`) AGL |",
    ]

    if buildings:
        tall_cnt = sum(1 for b in buildings if b.height_m >= 15.0)
        max_bh = max((b.height_m for b in buildings), default=0.0)
        md_lines.append(
            f"| **Building Overlay** | {b_src_label} (`{len(buildings):,}` structures, "
            f"`{tall_cnt}` >= 15 m, max height `{max_bh:.1f} m` / `{max_bh*3.28084:.0f} ft`) |"
        )

    for k in active_location_keys:
        loc = config.locations[k]
        role_label = f"{loc['name']} (Repeater Hub)" if (multi_link_mode and k in hub_repeater_keys) else loc["name"]
        md_lines.append(
            f"| **{role_label}** | `{loc['lat']:.6f}, {loc['lon']:.6f}` — "
            f"Ground Elev `{loc['elev_m']:.1f} m` (`{loc['elev_m']*3.28084:,.0f} ft`), "
            f"Mount `{loc['height_m']:.2f} m` (`{loc['height_m']*3.28084:.1f} ft`) AGL |"
        )

    if candidate_keys:
        cand_elev_list = dem.fetch_elevations([config.locations[k]["xy"] for k in candidate_keys])
        for k, c_elev_m in zip(candidate_keys, cand_elev_list):
            loc = config.locations[k]
            loc["elev_m"] = c_elev_m
            extra_parts = []
            if loc.get("building_height_m"):
                bh_m = float(loc["building_height_m"])
                extra_parts.append(f"Structure `{bh_m:.1f} m` (`{bh_m*3.28084:.0f} ft`)")
            if loc.get("address"):
                extra_parts.append(f"Address `{loc['address']}`")
            extra_str = (", " + ", ".join(extra_parts)) if extra_parts else ""
            md_lines.append(
                f"| **{loc['name']} (Candidate Relay)** | `{loc['lat']:.6f}, {loc['lon']:.6f}`, "
                f"Ground Elev `{c_elev_m:.1f} m` (`{c_elev_m*3.28084:,.0f} ft`){extra_str}, "
                f"Mount `{loc['height_m']:.2f} m` (`{loc['height_m']*3.28084:.1f} ft`) |"
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
            r1_h = res["best_2hop"].get("r1_height_m", config.relay_height_m)
            r2_h = res["best_2hop"].get("r2_height_m", config.relay_height_m)
            r1_name = res["best_2hop"].get("r1_name") or "2-Hop Relay 1"
            r2_name = res["best_2hop"].get("r2_name") or "2-Hop Relay 2"
            if r1_name == "Grid Relay":
                r1_name = "2-Hop Relay 1 (Grid)"
            if r2_name == "Grid Relay":
                r2_name = "2-Hop Relay 2 (Grid)"
            r1_ll = inv_transform.transform(QgsPointXY(*r1_pt))
            r2_ll = inv_transform.transform(QgsPointXY(*r2_pt))
            hop1_prof = analyze_link_profile(dem, config, u_loc["xy"], hu, r1_pt, r1_h, multi_link_mode)
            hop2_prof = analyze_link_profile(dem, config, r1_pt, r1_h, r2_pt, r2_h, multi_link_mode)
            hop3_prof = analyze_link_profile(dem, config, r2_pt, r2_h, v_loc["xy"], hv, multi_link_mode)
            e_r1, e_r2 = hop1_prof["end_elev_m"], hop2_prof["end_elev_m"]
            tot_2h_dist = hop1_prof["dist_m"] + hop2_prof["dist_m"] + hop3_prof["dist_m"]

            md_lines.extend([
                f"### Optimal 2-Hop Repeater Solution ({pair_name}, Solid Red Path)",
                "",
                f"| Node | Latitude, Longitude (WGS84) | {zone_label} (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
                f"| **{u_loc['name']}** | `{u_loc['lat']:.6f}, {u_loc['lon']:.6f}` | `E {u_loc['x']:.1f}, N {u_loc['y']:.1f}` | `{eu:.1f} m` (`{eu*3.28084:,.0f} ft`) | `{hu:.2f} m` (`{hu*3.28084:.0f} ft`) | `{eu+hu:.1f} m` (`{(eu+hu)*3.28084:,.0f} ft`) |",
                f"| **{r1_name}** | `{r1_ll.y():.6f}, {r1_ll.x():.6f}` | `E {r1_pt[0]:.1f}, N {r1_pt[1]:.1f}` | `{e_r1:.1f} m` (`{e_r1*3.28084:,.0f} ft`) | `{r1_h:.1f} m` (`{r1_h*3.28084:.0f} ft`) | `{e_r1+r1_h:.1f} m` (`{(e_r1+r1_h)*3.28084:,.0f} ft`) |",
                f"| **{r2_name}** | `{r2_ll.y():.6f}, {r2_ll.x():.6f}` | `E {r2_pt[0]:.1f}, N {r2_pt[1]:.1f}` | `{e_r2:.1f} m` (`{e_r2*3.28084:,.0f} ft`) | `{r2_h:.1f} m` (`{r2_h*3.28084:.0f} ft`) | `{e_r2+r2_h:.1f} m` (`{(e_r2+r2_h)*3.28084:,.0f} ft`) |",
                f"| **{v_loc['name']}** | `{v_loc['lat']:.6f}, {v_loc['lon']:.6f}` | `E {v_loc['x']:.1f}, N {v_loc['y']:.1f}` | `{ev:.1f} m` (`{ev*3.28084:,.0f} ft`) | `{hv:.2f} m` (`{hv*3.28084:.0f} ft`) | `{ev+hv:.1f} m` (`{(ev+hv)*3.28084:,.0f} ft`) |",
                "",
                f"| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | {freq_label} MHz Free-Space Path Loss (FSPL) |",
                "| :--- | :--- | :--- | :--- | :--- |",
                f"| **Hop 1: {u_loc['name']} → {r1_name}** | `{hop1_prof['dist_m']/1000.0:.2f} km` (`{hop1_prof['dist_m']*0.000621371:.2f} mi`) | `{hop1_prof['min_clearance_m']:.1f} m` (`{hop1_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop1_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop1_prof['fspl_db']:.1f} dB` |",
                f"| **Hop 2: {r1_name} → {r2_name}** | `{hop2_prof['dist_m']/1000.0:.2f} km` (`{hop2_prof['dist_m']*0.000621371:.2f} mi`) | `{hop2_prof['min_clearance_m']:.1f} m` (`{hop2_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop2_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop2_prof['fspl_db']:.1f} dB` |",
                f"| **Hop 3: {r2_name} → {v_loc['name']}** | `{hop3_prof['dist_m']/1000.0:.2f} km` (`{hop3_prof['dist_m']*0.000621371:.2f} mi`) | `{hop3_prof['min_clearance_m']:.1f} m` (`{hop3_prof['min_clearance_m']*3.28084:.0f} ft`) | **`{hop3_prof['min_fresnel_ratio']*100:.0f}%`** | `{hop3_prof['fspl_db']:.1f} dB` |",
                f"| **Total 2-Hop Link** | **`{tot_2h_dist/1000.0:.2f} km`** (`{tot_2h_dist*0.000621371:.2f} mi`, `+{(tot_2h_dist/res['dist_m'] - 1.0)*100:.1f}%`) | `{min(hop1_prof['min_clearance_m'], hop2_prof['min_clearance_m'], hop3_prof['min_clearance_m']):.1f} m` worst-case | **`{min(hop1_prof['min_fresnel_ratio'], hop2_prof['min_fresnel_ratio'], hop3_prof['min_fresnel_ratio'])*100:.0f}%`** worst-case | Max hop: `{max(hop1_prof['fspl_db'], hop2_prof['fspl_db'], hop3_prof['fspl_db']):.1f} dB` |",
                "",
            ])

        if res["best_1hop"] is not None:
            oh_pt = res["best_1hop"]["relay"]
            oh_h = res["best_1hop"].get("relay_height_m", config.relay_height_m)
            oh_name = res["best_1hop"].get("candidate_name") or f"1-Hop Relay ({pair_name})"
            oh_ll = inv_transform.transform(QgsPointXY(*oh_pt))
            oh_leg1 = analyze_link_profile(dem, config, u_loc["xy"], hu, oh_pt, oh_h, multi_link_mode)
            oh_leg2 = analyze_link_profile(dem, config, oh_pt, oh_h, v_loc["xy"], hv, multi_link_mode)
            e_oh = oh_leg1["end_elev_m"]
            tot_1h_dist = oh_leg1["dist_m"] + oh_leg2["dist_m"]

            md_lines.extend([
                f"### Optimal 1-Hop Single-Repeater Solution ({pair_name}, Dashed Blue Path)",
                "",
                f"| Node | Latitude, Longitude (WGS84) | {zone_label} (E, N) | Ground Elevation | Mount Height (AGL) | Total Tip Elevation (ASL) |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
                f"| **{u_loc['name']}** | `{u_loc['lat']:.6f}, {u_loc['lon']:.6f}` | `E {u_loc['x']:.1f}, N {u_loc['y']:.1f}` | `{eu:.1f} m` (`{eu*3.28084:,.0f} ft`) | `{hu:.2f} m` (`{hu*3.28084:.0f} ft`) | `{eu+hu:.1f} m` (`{(eu+hu)*3.28084:,.0f} ft`) |",
                f"| **{oh_name}** | `{oh_ll.y():.6f}, {oh_ll.x():.6f}` | `E {oh_pt[0]:.1f}, N {oh_pt[1]:.1f}` | `{e_oh:.1f} m` (`{e_oh*3.28084:,.0f} ft`) | `{oh_h:.1f} m` (`{oh_h*3.28084:.0f} ft`) | `{e_oh+oh_h:.1f} m` (`{(e_oh+oh_h)*3.28084:,.0f} ft`) |",
                f"| **{v_loc['name']}** | `{v_loc['lat']:.6f}, {v_loc['lon']:.6f}` | `E {v_loc['x']:.1f}, N {v_loc['y']:.1f}` | `{ev:.1f} m` (`{ev*3.28084:,.0f} ft`) | `{hv:.2f} m` (`{hv*3.28084:.0f} ft`) | `{ev+hv:.1f} m` (`{(ev+hv)*3.28084:,.0f} ft`) |",
                "",
                f"| Hop Segment | Distance | Min Terrain Clearance | Min 1st Fresnel ($F_1$) Clearance | {freq_label} MHz Free-Space Path Loss (FSPL) |",
                "| :--- | :--- | :--- | :--- | :--- |",
                f"| **Leg 1: {u_loc['name']} (`{hu*3.28084:.0f} ft`) → Relay** | `{oh_leg1['dist_m']/1000.0:.2f} km` (`{oh_leg1['dist_m']*0.000621371:.2f} mi`) | `{oh_leg1['min_clearance_m']:.1f} m` (`{oh_leg1['min_clearance_m']*3.28084:.0f} ft`) | **`{oh_leg1['min_fresnel_ratio']*100:.0f}%`** | `{oh_leg1['fspl_db']:.1f} dB` |",
                f"| **Leg 2: Relay → {v_loc['name']} (`{hv*3.28084:.0f} ft`)** | `{oh_leg2['dist_m']/1000.0:.2f} km` (`{oh_leg2['dist_m']*0.000621371:.2f} mi`) | `{oh_leg2['min_clearance_m']:.1f} m` (`{oh_leg2['min_clearance_m']*3.28084:.0f} ft`) | **`{oh_leg2['min_fresnel_ratio']*100:.0f}%`** | `{oh_leg2['fspl_db']:.1f} dB` |",
                f"| **Total 1-Hop Link ({pair_name})** | **`{tot_1h_dist/1000.0:.2f} km`** (`{tot_1h_dist*0.000621371:.2f} mi`, `+{(tot_1h_dist/res['dist_m'] - 1.0)*100:.1f}%`) | `{min(oh_leg1['min_clearance_m'], oh_leg2['min_clearance_m']):.1f} m` worst-case | **`{min(oh_leg1['min_fresnel_ratio'], oh_leg2['min_fresnel_ratio'])*100:.0f}%`** worst-case | Max leg: `{max(oh_leg1['fspl_db'], oh_leg2['fspl_db']):.1f} dB` |",
                "",
            ])

        if res.get("explicit_candidates"):
            md_lines.extend([
                f"### Explicit Candidate Relay Evaluation ({pair_name})",
                "",
            ])
            if profiles_filename:
                md_lines.extend([
                    f"![Candidate Terrain & Line-of-Sight Profiles]({profiles_filename})",
                    "",
                ])
            md_lines.extend([
                f"| Candidate Site | Coordinates (Lat, Lon) | Ground Elev | Mount (AGL) | Leg 1 ({u_loc['name']} → C) | Leg 2 (C → {v_loc['name']}) | 1-Hop Verdict | Total Path |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for ec in res["explicit_candidates"]:
                l1, l2 = ec["leg1"], ec["leg2"]
                l1_tag = (
                    f"CLEAR: `{l1['min_fresnel_ratio']*100:.0f}%` F1 (`{l1['min_clearance_m']:.1f} m`, `{l1['dist_m']/1000.0:.2f} km`, `{l1['fspl_db']:.1f} dB`)"
                    if l1["clear"]
                    else f"BLOCKED (`{l1['min_clearance_m']:.1f} m`, `{l1['dist_m']/1000.0:.2f} km`)"
                )
                l2_tag = (
                    f"CLEAR: `{l2['min_fresnel_ratio']*100:.0f}%` F1 (`{l2['min_clearance_m']:.1f} m`, `{l2['dist_m']/1000.0:.2f} km`, `{l2['fspl_db']:.1f} dB`)"
                    if l2["clear"]
                    else f"BLOCKED (`{l2['min_clearance_m']:.1f} m`, `{l2['dist_m']/1000.0:.2f} km`)"
                )
                verdict = (
                    f"**VIABLE (`{ec['min_fresnel']*100:.0f}%` F1)**"
                    if ec["viable"]
                    else f"BLOCKED (`{ec['min_clear_m']:.1f} m`)"
                )
                md_lines.append(
                    f"| **{ec['name']}** | `{ec['lat']:.6f}, {ec['lon']:.6f}` | `{ec['elev_m']:.1f} m` (`{ec['elev_m']*3.28084:,.0f} ft`) | "
                    f"`{ec['height_m']:.2f} m` (`{ec['height_m']*3.28084:.0f} ft`) | {l1_tag} | {l2_tag} | {verdict} | "
                    f"`{ec['total_dist']/1000.0:.2f} km` |"
                )
            md_lines.append("")

        if res.get("explicit_sensitivity"):
            for es_tbl in res["explicit_sensitivity"]:
                cand_names = [c["name"] for c in es_tbl["rows"][0]["candidates"]]
                header_cols = " | ".join(cand_names)
                sep_cols = " | ".join(":---" for _ in cand_names)
                md_lines.extend([
                    f"### Explicit Candidate Sensitivity to {es_tbl['varied_name']} Repeater Height",
                    "",
                    f"| {es_tbl['varied_name']} Height | {header_cols} |",
                    f"| :--- | {sep_cols} |",
                ])
                for row in es_tbl["rows"]:
                    cells = []
                    for c_res in row["candidates"]:
                        if c_res["viable"]:
                            cells.append(f"**VIABLE `{c_res['min_fresnel']*100:.0f}%` F1** (`{c_res['min_clear_m']:.1f} m`)")
                        else:
                            l1_s = "L1 OK" if c_res["leg1_clear"] else "L1 blk"
                            l2_s = "L2 OK" if c_res["leg2_clear"] else "L2 blk"
                            cells.append(f"Blocked ({l1_s}, {l2_s}; `{c_res['min_clear_m']:.1f} m`)")
                    md_lines.append(f"| **{row['label']}** | {' | '.join(cells)} |")
                md_lines.append("")

        if res.get("explicit_2hop_pairs"):
            viable_pairs = [p for p in res["explicit_2hop_pairs"] if p["viable"]]
            display_pairs = viable_pairs if viable_pairs else res["explicit_2hop_pairs"][:6]
            md_lines.extend([
                f"### Explicit Candidate 2-Hop Pair Evaluation ({pair_name})",
                "",
                f"| Relay 1 -> Relay 2 | Hop 1 ({u_loc['name']} → R1) | Hop 2 (R1 → R2) | Hop 3 (R2 → {v_loc['name']}) | Verdict | Total Path |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for p in display_pairs:
                h1, h2, h3 = p["hop1"], p["hop2"], p["hop3"]
                h1_s = f"CLEAR `{h1['min_fresnel_ratio']*100:.0f}%`" if h1["clear"] else f"BLK `{h1['min_clearance_m']:.1f} m`"
                h2_s = f"CLEAR `{h2['min_fresnel_ratio']*100:.0f}%`" if h2["clear"] else f"BLK `{h2['min_clearance_m']:.1f} m`"
                h3_s = f"CLEAR `{h3['min_fresnel_ratio']*100:.0f}%`" if h3["clear"] else f"BLK `{h3['min_clearance_m']:.1f} m`"
                v_s = f"**VIABLE (`{p['min_fresnel']*100:.0f}%` F1)**" if p["viable"] else f"Blocked (`{p['min_clear_m']:.1f} m`)"
                md_lines.append(
                    f"| **{p['c1_name']}** → **{p['c2_name']}** | {h1_s} | {h2_s} | {h3_s} | {v_s} | `{p['total_dist']/1000.0:.2f} km` |"
                )
            md_lines.append("")

        if res.get("hybrid_2hop"):
            top_hyb = res["hybrid_2hop"][:10]
            md_lines.extend([
                f"### Top Hybrid 2-Hop Solutions (1 Explicit Candidate + 1 Grid Relay, {pair_name})",
                "",
                "| Rank | Relay 1 | Relay 2 | Hop 1 $F_1$ | Hop 2 $F_1$ | Hop 3 $F_1$ | Worst-Case $F_1$ | Total Path |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for h_idx, sol in enumerate(top_hyb, 1):
                p1_ll = inv_transform.transform(QgsPointXY(*sol["r1"]))
                p2_ll = inv_transform.transform(QgsPointXY(*sol["r2"]))
                r1_desc = f"**{sol['r1_name']}**" if sol["r1_name"] != "Grid Relay" else f"Grid (`{p1_ll.y():.5f}, {p1_ll.x():.5f}`)"
                r2_desc = f"**{sol['r2_name']}**" if sol["r2_name"] != "Grid Relay" else f"Grid (`{p2_ll.y():.5f}, {p2_ll.x():.5f}`)"
                md_lines.append(
                    f"| `#{h_idx}` | {r1_desc} | {r2_desc} | `{sol['f1_u']*100:.0f}%` | `{sol['f1_12']*100:.0f}%` | `{sol['f1_v']*100:.0f}%` | "
                    f"**`{sol['min_fresnel']*100:.0f}%`** (`{sol['min_clear_m']:.1f} m`) | `{sol['total_dist']/1000.0:.2f} km` |"
                )
            md_lines.append("")

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
        is_ca_geonames = config.is_canada_dem or any(
            config.locations.get(k, {}).get("country") == "CA" for k in active_location_keys
        )
        geonames_label = "NRCan CGNDB GeoNames" if is_ca_geonames else "USGS GeoNames"
        md_lines.extend([
            "",
            f"## {sec_idx}. Surrounding Terrain Features ({geonames_label})",
            "",
        ])
        if peaks_list:
            md_lines.append("### Mountain Summits & Peaks")
            for (p_name, p_coords), p_elev_m in zip(peaks_list, peak_elevs):
                p_ll = inv_transform.transform(QgsPointXY(*p_coords))
                if p_elev_m > -9000.0:
                    md_lines.append(
                        f"- **{p_name}**: `{p_elev_m:.0f} m` (`{p_elev_m * 3.28084:,.0f} ft`) — `{p_ll.y():.5f}, {p_ll.x():.5f}`"
                    )
                else:
                    md_lines.append(f"- **{p_name}**: `{p_ll.y():.5f}, {p_ll.x():.5f}`")
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


def export_city_markdown_report(
    config: LoRaGISConfig,
    city_result: Dict,
    zone_label: str,
    timestamp_str: str,
    png_filename: str,
    md_output_path: str,
    buildings: Optional[List] = None,
) -> None:
    """Exports the Markdown city rooftop ranking & viewshed coverage report."""
    center = city_result["center_loc"]
    rad_km = city_result["radius_m"] / 1000.0
    rad_mi = city_result["radius_m"] * 0.000621371
    freq_label = f"{config.freq_mhz:.0f}" if config.freq_mhz.is_integer() else f"{config.freq_mhz:.1f}"
    f1_pct_target = int(round(config.min_fresnel_clearance * 100))
    tg = city_result["target_grid"]

    surface_kind = config.surface_kind_label
    b_src_labels = {
        "osm": "OpenStreetMap",
        "overture": "Overture Maps",
        "hybrid": "Overture Maps + OpenStreetMap",
    }
    b_src_label = b_src_labels.get(config.buildings_source.strip().lower(), "Building Overlay")

    md_lines = [
        f"# {config.title} {freq_label} MHz City Viewshed & Rooftop Ranking: {center['name']} ({timestamp_str})",
        "",
        f"![City Viewshed Coverage Map]({png_filename})",
        "",
        "## 1. City Study Overview",
        "",
        "| Parameter | Value |",
        "| :--- | :--- |",
        f"| **Study Center** | **{center['name']}** (`{center['lat']:.6f}, {center['lon']:.6f}`, {zone_label}) |",
        f"| **Study Radius** | `{rad_km:.2f} km` (`{rad_mi:.2f} mi`), `{len(tg['target_xy']):,}` target points (`~{tg['cell_size_m']:.0f} m` spacing) |",
        f"| **Operating Frequency** | `{config.freq_mhz:.1f} MHz` (LoRa / MeshCore, $\\lambda = {config.wavelength_m*100:.1f}\\text{{ cm}}$) |",
        f"| **Target Fresnel Clearance** | `>= {f1_pct_target}%` of 1st Fresnel Zone ($F_1$), $K = 4/3$ Earth Curvature |",
        f"| **Rooftop Mast Height** | `{config.city_mast_height_m:.2f} m` (`{config.city_mast_height_m*3.28084:.1f} ft`) above structure |",
        f"| **Target Receiver Height** | `{config.city_rx_height_m:.2f} m` (`{config.city_rx_height_m*3.28084:.1f} ft`) AGL |",
        f"| **Surface Sampling** | {surface_kind} nearest-neighbor (`{config.effective_sample_step_m:.1f} m` ray step, `{config.effective_rooftop_margin_m:.1f} m` rooftop margin) |",
        f"| **Candidates Evaluated** | `{len(city_result['all_results'])}` structures (showing top `{len(city_result['top_results'])}`) |",
    ]

    if buildings:
        tall_cnt = sum(1 for b in buildings if b.height_m >= config.min_building_height_m)
        max_bh = max((b.height_m for b in buildings), default=0.0)
        md_lines.append(
            f"| **Building Overlay** | {b_src_label} (`{len(buildings):,}` structures, "
            f"`{tall_cnt}` >= {config.min_building_height_m:.0f} m, max `{max_bh:.1f} m` / `{max_bh*3.28084:.0f} ft`) |"
        )
    md_lines.append("")

    top_results = city_result.get("top_results", [])
    md_lines.extend([
        f"## 2. Top Ranked Rooftops & Tall Structures (Top {len(top_results)})",
        "",
        f"| Rank | Structure | Type / Address | Coordinates (Lat, Lon) | Ground Elev | Height | Mast | >= {f1_pct_target}% $F_1$ Coverage | Optical LOS Coverage | Max Clear Range |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for rank_idx, cand in enumerate(top_results, 1):
        type_clean = cand.structure_type.replace("_", " ").title()
        meta_col = f"{type_clean}, `{cand.address}`" if cand.address else type_clean
        md_lines.append(
            f"| `#{rank_idx}` | **{cand.name}** | {meta_col} | `{cand.lat:.6f}, {cand.lon:.6f}` | "
            f"`{cand.ground_elev_m:.0f} m` (`{cand.ground_elev_m*3.28084:,.0f} ft`) | "
            f"`{cand.structure_height_m:.1f} m` (`{cand.structure_height_m*3.28084:.0f} ft`) | "
            f"`{cand.mast_height_m*3.28084:.0f} ft` | "
            f"**`{cand.f1_pct:.1f}%`** | `{cand.los_pct:.1f}%` | "
            f"`{cand.max_f1_range_m/1000.0:.2f} km` (`{cand.max_f1_range_m*0.000621371:.2f} mi`) |"
        )
    md_lines.append("")

    combos = city_result.get("combos", [])
    if combos:
        md_lines.extend([
            "## 3. Optimal Multi-Site Combinations (Greedy Set-Cover)",
            "",
            f"| Sites | Added Structure | Marginal $F_1$ Gain | Cumulative >= {f1_pct_target}% $F_1$ | Cumulative Optical LOS |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for combo in combos:
            added = combo["added"]
            md_lines.append(
                f"| **{combo['size']}-Site** | **{added.name}** (`{added.lat:.5f}, {added.lon:.5f}`) | "
                f"`+{combo['marginal_f1_pct']:.1f}%` | **`{combo['cumulative_f1_pct']:.1f}%`** | "
                f"`{combo['cumulative_los_pct']:.1f}%` |"
            )
        md_lines.append("")

    with open(md_output_path, "w", encoding="utf-8") as md_file:
        md_file.write("\n".join(md_lines) + "\n")

    print(f"City Viewshed Markdown Report exported to:  {md_output_path}", flush=True)
