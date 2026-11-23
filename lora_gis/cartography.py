"""PyQGIS topographic map rendering and vector layer symbology."""

from typing import Dict, List, Optional, Set, Tuple

from .config import LoRaGISConfig
from .dem import DEMProvider
from .geonames import fetch_geonames_features


def render_topographic_map(
    config: LoRaGISConfig,
    dem: DEMProvider,
    link_results: List[Dict],
    all_viable_relays: Set[Tuple[float, float]],
    hub_repeater_keys: Set[str],
    multi_link_mode: bool,
    crs_utm,
    epsg_str: str,
    wkid: int,
    inv_transform,
    timestamp_str: str,
    png_output_path: str,
    candidate_keys: Optional[List[str]] = None,
) -> Tuple[List, List, List[float]]:
    """
    Renders the topographic map backdrop, candidate relays, 1-hop/2-hop sightlines,
    blocked direct links, mountain summits, and town labels to `png_output_path`.
    Returns (peaks_list, towns_list, peak_elevs).
    """
    from qgis.core import (
        QgsFeature,
        QgsGeometry,
        QgsLineSymbol,
        QgsMapRendererSequentialJob,
        QgsMapSettings,
        QgsMarkerSymbol,
        QgsPalLayerSettings,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsSingleSymbolRenderer,
        QgsTextBufferSettings,
        QgsTextFormat,
        QgsVectorLayer,
        QgsVectorLayerSimpleLabeling,
    )
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QFont

    basemap_labels = {
        "topo": "USGS Topographic Basemap",
        "osm": "OpenStreetMap Street Basemap",
        "satellite": "World Satellite Imagery",
    }
    basemap_title = basemap_labels.get(config.basemap.strip().lower(), "Custom Basemap")
    topo_layer = QgsRasterLayer(config.active_basemap_url, basemap_title, "wms")
    if not topo_layer.isValid():
        topo_layer = QgsRasterLayer(config.fallback_basemap_url, "World Topographic Basemap", "wms")
    if topo_layer.isValid():
        QgsProject.instance().addMapLayer(topo_layer)
        print(f"\nBasemap stream connected ({basemap_title}).", flush=True)

    node_layer = QgsVectorLayer(
        f"Point?crs={epsg_str}&field=Role:string&field=Lat:double&field=Lon:double&field=LabelText:string",
        f"Key Nodes ({timestamp_str})",
        "memory",
    )
    cand_layer = QgsVectorLayer(
        f"Point?crs={epsg_str}&field=Type:string",
        f"All Valid Relays ({timestamp_str})",
        "memory",
    )
    line_layer = QgsVectorLayer(f"LineString?crs={epsg_str}", f"Optimal 2-Hop Sightline ({timestamp_str})", "memory")
    onehop_layer = QgsVectorLayer(f"LineString?crs={epsg_str}", f"Optimal 1-Hop Sightline ({timestamp_str})", "memory")
    blocked_layer = QgsVectorLayer(f"LineString?crs={epsg_str}", f"Blocked Direct Path ({timestamp_str})", "memory")
    peak_layer = QgsVectorLayer(
        f"Point?crs={epsg_str}&field=LabelText:string", f"Mountain Peaks ({timestamp_str})", "memory"
    )
    town_layer = QgsVectorLayer(f"Point?crs={epsg_str}&field=LabelText:string", f"Towns ({timestamp_str})", "memory")

    n_prov = node_layer.dataProvider()
    c_prov = cand_layer.dataProvider()
    l_prov = line_layer.dataProvider()
    oh_prov = onehop_layer.dataProvider()
    b_prov = blocked_layer.dataProvider()
    p_prov = peak_layer.dataProvider()
    t_prov = town_layer.dataProvider()

    raw_nodes = []
    seen_node_keys = set()

    for res in link_results:
        u_key, v_key = res["u_key"], res["v_key"]
        u_loc, v_loc = res["u_loc"], res["v_loc"]

        if u_key not in seen_node_keys:
            seen_node_keys.add(u_key)
            u_role = (
                f"{u_loc['name']} (Repeater)"
                if (multi_link_mode and u_key in hub_repeater_keys)
                else f"{u_loc['name']}"
            )
            raw_nodes.append((u_role, u_loc["xy"], u_loc["lat"], u_loc["lon"]))

        if res["best_2hop"] is not None:
            r1_pt, r2_pt = res["best_2hop"]["r1"], res["best_2hop"]["r2"]
            r1_ll = inv_transform.transform(QgsPointXY(*r1_pt))
            r2_ll = inv_transform.transform(QgsPointXY(*r2_pt))
            r1_lbl = res["best_2hop"].get("r1_name") or "2-Hop Relay 1"
            r2_lbl = res["best_2hop"].get("r2_name") or "2-Hop Relay 2"
            if r1_lbl == "Grid Relay":
                r1_lbl = "2-Hop Relay 1"
            if r2_lbl == "Grid Relay":
                r2_lbl = "2-Hop Relay 2"
            raw_nodes.append((r1_lbl, r1_pt, r1_ll.y(), r1_ll.x()))
            raw_nodes.append((r2_lbl, r2_pt, r2_ll.y(), r2_ll.x()))
            path_2h = [u_loc["xy"], r1_pt, r2_pt, v_loc["xy"]]
            for i in range(len(path_2h) - 1):
                f_line = QgsFeature()
                f_line.setGeometry(
                    QgsGeometry.fromPolylineXY([QgsPointXY(*path_2h[i]), QgsPointXY(*path_2h[i + 1])])
                )
                l_prov.addFeature(f_line)

        map_1h = res["best_1hop"]
        if map_1h is None and res["sensitivity_tables"]:
            for tbl in res["sensitivity_tables"]:
                for row in tbl["rows"]:
                    if row["best"] is not None:
                        map_1h = row["best"]
                        break
                if map_1h is not None:
                    break

        if map_1h is not None:
            oh_pt = map_1h["relay"]
            oh_ll = inv_transform.transform(QgsPointXY(*oh_pt))
            cand_nm = map_1h.get("candidate_name")
            oh_label = (
                f"1-Hop Relay ({cand_nm})"
                if cand_nm
                else (
                    f"1-Hop Relay ({u_loc['name']}–{v_loc['name']})"
                    if len(link_results) > 1
                    else "1-Hop Single Relay"
                )
            )
            raw_nodes.append((oh_label, oh_pt, oh_ll.y(), oh_ll.x()))
            path_1h = [u_loc["xy"], oh_pt, v_loc["xy"]]
            for i in range(len(path_1h) - 1):
                f_oh = QgsFeature()
                f_oh.setGeometry(
                    QgsGeometry.fromPolylineXY([QgsPointXY(*path_1h[i]), QgsPointXY(*path_1h[i + 1])])
                )
                oh_prov.addFeature(f_oh)

        if v_key not in seen_node_keys:
            seen_node_keys.add(v_key)
            v_role = (
                f"{v_loc['name']} (Repeater)"
                if (multi_link_mode and v_key in hub_repeater_keys)
                else f"{v_loc['name']}"
            )
            raw_nodes.append((v_role, v_loc["xy"], v_loc["lat"], v_loc["lon"]))

        if not res["direct_clear"]:
            f_blk = QgsFeature()
            f_blk.setGeometry(
                QgsGeometry.fromPolylineXY([QgsPointXY(*u_loc["xy"]), QgsPointXY(*v_loc["xy"])])
            )
            b_prov.addFeature(f_blk)

    key_elevs = dem.fetch_elevations([n[1] for n in raw_nodes])
    for (role, coords, lat, lon), elev_m in zip(raw_nodes, key_elevs):
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*coords)))
        elev_ft = elev_m * 3.28084
        label_text = f"{role}\n({lat:.5f}, {lon:.5f})\nElev: {elev_m:.0f} m ({elev_ft:,.0f} ft)"
        feat.setAttributes([role, lat, lon, label_text])
        n_prov.addFeature(feat)

    for c_coords in all_viable_relays:
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*c_coords)))
        feat.setAttributes(["Viable Relay Spot"])
        c_prov.addFeature(feat)

    node_layer.updateExtents()
    cand_layer.updateExtents()
    line_layer.updateExtents()
    onehop_layer.updateExtents()
    blocked_layer.updateExtents()

    explicit_viable_layer = None
    explicit_blocked_layer = None
    cand_sightline_layer = None
    cand_clear_sightline_layer = None
    cand_blockage_layer = None
    if candidate_keys:
        explicit_viable_layer = QgsVectorLayer(
            f"Point?crs={epsg_str}&field=LabelText:string",
            f"Viable Candidate Relays ({timestamp_str})",
            "memory",
        )
        explicit_blocked_layer = QgsVectorLayer(
            f"Point?crs={epsg_str}&field=LabelText:string",
            f"Blocked Candidate Relays ({timestamp_str})",
            "memory",
        )
        cand_sightline_layer = QgsVectorLayer(
            f"LineString?crs={epsg_str}",
            f"Blocked Candidate Sightlines ({timestamp_str})",
            "memory",
        )
        cand_clear_sightline_layer = QgsVectorLayer(
            f"LineString?crs={epsg_str}",
            f"Clear Candidate Sightlines ({timestamp_str})",
            "memory",
        )
        cand_blockage_layer = QgsVectorLayer(
            f"Point?crs={epsg_str}&field=LabelText:string",
            f"Candidate Terrain Blockages ({timestamp_str})",
            "memory",
        )
        ev_prov = explicit_viable_layer.dataProvider()
        eb_prov = explicit_blocked_layer.dataProvider()
        cs_prov = cand_sightline_layer.dataProvider()
        ccs_prov = cand_clear_sightline_layer.dataProvider()
        cb_prov = cand_blockage_layer.dataProvider()

        cand_eval_by_key: Dict[str, List[Dict]] = {k: [] for k in candidate_keys}
        cand_clear_legs: Dict[str, List[Tuple[str, float]]] = {k: [] for k in candidate_keys}
        cand_2hop_f1: Dict[str, List[float]] = {k: [] for k in candidate_keys}
        cand_hybrid_f1: Dict[str, List[float]] = {k: [] for k in candidate_keys}
        seen_cand_segments = set()
        for res in link_results:
            u_xy = res["u_loc"]["xy"]
            v_xy = res["v_loc"]["xy"]
            u_name = res["u_loc"]["name"]
            v_name = res["v_loc"]["name"]
            for p in res.get("explicit_2hop_pairs", []):
                if p.get("viable"):
                    for ck in (p["c1_key"], p["c2_key"]):
                        if ck in cand_2hop_f1:
                            cand_2hop_f1[ck].append(p["min_fresnel"])
            for h in res.get("hybrid_2hop", []):
                for ck in candidate_keys:
                    c_nm = config.locations[ck]["name"]
                    if h.get("r1_name") == c_nm or h.get("r2_name") == c_nm:
                        cand_hybrid_f1[ck].append(h["min_fresnel"])
            for ec in res.get("explicit_candidates", []):
                if ec["key"] in cand_eval_by_key:
                    cand_eval_by_key[ec["key"]].append(ec)
                    if ec["leg1"]["clear"]:
                        cand_clear_legs[ec["key"]].append((u_name, ec["leg1"]["min_fresnel_ratio"]))
                    if ec["leg2"]["clear"]:
                        cand_clear_legs[ec["key"]].append((v_name, ec["leg2"]["min_fresnel_ratio"]))
                c_xy = ec["xy"]
                for start_xy, end_xy, leg_d in [
                    (u_xy, c_xy, ec["leg1"]),
                    (c_xy, v_xy, ec["leg2"]),
                ]:
                    seg_a = (round(start_xy[0], 1), round(start_xy[1], 1))
                    seg_b = (round(end_xy[0], 1), round(end_xy[1], 1))
                    seg_key = (seg_a, seg_b) if seg_a <= seg_b else (seg_b, seg_a)
                    if seg_key in seen_cand_segments:
                        continue
                    seen_cand_segments.add(seg_key)
                    f_sl = QgsFeature()
                    f_sl.setGeometry(
                        QgsGeometry.fromPolylineXY([QgsPointXY(*start_xy), QgsPointXY(*end_xy)])
                    )
                    if leg_d["clear"]:
                        ccs_prov.addFeature(f_sl)
                    else:
                        cs_prov.addFeature(f_sl)
                        if "profile" in leg_d:
                            w_xy = leg_d["profile"]["worst_xy"]
                            f_blk_pt = QgsFeature()
                            f_blk_pt.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*w_xy)))
                            f_blk_pt.setAttributes([f"✕ {leg_d['min_clearance_m']:.0f}m"])
                            cb_prov.addFeature(f_blk_pt)

        for c_key in candidate_keys:
            c_loc = config.locations[c_key]
            evals = cand_eval_by_key.get(c_key, [])
            is_1hop_viable = any(e["viable"] for e in evals)
            is_2hop_viable = bool(cand_2hop_f1.get(c_key))
            is_hybrid_viable = bool(cand_hybrid_f1.get(c_key))
            clear_legs = cand_clear_legs.get(c_key, [])
            is_viable = is_1hop_viable or is_2hop_viable or is_hybrid_viable or bool(clear_legs)
            elev_m = evals[0]["elev_m"] if evals else dem.fetch_elevations([c_loc["xy"]])[0]
            elev_ft = elev_m * 3.28084
            if is_1hop_viable:
                best_f1 = max(e["min_fresnel"] for e in evals if e["viable"])
                status_txt = f"1-Hop: {best_f1*100:.0f}% F1"
            elif is_2hop_viable:
                best_f1 = max(cand_2hop_f1[c_key])
                status_txt = f"2-Hop: {best_f1*100:.0f}% F1"
            elif clear_legs:
                best_town, best_f1 = max(clear_legs, key=lambda item: item[1])
                status_txt = f"Clear → {best_town} ({best_f1*100:.0f}% F1)"
            elif evals:
                e0 = evals[0]
                l1_s = "OK" if e0["leg1"]["clear"] else f"{e0['leg1']['min_clearance_m']:.0f}m"
                l2_s = "OK" if e0["leg2"]["clear"] else f"{e0['leg2']['min_clearance_m']:.0f}m"
                status_txt = f"Blocked ({l1_s} / {l2_s})"
            else:
                status_txt = "Candidate"

            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*c_loc["xy"])))
            lbl = (
                f"{c_loc['name']}\n"
                f"({c_loc['lat']:.5f}, {c_loc['lon']:.5f})\n"
                f"Elev: {elev_m:.0f} m ({elev_ft:,.0f} ft) | {status_txt}"
            )
            feat.setAttributes([lbl])
            if is_viable:
                ev_prov.addFeature(feat)
            else:
                eb_prov.addFeature(feat)

        explicit_viable_layer.updateExtents()
        explicit_blocked_layer.updateExtents()
        cand_sightline_layer.updateExtents()
        cand_clear_sightline_layer.updateExtents()
        cand_blockage_layer.updateExtents()

    full_extent = node_layer.extent()
    if cand_layer.featureCount() > 0:
        full_extent.combineExtentWith(cand_layer.extent())
    if explicit_viable_layer is not None and explicit_viable_layer.featureCount() > 0:
        full_extent.combineExtentWith(explicit_viable_layer.extent())
    if explicit_blocked_layer is not None and explicit_blocked_layer.featureCount() > 0:
        full_extent.combineExtentWith(explicit_blocked_layer.extent())
    full_extent.scale(config.map_extent_scale)

    peaks_list, towns_list = fetch_geonames_features(full_extent, wkid, config.geonames_url)
    peak_elevs = []
    if peaks_list:
        peak_elevs = dem.fetch_elevations([coords for _, coords in peaks_list])
        for (p_name, p_coords), p_elev_m in zip(peaks_list, peak_elevs):
            f_p = QgsFeature()
            f_p.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*p_coords)))
            p_elev_ft = p_elev_m * 3.28084
            f_p.setAttributes([f"▲ {p_name}\n({p_elev_m:.0f} m / {p_elev_ft:,.0f} ft)"])
            p_prov.addFeature(f_p)
        peak_layer.updateExtents()

    if towns_list:
        for t_name, t_coords in towns_list:
            f_t = QgsFeature()
            f_t.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*t_coords)))
            f_t.setAttributes([t_name])
            t_prov.addFeature(f_t)
        town_layer.updateExtents()

    node_symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "220,25,25,255",
        "outline_color": "255,255,255,255",
        "outline_width": "0.8",
        "size": "4.2",
    })
    node_layer.setRenderer(QgsSingleSymbolRenderer(node_symbol))

    cand_symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "255,185,0,145",
        "outline_color": "140,80,0,180",
        "outline_width": "0.35",
        "size": "2.1",
    })
    cand_layer.setRenderer(QgsSingleSymbolRenderer(cand_symbol))

    line_symbol = QgsLineSymbol.createSimple({"color": "255,255,255,235", "width": "1.9"})
    inner_line = QgsLineSymbol.createSimple({"color": "220,20,20,255", "width": "1.05"})
    line_symbol.appendSymbolLayer(inner_line.symbolLayer(0).clone())
    line_layer.setRenderer(QgsSingleSymbolRenderer(line_symbol))

    oh_symbol = QgsLineSymbol.createSimple({"color": "255,255,255,220", "width": "1.7"})
    oh_inner = QgsLineSymbol.createSimple({"color": "15,105,215,245", "width": "0.95", "line_style": "dash"})
    oh_symbol.appendSymbolLayer(oh_inner.symbolLayer(0).clone())
    onehop_layer.setRenderer(QgsSingleSymbolRenderer(oh_symbol))

    blocked_symbol = QgsLineSymbol.createSimple({"color": "80,80,80,185", "width": "0.75", "line_style": "dash"})
    blocked_layer.setRenderer(QgsSingleSymbolRenderer(blocked_symbol))

    peak_symbol = QgsMarkerSymbol.createSimple({
        "name": "triangle",
        "color": "120,60,15,235",
        "outline_color": "255,255,255,240",
        "outline_width": "0.6",
        "size": "3.4",
    })
    peak_layer.setRenderer(QgsSingleSymbolRenderer(peak_symbol))

    town_symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": "40,60,90,230",
        "outline_color": "255,255,255,240",
        "outline_width": "0.6",
        "size": "2.6",
    })
    town_layer.setRenderer(QgsSingleSymbolRenderer(town_symbol))

    _bold_weight = getattr(QFont, "Bold", QFont.Weight.Bold)
    text_format = QgsTextFormat()
    text_format.setFont(QFont("DejaVu Sans", 9, _bold_weight))
    text_format.setColor(QColor(15, 15, 15))
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.5)
    buffer_settings.setColor(QColor(255, 255, 255))
    text_format.setBuffer(buffer_settings)

    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = "LabelText"
    label_settings.isExpression = False
    label_settings.dist = 2.2
    label_settings.setFormat(text_format)
    node_layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
    node_layer.setLabelsEnabled(True)

    peak_tf = QgsTextFormat()
    peak_tf.setFont(QFont("DejaVu Sans", 8, _bold_weight))
    peak_tf.setColor(QColor(85, 40, 10))
    peak_buf = QgsTextBufferSettings()
    peak_buf.setEnabled(True)
    peak_buf.setSize(1.3)
    peak_buf.setColor(QColor(255, 252, 240))
    peak_tf.setBuffer(peak_buf)

    peak_lbl = QgsPalLayerSettings()
    peak_lbl.fieldName = "LabelText"
    peak_lbl.isExpression = False
    peak_lbl.dist = 1.8
    peak_lbl.setFormat(peak_tf)
    peak_layer.setLabeling(QgsVectorLayerSimpleLabeling(peak_lbl))
    peak_layer.setLabelsEnabled(True)

    town_tf = QgsTextFormat()
    town_tf.setFont(QFont("DejaVu Sans", 9, _bold_weight))
    town_tf.setColor(QColor(25, 45, 75))
    town_buf = QgsTextBufferSettings()
    town_buf.setEnabled(True)
    town_buf.setSize(1.4)
    town_buf.setColor(QColor(255, 255, 255))
    town_tf.setBuffer(town_buf)

    town_lbl = QgsPalLayerSettings()
    town_lbl.fieldName = "LabelText"
    town_lbl.isExpression = False
    town_lbl.dist = 1.8
    town_lbl.setFormat(town_tf)
    town_layer.setLabeling(QgsVectorLayerSimpleLabeling(town_lbl))
    town_layer.setLabelsEnabled(True)

    extra_cand_layers = []
    extra_cand_line_layers = []
    if explicit_viable_layer is not None and explicit_blocked_layer is not None:
        cs_symbol = QgsLineSymbol.createSimple({
            "color": "145,55,180,145",
            "width": "0.65",
            "line_style": "dot",
        })
        cand_sightline_layer.setRenderer(QgsSingleSymbolRenderer(cs_symbol))
        extra_cand_line_layers.append(cand_sightline_layer)

        ccs_symbol = QgsLineSymbol.createSimple({
            "color": "20,165,65,220",
            "width": "0.95",
            "line_style": "dash",
        })
        cand_clear_sightline_layer.setRenderer(QgsSingleSymbolRenderer(ccs_symbol))
        extra_cand_line_layers.append(cand_clear_sightline_layer)

        cb_symbol = QgsMarkerSymbol.createSimple({
            "name": "cross2",
            "color": "215,25,28,240",
            "outline_color": "215,25,28,255",
            "outline_width": "0.9",
            "size": "3.4",
        })
        cand_blockage_layer.setRenderer(QgsSingleSymbolRenderer(cb_symbol))
        cb_tf = QgsTextFormat()
        cb_tf.setFont(QFont("DejaVu Sans", 7, _bold_weight))
        cb_tf.setColor(QColor(185, 15, 20))
        cb_buf = QgsTextBufferSettings()
        cb_buf.setEnabled(True)
        cb_buf.setSize(1.2)
        cb_buf.setColor(QColor(255, 255, 255))
        cb_tf.setBuffer(cb_buf)
        cb_lbl = QgsPalLayerSettings()
        cb_lbl.fieldName = "LabelText"
        cb_lbl.isExpression = False
        cb_lbl.dist = 1.4
        cb_lbl.setFormat(cb_tf)
        cand_blockage_layer.setLabeling(QgsVectorLayerSimpleLabeling(cb_lbl))
        cand_blockage_layer.setLabelsEnabled(True)
        extra_cand_layers.append(cand_blockage_layer)

        ev_symbol = QgsMarkerSymbol.createSimple({
            "name": "diamond",
            "color": "20,165,65,255",
            "outline_color": "255,255,255,255",
            "outline_width": "0.8",
            "size": "4.8",
        })
        explicit_viable_layer.setRenderer(QgsSingleSymbolRenderer(ev_symbol))

        eb_symbol = QgsMarkerSymbol.createSimple({
            "name": "diamond",
            "color": "145,55,180,235",
            "outline_color": "255,255,255,255",
            "outline_width": "0.75",
            "size": "4.2",
        })
        explicit_blocked_layer.setRenderer(QgsSingleSymbolRenderer(eb_symbol))

        for lyr, color_rgb in [
            (explicit_viable_layer, (10, 95, 35)),
            (explicit_blocked_layer, (95, 25, 125)),
        ]:
            c_tf = QgsTextFormat()
            c_tf.setFont(QFont("DejaVu Sans", 8, _bold_weight))
            c_tf.setColor(QColor(*color_rgb))
            c_buf = QgsTextBufferSettings()
            c_buf.setEnabled(True)
            c_buf.setSize(1.4)
            c_buf.setColor(QColor(255, 255, 255))
            c_tf.setBuffer(c_buf)
            c_lbl = QgsPalLayerSettings()
            c_lbl.fieldName = "LabelText"
            c_lbl.isExpression = False
            c_lbl.dist = 2.0
            c_lbl.priority = 8
            c_lbl.setFormat(c_tf)
            lyr.setLabeling(QgsVectorLayerSimpleLabeling(c_lbl))
            lyr.setLabelsEnabled(True)
            extra_cand_layers.append(lyr)

    for lyr in [cand_layer, blocked_layer, *extra_cand_line_layers, onehop_layer, line_layer, peak_layer, town_layer, *extra_cand_layers, node_layer]:
        QgsProject.instance().addMapLayer(lyr)

    map_settings = QgsMapSettings()
    map_settings.setDestinationCrs(crs_utm)
    map_settings.setTransformContext(QgsProject.instance().transformContext())
    try:
        from qgis.core import Qgis, QgsLabelingEngineSettings
        les = map_settings.labelingEngineSettings()
        partial_flag = getattr(
            getattr(Qgis, "LabelingFlag", None),
            "UsePartialCandidates",
            getattr(QgsLabelingEngineSettings, "UsePartialCandidates", None),
        )
        if partial_flag is not None:
            les.setFlag(partial_flag, False)
            map_settings.setLabelingEngineSettings(les)
    except Exception:
        pass

    render_layers = [node_layer, *extra_cand_layers, peak_layer, town_layer, line_layer, onehop_layer, *extra_cand_line_layers, blocked_layer, cand_layer]
    if topo_layer.isValid():
        render_layers.append(topo_layer)

    map_settings.setLayers(render_layers)
    map_settings.setExtent(full_extent)
    map_settings.setOutputSize(QSize(config.map_width, config.map_height))
    map_settings.setOutputDpi(config.map_dpi)

    render_job = QgsMapRendererSequentialJob(map_settings)
    render_job.start()
    render_job.waitForFinished()

    rendered_img = render_job.renderedImage()
    rendered_img.save(png_output_path, "PNG")
    print(f"Topographic Map PNG with coordinate labels exported to: {png_output_path}", flush=True)

    return peaks_list, towns_list, peak_elevs


def render_candidate_profiles(
    config: LoRaGISConfig,
    link_results: List[Dict],
    png_output_path: str,
) -> Optional[str]:
    """
    Renders cross-sectional terrain elevation profiles for every explicit candidate relay leg,
    highlighting the direct line-of-sight, 1st Fresnel zone (F1), and exact terrain blockage.
    Returns `png_output_path` on success, or None if no explicit candidates or matplotlib is unavailable.
    """
    rows = []
    for res in link_results:
        u_loc, v_loc = res["u_loc"], res["v_loc"]
        for ec in res.get("explicit_candidates", []):
            if "profile" in ec["leg1"] and "profile" in ec["leg2"]:
                rows.append((u_loc, v_loc, ec))

    if not rows:
        return None

    try:
        import os
        import tempfile
        os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "lora_gis_mpl"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        print(f"Warning: Skipping candidate profile chart (matplotlib unavailable: {exc}).", flush=True)
        return None

    n_rows = len(rows)
    fig, axes = plt.subplots(n_rows, 2, figsize=(15.5, 3.6 * n_rows), squeeze=False)
    fig.patch.set_facecolor("#ffffff")

    freq_label = f"{config.freq_mhz:.0f}" if config.freq_mhz.is_integer() else f"{config.freq_mhz:.1f}"
    fig.suptitle(
        f"{config.title} ({freq_label} MHz) Explicit Candidate Terrain & Line-of-Sight Profiles (K = 4/3 Earth Curvature)",
        fontsize=13,
        fontweight="bold",
        y=0.995,
    )

    for row_idx, (u_loc, v_loc, ec) in enumerate(rows):
        legs = [
            (
                f"Leg 1: {u_loc['name']} ({u_loc['height_m']*3.28084:.0f} ft) → {ec['name']} ({ec['height_m']*3.28084:.0f} ft)",
                ec["leg1"],
                u_loc["name"],
                ec["name"],
            ),
            (
                f"Leg 2: {ec['name']} ({ec['height_m']*3.28084:.0f} ft) → {v_loc['name']} ({v_loc['height_m']*3.28084:.0f} ft)",
                ec["leg2"],
                ec["name"],
                v_loc["name"],
            ),
        ]
        for col_idx, (leg_title, leg_d, left_lbl, right_lbl) in enumerate(legs):
            ax = axes[row_idx][col_idx]
            prof = leg_d["profile"]
            dist_km = np.array(prof["dist_km"], dtype=np.float64)
            terrain_m = np.array(prof["terrain_m"], dtype=np.float64)
            sight_m = np.array(prof["sightline_m"], dtype=np.float64)
            f1_m = np.array(prof["f1_radius_m"], dtype=np.float64)

            raw_min = float(min(terrain_m.min(), (sight_m - f1_m).min()))
            raw_max = float(max(terrain_m.max(), (sight_m + f1_m).max()))
            span = max(40.0, raw_max - raw_min)
            y_min = raw_min - max(20.0, 0.10 * span)
            y_max = raw_max + max(50.0, 0.28 * span)

            # Terrain / surface fill and ridge outline
            if "ground_m" in prof:
                ground_m = np.array(prof["ground_m"], dtype=np.float64)
                ax.fill_between(dist_km, y_min, ground_m, color="#b5a68e", alpha=0.55, label="Ground DEM (+ 4/3 Bulge)")
                ax.fill_between(
                    dist_km,
                    ground_m,
                    terrain_m,
                    where=(terrain_m > ground_m),
                    color="#6b7b8c",
                    alpha=0.65,
                    label="Surface / Buildings (DSM)",
                )
                ax.plot(dist_km, terrain_m, color="#3b4856", linewidth=1.2)
            else:
                surface_label = "DSM Surface (+ 4/3 Bulge)" if config.is_dsm_mode else "Terrain (+ 4/3 Earth Bulge)"
                ax.fill_between(dist_km, y_min, terrain_m, color="#b5a68e", alpha=0.55, label=surface_label)
                ax.plot(dist_km, terrain_m, color="#5c4b37", linewidth=1.3)

            # 1st Fresnel Zone envelope
            f1_color = "#2ca02c" if leg_d["clear"] else "#ff9933"
            ax.fill_between(
                dist_km,
                sight_m - f1_m,
                sight_m + f1_m,
                color=f1_color,
                alpha=0.18,
                label="1st Fresnel Zone (F1)",
            )

            # Direct LOS line
            los_color = "#1b8a2f" if leg_d["clear"] else "#cc2222"
            los_style = "-" if leg_d["clear"] else "--"
            ax.plot(dist_km, sight_m, color=los_color, linestyle=los_style, linewidth=1.6, label="Direct LOS")

            # Highlight terrain protruding above the LOS sightline in red
            blocked_mask = terrain_m > sight_m
            if np.any(blocked_mask):
                ax.fill_between(
                    dist_km,
                    sight_m,
                    terrain_m,
                    where=blocked_mask,
                    interpolate=True,
                    color="#d62728",
                    alpha=0.55,
                    label="Terrain Blockage",
                )

            # Mark antenna tips at endpoints
            ax.scatter([dist_km[0], dist_km[-1]], [sight_m[0], sight_m[-1]], color="#1f4e79", s=32, zorder=5)

            # Annotate worst clearance / blockage point
            wx = prof["worst_dist_km"]
            wt = prof["worst_terrain_m"]
            ws = prof["worst_sightline_m"]
            min_clr = leg_d["min_clearance_m"]
            min_clr_ft = min_clr * 3.28084
            if not leg_d["clear"]:
                ax.plot([wx, wx], [ws, wt], color="#990000", linewidth=2.0, zorder=6)
                ax.scatter([wx], [wt], color="#d62728", edgecolor="#ffffff", s=50, zorder=7)
                ann_txt = f"Worst blockage:\n{min_clr:.1f} m ({min_clr_ft:.0f} ft) @ {wx:.2f} km"
                x_offset = 10 if wx < 0.62 * dist_km[-1] else -115
                ax.annotate(
                    ann_txt,
                    xy=(wx, wt),
                    xytext=(x_offset, 12),
                    textcoords="offset points",
                    fontsize=8,
                    fontweight="bold",
                    color="#8c0d0d",
                    bbox=dict(boxstyle="round,pad=0.25", fc="#fff3f3", ec="#d62728", lw=0.8),
                    arrowprops=dict(arrowstyle="->", color="#990000", lw=1.0),
                    zorder=8,
                )
            else:
                ax.scatter([wx], [wt], color="#1b8a2f", edgecolor="#ffffff", s=45, zorder=7)
                ann_txt = f"Min clearance:\n+{min_clr:.1f} m (+{min_clr_ft:.0f} ft, {leg_d['min_fresnel_ratio']*100:.0f}% F1)"
                x_offset = 10 if wx < 0.62 * dist_km[-1] else -130
                ax.annotate(
                    ann_txt,
                    xy=(wx, wt),
                    xytext=(x_offset, 12),
                    textcoords="offset points",
                    fontsize=8,
                    fontweight="bold",
                    color="#136620",
                    bbox=dict(boxstyle="round,pad=0.25", fc="#f2fbf4", ec="#1b8a2f", lw=0.8),
                    arrowprops=dict(arrowstyle="->", color="#1b8a2f", lw=1.0),
                    zorder=8,
                )

            status_badge = (
                f"CLEAR ({leg_d['min_fresnel_ratio']*100:.0f}% F1)"
                if leg_d["clear"]
                else f"BLOCKED ({min_clr:.1f} m / {min_clr_ft:.0f} ft)"
            )
            ax.set_title(
                f"{leg_title}\n{dist_km[-1]:.2f} km | {status_badge}",
                fontsize=9.5,
                fontweight="bold",
                color="#136620" if leg_d["clear"] else "#8c0d0d",
            )
            ax.set_xlabel(f"Distance from {left_lbl} to {right_lbl} (km)", fontsize=8.5)
            ax.set_ylabel("Elevation ASL (m)", fontsize=8.5)
            ax.set_xlim(0.0, float(dist_km[-1]))
            ax.set_ylim(y_min, y_max)
            ax.grid(True, linestyle=":", alpha=0.55)

            # Secondary Y-axis in feet
            ax_ft = ax.twinx()
            ax_ft.set_ylim(y_min * 3.28084, y_max * 3.28084)
            ax_ft.set_ylabel("Elevation ASL (ft)", fontsize=8, color="#555555")
            ax_ft.tick_params(axis="y", labelsize=8, colors="#555555")

            if row_idx == 0 and col_idx == 0:
                ax.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
    fig.savefig(png_output_path, dpi=150)
    plt.close(fig)
    print(f"Candidate Terrain Blockage Profiles exported to:     {png_output_path}", flush=True)
    return png_output_path
