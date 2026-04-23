"""Folium-based interactive map with score overlay, tooltips and legend."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import branca.colormap as bcm
import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import HeatMap, MarkerCluster


def _make_colormap() -> bcm.LinearColormap:
    cm = bcm.LinearColormap(
        colors=[
            "#b30000",  # 0    — muito ruim
            "#e34a33",
            "#fc8d59",
            "#fdbb84",  # ~30
            "#fee08b",
            "#ffffbf",  # ~50  — médio
            "#d9ef8b",
            "#a6d96a",  # ~70
            "#66bd63",
            "#1a9850",  # 100  — muito bom
        ],
        vmin=0,
        vmax=100,
    )
    cm.caption = "Score de potencial (0-100)"
    return cm


def _style_factory(cm: bcm.LinearColormap, fill_opacity: float, line_opacity: float):
    def styler(feature):
        score = feature["properties"].get("score", 0)
        return {
            "fillColor": cm(float(score)),
            "color": "#222",
            "weight": 0.3,
            "fillOpacity": float(fill_opacity),
            "opacity": float(line_opacity),
        }

    return styler


def _tooltip_fields(props: dict[str, Any]) -> tuple[list[str], list[str]]:
    fields = ["h3", "class", "score"]
    aliases = ["H3 cell:", "Classe:", "Score:"]
    # optional breakdown columns (top positive + penalties)
    for f, a in [
        ("positive_total", "Soma positiva:"),
        ("penalty_total", "Soma penalidades:"),
        ("pos_food", "food:"),
        ("pos_shop", "shop:"),
        ("pos_supermarket", "supermercado:"),
        ("pos_pharmacy", "farmácia:"),
        ("pos_education", "educação:"),
        ("pos_fitness", "academia:"),
        ("pos_healthcare", "saúde:"),
        ("pos_office", "escritório:"),
        ("pos_transport", "transporte:"),
        ("pos_mixed_use", "mixed-use:"),
        ("pos_residential", "residencial:"),
        ("pos_commercial", "comercial:"),
        ("pos_road_density", "conectividade:"),
        ("pen_unsuitable_landuse", "pen. landuse inviável:"),
        ("pen_industrial", "pen. industrial:"),
        ("pen_isolation", "pen. isolamento:"),
        ("pen_low_connectivity", "pen. baixa conectividade:"),
    ]:
        if f in props:
            fields.append(f)
            aliases.append(a)
    return fields, aliases


def build_map(
    grid: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    top_cells: pd.DataFrame | None = None,
    study_polygon_wkt: str | None = None,
) -> folium.Map:
    m = folium.Map(
        location=cfg["map"]["center"],
        zoom_start=cfg["map"]["zoom_start"],
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.TileLayer(
        "CartoDB positron", name="Carto Positron", control=True
    ).add_to(m)
    folium.TileLayer(
        "CartoDB dark_matter", name="Carto Dark", control=True
    ).add_to(m)

    cm = _make_colormap()
    cm.add_to(m)

    # round numeric columns for tooltip readability
    display = grid.copy()
    numeric_cols = display.select_dtypes(include=["float", "float64", "float32"]).columns
    for c in numeric_cols:
        display[c] = display[c].round(3)

    # ------ choropleth of hex cells -------------------------------------
    geo = display.to_json()
    fields, aliases = _tooltip_fields(display.iloc[0].to_dict() if not display.empty else {})

    folium.GeoJson(
        geo,
        name="Score por célula (H3)",
        style_function=_style_factory(cm, cfg["map"]["fill_opacity"], cfg["map"]["line_opacity"]),
        tooltip=folium.features.GeoJsonTooltip(
            fields=fields,
            aliases=aliases,
            localize=True,
            sticky=True,
            labels=True,
        ),
    ).add_to(m)

    # ------ smoothed heatmap (centroids weighted by score) -------------
    if cfg["map"].get("include_heatmap_layer", True):
        pts = [
            [float(r.lat), float(r.lon), float(r.score) / 100.0]
            for r in grid.itertuples(index=False)
            if r.score > 0
        ]
        if pts:
            heat_group = folium.FeatureGroup(name="Heatmap suavizado", show=False)
            HeatMap(
                pts,
                radius=18,
                blur=22,
                min_opacity=0.25,
                max_zoom=15,
                gradient={
                    "0.0": "#b30000",
                    "0.25": "#fc8d59",
                    "0.5": "#ffffbf",
                    "0.75": "#a6d96a",
                    "1.0": "#1a9850",
                },
            ).add_to(heat_group)
            heat_group.add_to(m)

    # ------ top markers ------------------------------------------------
    if cfg["map"].get("include_top_markers", True) and top_cells is not None and not top_cells.empty:
        cluster = MarkerCluster(name="Top áreas (ranking)")
        for _, row in top_cells.iterrows():
            html = (
                f"<b>Rank #{int(row['rank'])}</b><br>"
                f"Score: <b>{row['score']:.1f}</b> ({row['class']})<br>"
                f"H3: {row['h3']}<br>"
                f"Lat/Lon: {row['lat']:.5f}, {row['lon']:.5f}"
            )
            folium.Marker(
                location=[row["lat"], row["lon"]],
                tooltip=f"#{int(row['rank'])} — {row['score']:.1f}",
                popup=folium.Popup(html, max_width=350),
                icon=folium.Icon(color="green", icon="star", prefix="fa"),
            ).add_to(cluster)
        cluster.add_to(m)

    # ------ study area outline -----------------------------------------
    from shapely import wkt as _wkt

    if study_polygon_wkt:
        try:
            poly = _wkt.loads(study_polygon_wkt)
            folium.GeoJson(
                gpd.GeoSeries([poly], crs="EPSG:4326").to_json(),
                name="Área de estudo",
                style_function=lambda _f: {
                    "color": "#000",
                    "weight": 2,
                    "fill": False,
                    "dashArray": "5,5",
                },
            ).add_to(m)
        except Exception:
            pass

    folium.LayerControl(collapsed=False).add_to(m)

    # ------ floating legend / info panel -------------------------------
    _add_info_panel(m, cfg)
    return m


def _add_info_panel(m: folium.Map, cfg: dict[str, Any]) -> None:
    html = f"""
    <div style="
        position: fixed; bottom: 24px; left: 24px; z-index: 9999;
        background: rgba(255,255,255,0.92); padding: 10px 14px;
        border: 1px solid #888; border-radius: 6px; font: 12px/1.3 sans-serif;
        max-width: 320px;">
      <b>Vending Machine Heatmap — {cfg['city']['name']}</b><br>
      Score 0-100 combinando POIs, landuse, conectividade e penalidades.<br>
      <b>Classes</b>:
        <span style='color:#b30000'>0-20 muito ruim</span> ·
        <span style='color:#fc8d59'>20-40 ruim</span> ·
        <span style='color:#e0bf0b'>40-60 médio</span> ·
        <span style='color:#66bd63'>60-80 bom</span> ·
        <span style='color:#1a9850'>80-100 muito bom</span><br>
      Clique em uma célula para ver o breakdown.<br>
      <i>Metodologia: heurística espacial; não substitui visita in loco.</i>
    </div>"""
    m.get_root().html.add_child(folium.Element(html))


def save_map(m: folium.Map, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(p))
    return p
