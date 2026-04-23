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
    score, breakdown = S.compute_score(features, cfg["weights"])
    cls = S.classify(score)

    grid_scored = grid.copy()
    grid_scored["score"] = score.values
    grid_scored["class"] = cls.values
    for col in breakdown.columns:
        if col == "score":
            continue
        grid_scored[col] = breakdown[col].values
    # also expose a few raw counts for inspection
    for col in poi_counts.columns:
        grid_scored[col] = poi_counts[col].values

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

    # --- Interactive map ----------------------------------------------
    from shapely import wkt as _wkt

    m = build_map(
        grid_scored,
        cfg,
        top_cells=top_csv,
        study_polygon_wkt=poly.wkt,
    )
    html_path = out_dir / cfg["output"]["html"]
    save_map(m, html_path)
    LOG.info("wrote %s", html_path)

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
