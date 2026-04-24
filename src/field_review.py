"""Lighter HTML focused on manual field review — clusters numbered, popups
short, copy-to-clipboard for coords, status filter."""
from __future__ import annotations

from typing import Any

import folium
import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union


def build_field_review_map(
    grid: gpd.GeoDataFrame,
    cluster_meta: pd.DataFrame,
    shortlist: pd.DataFrame,
    *,
    study_polygon_wkt: str | None,
    cfg: dict[str, Any],
) -> folium.Map:
    m = folium.Map(
        location=cfg["map"]["center"],
        zoom_start=cfg["map"]["zoom_start"],
        tiles="CartoDB positron",
        control_scale=True,
    )

    # study polygon outline (subtle)
    if study_polygon_wkt:
        from shapely import wkt as _wkt
        try:
            poly = _wkt.loads(study_polygon_wkt)
            folium.GeoJson(
                gpd.GeoSeries([poly], crs="EPSG:4326").to_json(),
                name="Área", style_function=lambda _f: {
                    "color": "#666", "weight": 1.5, "fill": False,
                    "dashArray": "4,4",
                },
            ).add_to(m)
        except Exception:
            pass

    # cluster polygons
    for _, row in cluster_meta.head(int(cfg.get("clusters", {}).get("top_n", 10))).iterrows():
        cells = grid.iloc[row["cell_idx"]]
        try:
            geom = unary_union(cells.geometry.values).buffer(0)
        except Exception:
            continue
        folium.GeoJson(
            gpd.GeoSeries([geom], crs="EPSG:4326").to_json(),
            style_function=lambda f: {
                "color": "#0a4dff", "weight": 2, "fillColor": "#69a4ff",
                "fillOpacity": 0.18,
            },
            tooltip=f"Cluster #{int(row['cluster_id'])} · {row['bairro']}",
        ).add_to(m)

    # numbered markers + classification
    classes_layer = {
        "alta":  folium.FeatureGroup(name="🟢 Visitar já (prioridade alta)", show=True),
        "média": folium.FeatureGroup(name="🟡 Validar em campo (prioridade média)", show=True),
        "baixa": folium.FeatureGroup(name="⚪ Suspeita / baixa prioridade", show=True),
    }
    for _, row in shortlist.iterrows():
        prio = row.get("prioridade_visita", "média")
        layer = classes_layer.get(prio, classes_layer["média"])
        lat, lon = row["lat"], row["lon"]
        cid = int(row["cluster_id"])
        popup_html = f"""
        <div style="font:12px sans-serif;min-width:240px">
          <div style="font-size:14px"><b>#{int(row['cluster_rank'])} — {row['bairro_aproximado']}</b></div>
          Cluster #{cid} · prioridade <b>{prio}</b><br>
          score médio <b>{row['score_cluster']}</b> · máx <b>{row['score_max_cell']}</b><br>
          <i>{row['principais_sinais']}</i><br>
          <div style="margin:6px 0;padding:4px;background:#f3f3f3;border-radius:3px">
            <code>{lat:.6f}, {lon:.6f}</code>
            <button onclick="navigator.clipboard.writeText('{lat:.6f},{lon:.6f}');
              this.innerText='copiado!'"
              style="margin-left:6px;background:#0a4dff;color:#fff;border:none;
              padding:2px 6px;border-radius:3px;cursor:pointer">copiar</button>
          </div>
          <a href="https://www.google.com/maps/?q={lat},{lon}" target="_blank">
            abrir no Google Maps</a>
          <br><br>
          <i>{row['observacao_esperada_em_campo']}</i>
        </div>"""
        color = {"alta": "#0a8f3a", "média": "#d29400", "baixa": "#999"}[prio]
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                html=(f"<div style='background:{color};color:white;border-radius:50%;"
                      f"width:30px;height:30px;line-height:30px;text-align:center;"
                      f"font-weight:bold;font-size:13px;border:2px solid white;"
                      f"box-shadow:0 0 4px rgba(0,0,0,.5)'>"
                      f"{int(row['cluster_rank'])}</div>"),
                icon_size=(30, 30), icon_anchor=(15, 15),
            ),
            tooltip=f"#{int(row['cluster_rank'])} {row['bairro_aproximado']} ({prio})",
            popup=folium.Popup(popup_html, max_width=320),
        ).add_to(layer)
    for layer in classes_layer.values():
        layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    legend = """
    <div style="position:fixed;bottom:18px;left:18px;z-index:9999;
      background:rgba(255,255,255,.95);padding:10px 14px;
      border:1px solid #888;border-radius:6px;font:12px sans-serif;max-width:280px">
      <b>Field Review Map</b><br>
      Clusters de prospecção numerados.<br>
      <span style="color:#0a8f3a">●</span> visitar já ·
      <span style="color:#d29400">●</span> validar ·
      <span style="color:#999">●</span> baixa prioridade<br>
      Clique em um marcador para copiar lat/lon ou abrir no Google Maps.
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    return m
