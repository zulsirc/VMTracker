"""Folium-based interactive map with score overlay, anti-halo popup,
top-cluster polygons, audit toggles and POI category layers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import branca.colormap as bcm
import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import HeatMap, MarkerCluster
from shapely.ops import unary_union


# ----------------------------------------------------------------------------
# Colormap
# ----------------------------------------------------------------------------
def _make_colormap() -> bcm.LinearColormap:
    cm = bcm.LinearColormap(
        colors=[
            "#b30000", "#e34a33", "#fc8d59", "#fdbb84",
            "#fee08b", "#ffffbf",
            "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850",
        ],
        vmin=0, vmax=100,
    )
    cm.caption = "Score de potencial (0-100)"
    return cm


def _gradient_style(value_col: str, cm: bcm.LinearColormap, fill: float, line: float):
    def styler(feature):
        v = feature["properties"].get(value_col, 0) or 0
        return {
            "fillColor": cm(float(v)),
            "color": "#222",
            "weight": 0.3,
            "fillOpacity": float(fill),
            "opacity": float(line),
        }
    return styler


# ----------------------------------------------------------------------------
# Tooltip / popup
# ----------------------------------------------------------------------------
def _rich_popup_html(props: dict[str, Any]) -> str:
    score = props.get("score", 0) or 0
    direct = props.get("direct_activity_score", 0) or 0
    inherited = props.get("neighborhood_inherited_score", 0) or 0
    cls = props.get("class", "?")
    cluster = props.get("cluster_id", -1) or -1
    bairro = props.get("bairro", "?")

    def _row(label: str, key: str, suffix: str = "") -> str:
        v = props.get(key)
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            v = f"{v:.2f}"
        return f"<tr><td style='padding-right:8px;color:#666'>{label}</td><td><b>{v}</b>{suffix}</td></tr>"

    pos_rows = "".join(
        _row(label, key)
        for key, label in [
            ("pos_food", "alimentação"),
            ("pos_shop", "comércio"),
            ("pos_supermarket", "mercado"),
            ("pos_pharmacy", "farmácia"),
            ("pos_education", "educação"),
            ("pos_fitness", "academia"),
            ("pos_healthcare", "saúde"),
            ("pos_office", "escritórios"),
            ("pos_transport", "transporte"),
            ("pos_bank", "bancos"),
            ("pos_leisure", "lazer/turismo"),
            ("pos_residential", "residencial"),
            ("pos_commercial", "comercial"),
            ("pos_mixed_use", "mixed-use"),
            ("pos_road_density", "conectividade"),
            ("pos_anchor_proximity", "anchor prox."),
        ]
    )
    pen_rows = "".join(
        _row(label, key)
        for key, label in [
            ("pen_unsuitable_landuse", "inviável (landuse)"),
            ("pen_industrial", "industrial"),
            ("pen_isolation", "isolamento"),
            ("pen_low_connectivity", "baixa conectividade"),
        ]
    )
    cluster_html = (
        f"<b>Cluster #{int(cluster)}</b> · {bairro}<br>"
        if int(cluster) > 0 else f"<i>Sem cluster</i> · {bairro}<br>"
    )
    h3id = props.get("h3", "?")
    return f"""
    <div style="font:12px sans-serif; min-width:300px">
      <div style="font-weight:bold; font-size:14px; margin-bottom:4px">
        Score: {float(score):.1f} <span style='color:#888'>({cls})</span>
      </div>
      {cluster_html}
      <div style="margin:6px 0; padding:6px; background:#f3f7fb; border-radius:4px">
        <b>Anti-halo</b><br>
        atividade própria: <b>{float(direct):.1f}</b> ·
        herdada de vizinhos: <b>{float(inherited):.1f}</b>
      </div>
      <table style="font-size:11px">
        <tr><td colspan=2 style="font-weight:bold;color:#1a9850;padding-top:4px">Sinais positivos</td></tr>
        {pos_rows}
        <tr><td colspan=2 style="font-weight:bold;color:#b30000;padding-top:4px">Penalidades</td></tr>
        {pen_rows}
      </table>
      <div style="margin-top:6px;color:#999;font-size:10px">
        H3: {h3id}<br>
        Dica: clique-direito copia coordenadas do navegador.
      </div>
    </div>"""


def _add_grid_layer(
    m: folium.Map,
    grid: gpd.GeoDataFrame,
    cm: bcm.LinearColormap,
    *,
    name: str,
    value_col: str,
    fill_opacity: float,
    line_opacity: float,
    show: bool,
    add_popup: bool = True,
) -> folium.GeoJson:
    g = grid.copy()
    # round numeric for rendering
    for c in g.select_dtypes(include="float").columns:
        g[c] = g[c].round(3)
    # Folium tooltip wants flat field list; popup is full HTML.
    fg = folium.FeatureGroup(name=name, show=show)
    layer = folium.GeoJson(
        g.to_json(),
        style_function=_gradient_style(value_col, cm, fill_opacity, line_opacity),
        tooltip=folium.features.GeoJsonTooltip(
            fields=["score", "class", "bairro", "cluster_id"],
            aliases=["Score:", "Classe:", "Bairro:", "Cluster:"],
            sticky=True, labels=True, localize=True,
        ),
    )
    if add_popup:
        # We can't pass a HTML popup per-feature via GeoJsonPopup with arbitrary
        # markup, but Folium 0.14+ provides GeoJsonPopup with the same field
        # mechanism. For richer popups we rely on a sticky tooltip + click.
        layer = folium.GeoJson(
            g.to_json(),
            style_function=_gradient_style(value_col, cm, fill_opacity, line_opacity),
            tooltip=folium.features.GeoJsonTooltip(
                fields=["score", "actionability_score",
                        "direct_activity_score", "neighborhood_inherited_score",
                        "priority_tier", "class", "bairro", "cluster_id"],
                aliases=["Score final:", "Actionability:", "Atividade própria:",
                         "Herdada vizinhos:", "Tier:", "Classe:", "Bairro:", "Cluster:"],
                sticky=True, labels=True, localize=True,
            ),
            popup=folium.features.GeoJsonPopup(
                fields=["score", "actionability_score",
                        "direct_activity_score", "neighborhood_inherited_score",
                        "priority_tier", "flag_visual_review",
                        "class", "bairro", "cluster_id",
                        "pos_food", "pos_shop", "pos_supermarket", "pos_pharmacy",
                        "pos_education", "pos_fitness", "pos_healthcare", "pos_office",
                        "pos_transport", "pos_bank", "pos_leisure", "pos_residential",
                        "pos_commercial", "pos_mixed_use", "pos_road_density",
                        "pos_anchor_proximity",
                        "pen_unsuitable_landuse", "pen_industrial",
                        "pen_isolation", "pen_low_connectivity"],
                aliases=["Score final:", "Actionability:",
                         "Atividade própria:", "Herdada:",
                         "Tier:", "Flags:",
                         "Classe:", "Bairro:", "Cluster:",
                         "alimentação:", "comércio:", "mercado:", "farmácia:",
                         "educação:", "academia:", "saúde:", "escritórios:",
                         "transporte:", "bancos:", "lazer:", "residencial:",
                         "comercial:", "mixed-use:", "conectividade:", "anchor prox.:",
                         "PEN inviável:", "PEN industrial:",
                         "PEN isolamento:", "PEN baixa conectividade:"],
                labels=True, max_width=400,
            ),
        )
    layer.add_to(fg)
    fg.add_to(m)
    return fg


# ----------------------------------------------------------------------------
# Main map
# ----------------------------------------------------------------------------
def build_map(
    grid: gpd.GeoDataFrame,
    cfg: dict[str, Any],
    top_cells: pd.DataFrame | None = None,
    study_polygon_wkt: str | None = None,
    cluster_meta: pd.DataFrame | None = None,
    super_cluster_meta: pd.DataFrame | None = None,
    bottom_cells: pd.DataFrame | None = None,
    poi_layers: dict[str, gpd.GeoDataFrame] | None = None,
) -> folium.Map:
    m = folium.Map(
        location=cfg["map"]["center"],
        zoom_start=cfg["map"]["zoom_start"],
        tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.TileLayer("CartoDB positron", name="Carto Positron", control=True, show=False).add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Carto Dark", control=True, show=False).add_to(m)

    cm = _make_colormap()
    cm.add_to(m)

    fill_opacity = float(cfg["map"]["fill_opacity"])
    line_opacity = float(cfg["map"]["line_opacity"])

    # Main score layer (default)
    _add_grid_layer(m, grid, cm,
                    name="Score por célula (final)",
                    value_col="score",
                    fill_opacity=fill_opacity, line_opacity=line_opacity,
                    show=True)

    # Direct activity only (no smoothing)
    if "direct_activity_score" in grid.columns:
        _add_grid_layer(m, grid, cm,
                        name="🎯 Atividade própria (direct only)",
                        value_col="direct_activity_score",
                        fill_opacity=fill_opacity, line_opacity=line_opacity,
                        show=False)

    # Neighborhood-inherited only
    if "neighborhood_inherited_score" in grid.columns:
        _add_grid_layer(m, grid, cm,
                        name="🌐 Herdado da vizinhança (inherited only)",
                        value_col="neighborhood_inherited_score",
                        fill_opacity=fill_opacity, line_opacity=line_opacity,
                        show=False)

    # Penalties only — show as a red-only colormap
    if "penalty_total" in grid.columns:
        pen_cm = bcm.LinearColormap(
            colors=["#ffffff", "#ffd5d5", "#fc8d59", "#e34a33", "#b30000"],
            vmin=0, vmax=float(grid["penalty_total"].max() or 1),
        )
        gpen = grid.copy()
        for c in gpen.select_dtypes(include="float").columns:
            gpen[c] = gpen[c].round(3)
        fg_pen = folium.FeatureGroup(name="🔴 Penalidades (penalty only)", show=False)
        folium.GeoJson(
            gpen.to_json(),
            style_function=_gradient_style("penalty_total", pen_cm, 0.5, 0.1),
            tooltip=folium.features.GeoJsonTooltip(
                fields=["score", "penalty_total", "pen_unsuitable_landuse",
                        "pen_isolation", "pen_low_connectivity"],
                aliases=["Score:", "Penalidade total:", "PEN inviável:",
                         "PEN isolamento:", "PEN baixa conectividade:"],
                sticky=True, labels=True,
            ),
        ).add_to(fg_pen)
        fg_pen.add_to(m)

    # Smoothed heatmap (centroids weighted by score)
    if cfg["map"].get("include_heatmap_layer", True):
        pts = [
            [float(r.lat), float(r.lon), float(r.score) / 100.0]
            for r in grid.itertuples(index=False)
            if r.score > 0
        ]
        if pts:
            heat_group = folium.FeatureGroup(name="Heatmap suavizado", show=False)
            HeatMap(
                pts, radius=18, blur=22, min_opacity=0.25, max_zoom=15,
                gradient={"0.0": "#b30000", "0.25": "#fc8d59",
                          "0.5": "#ffffbf", "0.75": "#a6d96a", "1.0": "#1a9850"},
            ).add_to(heat_group)
            heat_group.add_to(m)

    # Top clusters as polygon outlines + numbered labels
    if cluster_meta is not None and not cluster_meta.empty:
        top_n = int(cfg.get("clusters", {}).get("top_n", 10))
        cluster_layer = folium.FeatureGroup(name="🏷️ Top clusters (polygon)", show=True)
        labels_layer = folium.FeatureGroup(name="🏷️ Top clusters (labels 1-N)", show=True)
        for _, row in cluster_meta.head(top_n).iterrows():
            cells = grid.iloc[row["cell_idx"]]
            try:
                geom = unary_union(cells.geometry.values).buffer(0)
            except Exception:
                continue
            folium.GeoJson(
                gpd.GeoSeries([geom], crs="EPSG:4326").to_json(),
                style_function=lambda f: {
                    "color": "#0033aa", "weight": 3, "fill": False,
                    "dashArray": "6,4",
                },
                tooltip=(f"<b>Cluster #{int(row['cluster_id'])}</b><br>"
                         f"{row['bairro']}<br>"
                         f"score médio {row['score_mean']:.0f}, "
                         f"máx {row['score_max']:.0f}, "
                         f"{int(row['n_cells'])} células"),
            ).add_to(cluster_layer)
            # numbered label as DivIcon
            folium.Marker(
                location=[row["centroid_lat"], row["centroid_lon"]],
                icon=folium.DivIcon(
                    html=(f"<div style='background:#0033aa;color:white;border-radius:50%;"
                          f"width:28px;height:28px;line-height:28px;text-align:center;"
                          f"font-weight:bold;font-size:14px;border:2px solid white;"
                          f"box-shadow:0 0 4px rgba(0,0,0,.5)'>"
                          f"{int(row['cluster_id'])}</div>"),
                    icon_size=(28, 28), icon_anchor=(14, 14),
                ),
            ).add_to(labels_layer)
        cluster_layer.add_to(m)
        labels_layer.add_to(m)

    # Super-clusters as merged polygons + labels
    if super_cluster_meta is not None and not super_cluster_meta.empty:
        sc_layer = folium.FeatureGroup(name="🏙️ Super clusters (polygon)", show=True)
        sc_labels = folium.FeatureGroup(name="🏙️ Super clusters (labels)", show=True)
        for _, row in super_cluster_meta.iterrows():
            cells = grid.iloc[row["cell_idx"]]
            try:
                geom = unary_union(cells.geometry.values).buffer(0)
            except Exception:
                continue
            color = {"alta": "#7a00d9", "média": "#b17bff", "baixa": "#cfcfcf"}.get(
                row["prioridade_visita"], "#7a00d9"
            )
            folium.GeoJson(
                gpd.GeoSeries([geom], crs="EPSG:4326").to_json(),
                style_function=lambda f, c=color: {
                    "color": c, "weight": 4, "fill": True, "fillColor": c,
                    "fillOpacity": 0.08,
                },
                tooltip=(
                    f"<b>Super #{int(row['super_cluster_id'])}</b> · "
                    f"{row['bairro_principal']}<br>"
                    f"micro-clusters unidos: {int(row['n_micro_clusters'])}<br>"
                    f"{int(row['n_cells_total'])} cells, score médio "
                    f"{row['score_medio']:.0f}, "
                    f"direct share {row['direct_share_medio']*100:.0f}%<br>"
                    f"<i>{row['principais_sinais']}</i>"
                ),
            ).add_to(sc_layer)
            folium.Marker(
                location=[row["centroid_lat"], row["centroid_lon"]],
                icon=folium.DivIcon(
                    html=(
                        f"<div style='background:{color};color:white;"
                        f"border-radius:6px;padding:2px 6px;"
                        f"font-weight:bold;font-size:13px;"
                        f"border:2px solid white;white-space:nowrap;"
                        f"box-shadow:0 0 4px rgba(0,0,0,.5)'>"
                        f"S#{int(row['super_cluster_id'])} · "
                        f"{row['bairro_principal']}</div>"
                    ),
                    icon_size=(120, 22), icon_anchor=(60, 11),
                ),
            ).add_to(sc_labels)
        sc_layer.add_to(m)
        sc_labels.add_to(m)

    # Top-40 markers
    if top_cells is not None and not top_cells.empty:
        cluster = MarkerCluster(name="⭐ Top 40 cells", show=True)
        for _, row in top_cells.head(40).iterrows():
            html = (
                f"<b>Rank #{int(row['rank'])}</b><br>"
                f"Score: <b>{row['score']:.1f}</b> ({row['class']})<br>"
                f"H3: {row['h3']}<br>"
                f"Lat/Lon: <code>{row['lat']:.5f}, {row['lon']:.5f}</code>"
            )
            folium.Marker(
                location=[row["lat"], row["lon"]],
                tooltip=f"#{int(row['rank'])} — {row['score']:.1f}",
                popup=folium.Popup(html, max_width=350),
                icon=folium.Icon(color="green", icon="star", prefix="fa"),
            ).add_to(cluster)
        cluster.add_to(m)

    # Bottom-40 markers
    if bottom_cells is not None and not bottom_cells.empty:
        bcluster = MarkerCluster(name="⛔ Bottom 40 cells", show=False)
        for _, row in bottom_cells.head(40).iterrows():
            html = (
                f"Score: <b>{row['score']:.1f}</b> ({row.get('class','?')})<br>"
                f"H3: {row.get('h3','?')}<br>"
                f"Lat/Lon: <code>{row['lat']:.5f}, {row['lon']:.5f}</code>"
            )
            folium.Marker(
                location=[row["lat"], row["lon"]],
                tooltip=f"score {row['score']:.1f}",
                popup=folium.Popup(html, max_width=300),
                icon=folium.Icon(color="red", icon="ban", prefix="fa"),
            ).add_to(bcluster)
        bcluster.add_to(m)

    # POIs by category as separate togglable layers
    if poi_layers:
        for cat, gdf in poi_layers.items():
            if gdf is None or gdf.empty:
                continue
            pts = gdf[gdf.geometry.geom_type == "Point"]
            if pts.empty:
                continue
            cat_layer = folium.FeatureGroup(name=f"POI · {cat} ({len(pts)})", show=False)
            for _, r in pts.iterrows():
                folium.CircleMarker(
                    location=[r.geometry.y, r.geometry.x],
                    radius=2.5, color="#222", weight=0.5,
                    fillColor="#3a89c9", fillOpacity=0.85,
                    tooltip=f"{cat}: {r.get('tags', {}).get('name', '?')}",
                ).add_to(cat_layer)
            cat_layer.add_to(m)

    # Study area outline
    from shapely import wkt as _wkt
    if study_polygon_wkt:
        try:
            poly = _wkt.loads(study_polygon_wkt)
            folium.GeoJson(
                gpd.GeoSeries([poly], crs="EPSG:4326").to_json(),
                name="Área de estudo",
                style_function=lambda _f: {
                    "color": "#000", "weight": 2, "fill": False,
                    "dashArray": "5,5",
                },
            ).add_to(m)
        except Exception:
            pass

    folium.LayerControl(collapsed=False).add_to(m)
    _add_info_panel(m, cfg)
    _add_audit_panel(m)
    return m


def _add_info_panel(m: folium.Map, cfg: dict[str, Any]) -> None:
    html = f"""
    <div style="
        position: fixed; bottom: 24px; left: 24px; z-index: 9999;
        background: rgba(255,255,255,0.92); padding: 10px 14px;
        border: 1px solid #888; border-radius: 6px; font: 12px/1.3 sans-serif;
        max-width: 360px;">
      <b>Vending Machine Heatmap — {cfg['city']['name']}</b><br>
      Score 0-100 combinando POIs, landuse, conectividade e penalidades.<br>
      <b>Classes</b>:
        <span style='color:#b30000'>0-20 muito ruim</span> ·
        <span style='color:#fc8d59'>20-40 ruim</span> ·
        <span style='color:#e0bf0b'>40-60 médio</span> ·
        <span style='color:#66bd63'>60-80 bom</span> ·
        <span style='color:#1a9850'>80-100 muito bom</span><br>
      Clique em uma célula para ver o breakdown completo
      (incluindo "atividade própria" vs "herdada da vizinhança").
    </div>"""
    m.get_root().html.add_child(folium.Element(html))


def _add_audit_panel(m: folium.Map) -> None:
    """Floating panel with one-click presets to enable layers for audit mode."""
    js = """
    <div id="audit-panel" style="
      position: fixed; top: 80px; left: 18px; z-index: 9999;
      background: rgba(255,255,255,.95); padding: 8px 10px;
      border:1px solid #888; border-radius:6px; font:12px sans-serif;">
      <b>Audit Mode</b><br>
      <button onclick="window._auditOn()"
        style="margin-top:4px;background:#0033aa;color:#fff;border:none;
        padding:4px 8px;border-radius:4px;cursor:pointer">
        Ligar todas as camadas relevantes
      </button>
    </div>
    <script>
    window._auditOn = function() {
      const wanted = [
        'Score por célula (final)',
        '🏷️ Top clusters (polygon)',
        '🏷️ Top clusters (labels 1-N)',
        '⭐ Top 40 cells',
        '⛔ Bottom 40 cells',
        'Área de estudo'
      ];
      document.querySelectorAll('.leaflet-control-layers-overlays label').forEach(l => {
        const txt = (l.textContent || '').trim();
        const cb = l.querySelector('input[type=checkbox]');
        if (cb) {
          const on = wanted.some(w => txt.indexOf(w) !== -1);
          if (on && !cb.checked) cb.click();
        }
      });
    };
    </script>
    """
    m.get_root().html.add_child(folium.Element(js))


def save_map(m: folium.Map, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(p))
    return p
