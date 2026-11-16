"""PyQGIS topographic map rendering and vector layer symbology."""

from typing import Dict, List, Set, Tuple

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

    topo_layer = QgsRasterLayer(config.topo_basemap_url, "USGS Topographic Basemap", "wms")
    if not topo_layer.isValid():
        topo_layer = QgsRasterLayer(config.fallback_basemap_url, "World Topographic Basemap", "wms")
    if topo_layer.isValid():
        QgsProject.instance().addMapLayer(topo_layer)
        print("\nTopographic basemap stream connected.", flush=True)

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
            raw_nodes.append(("2-Hop Relay 1", r1_pt, r1_ll.y(), r1_ll.x()))
            raw_nodes.append(("2-Hop Relay 2", r2_pt, r2_ll.y(), r2_ll.x()))
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
            oh_label = (
                f"1-Hop Relay ({u_loc['name']}–{v_loc['name']})"
                if len(link_results) > 1
                else "1-Hop Single Relay"
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

    full_extent = node_layer.extent()
    if cand_layer.featureCount() > 0:
        full_extent.combineExtentWith(cand_layer.extent())
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

    for lyr in [cand_layer, blocked_layer, onehop_layer, line_layer, peak_layer, town_layer, node_layer]:
        QgsProject.instance().addMapLayer(lyr)

    map_settings = QgsMapSettings()
    map_settings.setDestinationCrs(crs_utm)
    map_settings.setTransformContext(QgsProject.instance().transformContext())

    render_layers = [node_layer, peak_layer, town_layer, line_layer, onehop_layer, blocked_layer, cand_layer]
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
