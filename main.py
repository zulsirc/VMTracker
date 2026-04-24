"""Entry point.

Usage:
    python main.py --config configs/macae.yaml
    python main.py --city macae    # shortcut for configs/<city>.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from src import features as FEAT
from src import geometry as G
from src import scoring as S
from src.data_sources import DataSources
from src.report import write_report
from src.utils import ensure_dir, load_config, setup_logging
from src.visualization import build_map, save_map

LOG = setup_logging()


def _write_kml(cluster_meta: pd.DataFrame, path) -> None:
    """Tiny KML writer for top-cluster centroids (good for GMaps/Earth)."""
    pms: list[str] = []
    for _, row in cluster_meta.iterrows():
        pms.append(
            f"""    <Placemark>
      <name>Cluster #{int(row['cluster_id'])} — {row['bairro']}</name>
      <description><![CDATA[
        Cells: {int(row['n_cells'])}<br/>
        Score mean: {row['score_mean']:.1f}<br/>
        Score max: {row['score_max']:.1f}<br/>
        Radius: {row['radius_m']:.0f} m
      ]]></description>
      <Point><coordinates>{row['centroid_lon']:.6f},{row['centroid_lat']:.6f},0</coordinates></Point>
    </Placemark>"""
        )
    body = "\n".join(pms)
    kml = (
        f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Vending Machine — Top Clusters</name>
{body}
  </Document>
</kml>"""
    )
    from pathlib import Path as _P
    _P(path).write_text(kml, encoding="utf-8")


def _build_spatial_validation(
    grid_scored: pd.DataFrame, cluster_meta: pd.DataFrame
) -> pd.DataFrame:
    df = grid_scored.copy()
    cols = [
        "h3", "lat", "lon", "cluster_id", "bairro",
        "score", "direct_activity_score", "neighborhood_inherited_score",
        "penalty_total", "class",
        "raw_lu_frac_unsuitable",
    ]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out = out.rename(columns={
        "score": "score_final",
        "penalty_total": "penalty_score",
        "class": "classe_final",
        "raw_lu_frac_unsuitable": "raw_unsuitable_frac",
    })
    # auto flags
    flags = []
    notes = []
    for _, r in out.iterrows():
        f: list[str] = []
        n: list[str] = []
        sf = float(r.get("score_final", 0) or 0)
        da = float(r.get("direct_activity_score", 0) or 0)
        nh = float(r.get("neighborhood_inherited_score", 0) or 0)
        ru = float(r.get("raw_unsuitable_frac", 0) or 0)
        if sf >= 70 and da <= 35:
            f.append("halo_dominated")
            n.append(f"score {sf:.0f} mas atividade direta apenas {da:.0f}")
        if sf >= 70 and ru >= 0.3:
            f.append("inviable_landuse_present")
            n.append(f"raw unsuitable {ru:.2f}")
        if sf >= 55 and nh > sf * 0.55:
            f.append("inherited_majority")
            n.append(f"{nh/max(sf,1)*100:.0f}% do score vem da vizinhança")
        flags.append(",".join(f) if f else "")
        notes.append("; ".join(n) if n else "")
    out["flag_visual_review"] = flags
    out["review_note"] = notes
    return out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Vending Machine Heatmap")
    ap.add_argument("--config", type=str, help="Path to YAML config.")
    ap.add_argument(
        "--city",
        type=str,
        help="Shortcut: loads configs/<city>.yaml (default macae).",
        default=None,
    )
    ap.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip Overpass fetching; use only what is already cached.",
    )
    return ap.parse_args()


def resolve_config_path(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config)
    city = args.city or "macae"
    return Path("configs") / f"{city}.yaml"


def fetch_all_layers(cfg: dict[str, Any], ds: DataSources) -> dict[str, Any]:
    poi_layers: dict[str, gpd.GeoDataFrame] = {}
    for cat, spec in cfg["poi_categories"].items():
        raw = ds.fetch_poi(cat, spec["query"])
        gdf = G.overpass_to_gdf(raw)
        LOG.info("POI[%s]: %d elements", cat, len(gdf))
        poi_layers[cat] = gdf

    landuse_layers: dict[str, gpd.GeoDataFrame] = {}
    for cat, spec in cfg["landuse_categories"].items():
        raw = ds.fetch_landuse(cat, spec["query"])
        gdf = G.polygons_from_overpass(raw)
        LOG.info("LANDUSE[%s]: %d polygons", cat, len(gdf))
        landuse_layers[cat] = gdf

    road_raw = ds.fetch_roads(cfg["roads"]["query"])
    roads_gdf = G.overpass_roads_to_gdf(road_raw)
    LOG.info("ROADS: %d segments", len(roads_gdf))

    return {
        "poi_layers": poi_layers,
        "landuse_layers": landuse_layers,
        "roads": roads_gdf,
    }


def run(cfg: dict[str, Any]) -> dict[str, Any]:
    out_dir = ensure_dir(cfg["output"]["dir"])

    # --- Study area & grid --------------------------------------------
    poly = G.study_polygon(cfg)
    LOG.info("study polygon area ~ %.2f km²", poly.area * 111 * 111 * abs(
        0.94  # rough cos(lat) at -22°
    ))
    grid = G.build_h3_grid(poly, cfg["grid"]["h3_resolution"])
    # keep only cells whose centroid falls inside the polygon (edge cells that
    # only touch the exterior are already included by h3; this is a hard clip)
    cent = gpd.GeoSeries(
        gpd.points_from_xy(grid["lon"], grid["lat"]),
        crs="EPSG:4326",
    )
    grid = grid[cent.within(poly)].reset_index(drop=True)
    LOG.info("grid after polygon clip: %d cells", len(grid))

    # --- Data fetching -------------------------------------------------
    ds = DataSources(cfg)
    layers = fetch_all_layers(cfg, ds)

    # clip layers to polygon
    for k, gdf in list(layers["poi_layers"].items()):
        if not gdf.empty:
            layers["poi_layers"][k] = G.clip_to_polygon(gdf, poly)
    for k, gdf in list(layers["landuse_layers"].items()):
        if not gdf.empty:
            layers["landuse_layers"][k] = G.clip_to_polygon(gdf, poly)
    if not layers["roads"].empty:
        layers["roads"] = G.clip_to_polygon(layers["roads"], poly)

    # --- Features ------------------------------------------------------
    poi_counts = FEAT.compute_poi_counts(grid, layers["poi_layers"])
    road_df = FEAT.compute_road_density(grid, layers["roads"])
    landuse_df = FEAT.compute_landuse_fractions(grid, layers["landuse_layers"])

    # --- Smooth features over H3 neighborhood -------------------------
    smooth_cfg = cfg.get("smoothing", {})
    rings = int(smooth_cfg.get("neighbor_rings", 2))
    decay = float(smooth_cfg.get("decay", 0.55))
    poi_smoothed = FEAT.smooth_over_rings(grid, poi_counts, rings=rings, decay=decay)
    landuse_smoothed = FEAT.smooth_over_rings(grid, landuse_df, rings=rings, decay=decay)
    road_smoothed = FEAT.smooth_over_rings(grid, road_df, rings=rings, decay=decay)
    # assemble_feature_frame expects raw landuse/road column names (no _s);
    # POI uses count_X_s (kept as-is).
    landuse_smoothed.columns = list(landuse_df.columns)
    road_smoothed.columns = list(road_df.columns)

    categories = list(cfg["poi_categories"].keys())
    mixed = FEAT.diversity_score(poi_smoothed, categories)
    isolation = FEAT.isolation_penalty(poi_smoothed, categories)
    anchor_prox = FEAT.compute_anchor_proximity(grid, layers["poi_layers"])

    features = S.assemble_feature_frame(
        grid.index, poi_smoothed, road_smoothed, landuse_smoothed, mixed, isolation,
        anchor_proximity=anchor_prox,
    )

    # --- Score ---------------------------------------------------------
    raw_unsuitable = landuse_df.get(
        "lu_frac_unsuitable", pd.Series(0.0, index=grid.index)
    )
    score, breakdown = S.compute_score(
        features, cfg["weights"], raw_unsuitable_frac=raw_unsuitable
    )
    cls = S.classify(score)

    # --- Anti-halo: direct vs inherited --------------------------------
    from src import anti_halo as AH
    direct_score, inherited_score, breakdown_direct = AH.compute_direct_and_inherited(
        grid=grid,
        poi_counts_unsmoothed=poi_counts,
        road_df_unsmoothed=road_df,
        landuse_df_unsmoothed=landuse_df,
        features_smoothed=features,
        anchor_proximity=anchor_prox,
        weights=cfg["weights"],
        score_total=score,
        raw_total=breakdown["raw"],
        raw_unsuitable_frac=raw_unsuitable,
    )
    LOG.info(
        "anti-halo: direct mean=%.1f inherited mean=%.1f",
        float(direct_score.mean()), float(inherited_score.mean()),
    )

    grid_scored = grid.copy()
    grid_scored["score"] = score.values
    grid_scored["class"] = cls.values
    grid_scored["direct_activity_score"] = direct_score.values
    grid_scored["neighborhood_inherited_score"] = inherited_score.values
    for col in breakdown.columns:
        if col == "score":
            continue
        grid_scored[col] = breakdown[col].values
    # also expose a few raw counts for inspection
    for col in poi_counts.columns:
        grid_scored[col] = poi_counts[col].values
    # raw feature values (before weighting) — useful for auditing
    for feat_col in (
        "unsuitable_frac",
        "industrial_frac",
        "residential",
        "commercial",
        "road_density",
        "mixed_use",
        "isolation",
        "anchor_proximity",
        "low_connectivity",
    ):
        if feat_col in features.columns:
            grid_scored[f"feat_{feat_col}"] = features[feat_col].values
    # raw (un-smoothed) landuse fractions — so audits can distinguish
    # "this cell is itself unsuitable" from "a neighbor is".
    for lu_col in (
        "lu_frac_unsuitable",
        "lu_frac_residential",
        "lu_frac_commercial",
        "lu_frac_industrial",
    ):
        if lu_col in landuse_df.columns:
            grid_scored[f"raw_{lu_col}"] = landuse_df[lu_col].values

    # --- Outputs -------------------------------------------------------
    geojson_path = out_dir / cfg["output"]["geojson"]
    grid_scored.to_file(geojson_path, driver="GeoJSON")
    LOG.info("wrote %s", geojson_path)

    csv_all = grid_scored.drop(columns="geometry").copy()
    csv_all.to_csv(out_dir / cfg["output"]["csv_all"], index=False)

    top = (
        grid_scored.sort_values("score", ascending=False)
        .head(cfg["output"]["top_n"])
        .reset_index(drop=True)
    )
    top["rank"] = top.index + 1
    top_csv = top.drop(columns="geometry").copy()
    top_csv.to_csv(out_dir / cfg["output"]["csv_top"], index=False)

    # --- Clusters & operational artifacts -----------------------------
    from src import clusters as CL

    cluster_threshold = float(cfg.get("clusters", {}).get("score_threshold", 60.0))
    cluster_min_cells = int(cfg.get("clusters", {}).get("min_cells", 2))
    cluster_top_n = int(cfg.get("clusters", {}).get("top_n", 10))
    cluster_id_series, cluster_meta = CL.build_clusters(
        grid_scored, score_threshold=cluster_threshold,
        min_cells=cluster_min_cells,
        peak_radius_rings=int(cfg.get("clusters", {}).get("peak_radius_rings", 3)),
        target_clusters=cluster_top_n,
    )
    grid_scored["cluster_id"] = cluster_id_series.values
    grid_scored["bairro"] = [
        CL.nearest_bairro(lat, lon)
        for lat, lon in zip(grid_scored["lat"], grid_scored["lon"])
    ]
    LOG.info("clusters built: %d (threshold=%.0f)", len(cluster_meta), cluster_threshold)

    # field-visit shortlist
    short = CL.shortlist(
        grid_scored, cluster_meta,
        top_n=int(cfg.get("clusters", {}).get("top_n", 10)),
    )
    short_path = out_dir / "field_visit_shortlist.csv"
    short.to_csv(short_path, index=False)
    LOG.info("wrote %s", short_path)

    # clusters geojson + kml (only top N)
    if not cluster_meta.empty:
        from shapely.geometry import MultiPolygon, mapping
        from shapely.ops import unary_union

        top_clusters_n = int(cfg.get("clusters", {}).get("top_n", 10))
        feats: list[dict[str, Any]] = []
        for _, row in cluster_meta.head(top_clusters_n).iterrows():
            cells = grid_scored.iloc[row["cell_idx"]]
            try:
                geom = unary_union(cells.geometry.values).buffer(0)
            except Exception:
                geom = MultiPolygon(list(cells.geometry.values))
            props = {
                "cluster_id": int(row["cluster_id"]),
                "bairro": row["bairro"],
                "score_mean": round(float(row["score_mean"]), 2),
                "score_max": round(float(row["score_max"]), 2),
                "n_cells": int(row["n_cells"]),
                "radius_m": round(float(row["radius_m"]), 0),
                "principais_sinais": CL.cluster_top_signals(grid_scored, row["cell_idx"]),
            }
            feats.append({"type": "Feature", "geometry": mapping(geom), "properties": props})
        clusters_geojson = {"type": "FeatureCollection", "features": feats}
        cgj_path = out_dir / "clusters_top.geojson"
        with cgj_path.open("w", encoding="utf-8") as fh:
            import json as _json
            _json.dump(clusters_geojson, fh, ensure_ascii=False)
        LOG.info("wrote %s", cgj_path)

        # KML (simple)
        kml_path = out_dir / "clusters_top.kml"
        _write_kml(cluster_meta.head(top_clusters_n), kml_path)
        LOG.info("wrote %s", kml_path)

    # spatial validation CSV with auto-flags
    spv = _build_spatial_validation(grid_scored, cluster_meta)
    spv_path = out_dir / "audit" / "spatial_validation.csv"
    spv_path.parent.mkdir(parents=True, exist_ok=True)

    # attach flags into grid_scored too (for actionability)
    flags_by_h3 = dict(zip(spv["h3"], spv["flag_visual_review"].fillna("")))
    grid_scored["flag_visual_review"] = [
        flags_by_h3.get(h, "") for h in grid_scored["h3"]
    ]

    # --- Actionability -------------------------------------------------
    from src import actionability as ACT
    act = ACT.compute_actionability(grid_scored, grid_scored["flag_visual_review"])
    grid_scored["actionability_score"] = act.values
    tier = ACT.priority_tier(grid_scored, act, grid_scored["flag_visual_review"])
    grid_scored["priority_tier"] = tier.values
    LOG.info(
        "actionability: mean=%.1f median=%.1f",
        float(act.mean()), float(act.median()),
    )

    # push actionability + tier into spv for export
    spv["actionability_score"] = [
        float(grid_scored.loc[grid_scored["h3"] == h, "actionability_score"].iloc[0])
        for h in spv["h3"]
    ]
    spv["priority_tier"] = [
        str(grid_scored.loc[grid_scored["h3"] == h, "priority_tier"].iloc[0])
        for h in spv["h3"]
    ]
    spv.to_csv(spv_path, index=False)
    LOG.info("wrote %s", spv_path)

    # field_route_priority.csv — all cells with tier != "-", ranked by tier+act
    fr_prio = grid_scored[grid_scored["priority_tier"] != "-"][[
        "h3", "lat", "lon", "bairro", "cluster_id",
        "score", "direct_activity_score", "neighborhood_inherited_score",
        "actionability_score", "priority_tier", "flag_visual_review",
    ]].copy()
    fr_prio.columns = [
        "h3", "lat", "lon", "bairro", "cluster_id",
        "score_final", "direct_activity_score", "inherited_score",
        "actionability_score", "priority_tier", "flags",
    ]
    tier_order = {"visitar_agora": 0, "validar_visualmente": 1, "suspeita_halo": 2}
    fr_prio["_t"] = fr_prio["priority_tier"].map(tier_order).fillna(3)
    fr_prio = fr_prio.sort_values(
        ["_t", "actionability_score"], ascending=[True, False]
    ).drop(columns="_t").reset_index(drop=True)
    fr_prio.to_csv(out_dir / "field_route_priority.csv", index=False)
    LOG.info("wrote %s", out_dir / "field_route_priority.csv")

    # refresh shortlist with actionability_score
    cells_by_h3 = grid_scored.set_index("h3")
    act_by_cluster = (
        grid_scored[grid_scored["cluster_id"] > 0]
        .groupby("cluster_id")["actionability_score"].mean().round(2)
    )
    short["actionability_score"] = short["cluster_id"].map(act_by_cluster)
    short.to_csv(short_path, index=False)

    # --- Super-clusters ------------------------------------------------
    from src import super_clusters as SC
    merge_m = float(cfg.get("clusters", {}).get("super_cluster_merge_m", 400.0))
    seed_rings = int(cfg.get("clusters", {}).get("super_cluster_seed_rings", 2))
    super_meta = SC.build_super_clusters(
        grid_scored, cluster_meta,
        merge_distance_m=merge_m,
        seed_h3_distance=seed_rings,
    )
    LOG.info(
        "super-clusters built: %d (merge_m=%.0f)",
        len(super_meta), merge_m,
    )

    if not super_meta.empty:
        # add actionability share
        sc_act = []
        for _, srow in super_meta.iterrows():
            cells = grid_scored.iloc[srow["cell_idx"]]
            sc_act.append(round(float(cells["actionability_score"].mean()), 2))
        super_meta["actionability_medio"] = sc_act

        # export CSV (skip list columns that are hard to CSV-serialize)
        sc_csv = super_meta.copy()
        sc_csv["bairros"] = sc_csv["bairros"].apply(lambda v: ";".join(map(str, v)))
        sc_csv["micro_cluster_ids"] = sc_csv["micro_cluster_ids"].apply(
            lambda v: ";".join(map(str, v))
        )
        sc_csv.drop(columns=["cell_idx"]).to_csv(
            out_dir / "super_clusters.csv", index=False,
        )
        LOG.info("wrote %s", out_dir / "super_clusters.csv")

        # GeoJSON of super-cluster polygon unions
        from shapely.geometry import mapping
        from shapely.ops import unary_union
        import json as _json

        feats_sc: list[dict[str, Any]] = []
        for _, row in super_meta.iterrows():
            cells = grid_scored.iloc[row["cell_idx"]]
            try:
                geom = unary_union(cells.geometry.values).buffer(0)
            except Exception:
                continue
            feats_sc.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "super_cluster_id": int(row["super_cluster_id"]),
                    "micro_cluster_ids": list(row["micro_cluster_ids"]),
                    "bairro_principal": row["bairro_principal"],
                    "bairros": list(row["bairros"]),
                    "n_micro_clusters": int(row["n_micro_clusters"]),
                    "n_cells_total": int(row["n_cells_total"]),
                    "score_medio": float(row["score_medio"]),
                    "score_max": float(row["score_max"]),
                    "inherited_share_medio": float(row["inherited_share_medio"]),
                    "direct_share_medio": float(row["direct_share_medio"]),
                    "actionability_medio": float(row["actionability_medio"]),
                    "raio_m": float(row["raio_m"]),
                    "principais_sinais": row["principais_sinais"],
                    "justificativa": row["justificativa"],
                    "prioridade_visita": row["prioridade_visita"],
                },
            })
        sc_gj_path = out_dir / "super_clusters.geojson"
        with sc_gj_path.open("w", encoding="utf-8") as fh:
            _json.dump({"type": "FeatureCollection", "features": feats_sc},
                       fh, ensure_ascii=False)
        LOG.info("wrote %s", sc_gj_path)

    # --- Scenario comparison -------------------------------------------
    from src import scenarios as SCE
    beach_raw = ds.fetch_landuse("beach", SCE.BEACH_TAGS)
    beach_gdf = G.polygons_from_overpass(beach_raw)
    if not beach_gdf.empty:
        beach_gdf = G.clip_to_polygon(beach_gdf, poly)
    LOG.info("beach polygons: %d", len(beach_gdf))

    beach_prox = SCE.compute_beach_proximity(grid_scored, beach_gdf)
    grid_scored["beach_proximity"] = beach_prox.values

    scenario = str(cfg.get("scenario", "convenience_urban"))
    grid_scored = SCE.apply_scenario(grid_scored, beach_prox, scenario)
    LOG.info("applied scenario: %s", scenario)

    scenario_compare = SCE.compare_scenarios(grid_scored, beach_prox)
    scenario_compare.to_csv(out_dir / "scenario_compare.csv", index=False)
    LOG.info("wrote %s", out_dir / "scenario_compare.csv")

    # --- Routing -------------------------------------------------------
    from src import routing as RT
    max_d1 = int(cfg.get("routing", {}).get("max_stops_day1", 8))
    max_d2 = int(cfg.get("routing", {}).get("max_stops_day2", 8))
    day1, day2 = RT.build_routes(
        super_meta if not super_meta.empty else pd.DataFrame(),
        cluster_meta, grid_scored,
        max_stops_day1=max_d1, max_stops_day2=max_d2,
    )
    day1.to_csv(out_dir / "field_route_day1.csv", index=False)
    day2.to_csv(out_dir / "field_route_day2.csv", index=False)
    RT.route_to_kml(day1, out_dir / "field_route_day1.kml", "Rota de campo — Dia 1")
    RT.route_to_kml(day2, out_dir / "field_route_day2.kml", "Rota de campo — Dia 2")
    LOG.info("wrote field_route_day1/2.csv + .kml")

    # --- Interactive map ----------------------------------------------
    from shapely import wkt as _wkt

    m = build_map(
        grid_scored,
        cfg,
        top_cells=top_csv,
        study_polygon_wkt=poly.wkt,
        cluster_meta=cluster_meta,
        super_cluster_meta=super_meta if not super_meta.empty else None,
        bottom_cells=grid_scored.sort_values("score").head(40).copy(),
        poi_layers=layers["poi_layers"],
    )
    html_path = out_dir / cfg["output"]["html"]
    save_map(m, html_path)
    LOG.info("wrote %s", html_path)

    # --- Field-review map (lighter) -----------------------------------
    from src.field_review import build_field_review_map
    fr = build_field_review_map(
        grid_scored, cluster_meta, short, study_polygon_wkt=poly.wkt, cfg=cfg,
        super_cluster_meta=super_meta if not super_meta.empty else None,
    )
    fr_path = out_dir / "field_review_map.html"
    save_map(fr, fr_path)
    LOG.info("wrote %s", fr_path)

    # --- Report --------------------------------------------------------
    stats = {
        "cells total": len(grid_scored),
        "score min": round(float(grid_scored["score"].min()), 2),
        "score mean": round(float(grid_scored["score"].mean()), 2),
        "score median": round(float(grid_scored["score"].median()), 2),
        "score max": round(float(grid_scored["score"].max()), 2),
        "cells >= 60 (bom+)": int((grid_scored["score"] >= 60).sum()),
        "cells >= 80 (muito bom)": int((grid_scored["score"] >= 80).sum()),
        "POIs total": int(sum(len(g) for g in layers["poi_layers"].values())),
        "road segments": int(len(layers["roads"])),
    }
    report_path = out_dir / cfg["output"]["report_md"]
    write_report(cfg, stats, top_csv, report_path)
    LOG.info("wrote %s", report_path)

    return {
        "grid": grid_scored,
        "html": html_path,
        "geojson": geojson_path,
        "report": report_path,
        "top": top_csv,
        "stats": stats,
    }


def main() -> int:
    args = parse_args()
    cfg_path = resolve_config_path(args)
    cfg = load_config(cfg_path)
    LOG.info("loaded config %s", cfg_path)
    result = run(cfg)
    LOG.info("DONE. Open %s in your browser.", result["html"])
    print(f"\n=== Finished ===")
    print(f"HTML:    {result['html']}")
    print(f"GeoJSON: {result['geojson']}")
    print(f"Report:  {result['report']}")
    for k, v in result["stats"].items():
        print(f"  {k:<24} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
