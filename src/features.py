"""Turns raw OSM layers into per-cell numeric features."""
from __future__ import annotations

from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import geometry as G
from .utils import setup_logging

LOG = setup_logging()


def _safe_counts(layer_gdf: gpd.GeoDataFrame, grid: gpd.GeoDataFrame, col: str) -> pd.Series:
    if layer_gdf is None or layer_gdf.empty:
        return pd.Series(0, index=grid.index, name=col, dtype="int64")
    # Some layers might contain non-points (rare with out center); keep only point geoms
    pts = layer_gdf[layer_gdf.geometry.geom_type == "Point"].copy()
    if pts.empty:
        return pd.Series(0, index=grid.index, name=col, dtype="int64")
    return G.point_in_cell_counts(pts, grid, col)


def compute_poi_counts(
    grid: gpd.GeoDataFrame,
    poi_layers: dict[str, gpd.GeoDataFrame],
) -> pd.DataFrame:
    """One count column per POI category, aligned to grid.index."""
    out = pd.DataFrame(index=grid.index)
    for cat, gdf in poi_layers.items():
        out[f"count_{cat}"] = _safe_counts(gdf, grid, f"count_{cat}")
    return out


def compute_road_density(
    grid: gpd.GeoDataFrame, roads_gdf: gpd.GeoDataFrame
) -> pd.DataFrame:
    out = pd.DataFrame(index=grid.index)
    length = G.road_length_per_cell(roads_gdf, grid)
    # density in meters per km²
    area = grid["area_km2"].replace(0, np.nan)
    out["road_length_m"] = length
    out["road_density_m_per_km2"] = (length / area).fillna(0.0)
    return out


def compute_anchor_proximity(
    grid: gpd.GeoDataFrame,
    poi_layers: dict[str, gpd.GeoDataFrame],
    anchor_categories: tuple[str, ...] = (
        "food", "shop", "supermarket", "pharmacy", "transport",
    ),
) -> pd.Series:
    """Return a 0..1 proximity signal: 1 near a strong anchor, fading to 0.

    We project anchors and cell centroids to a metric CRS, then use a
    cKDTree to pull the distance (m) to the nearest anchor for every cell.
    Then map distance -> exp(-d / scale). This gives every cell a
    continuous, smoothly-varying value, so even empty cells differentiate
    by how far they sit from the urban fabric.
    """
    pts_list: list[gpd.GeoDataFrame] = []
    for cat in anchor_categories:
        gdf = poi_layers.get(cat)
        if gdf is None or gdf.empty:
            continue
        p = gdf[gdf.geometry.geom_type == "Point"]
        if not p.empty:
            pts_list.append(p[["geometry"]])
    if not pts_list:
        return pd.Series(0.0, index=grid.index, name="anchor_proximity")
    anchors = pd.concat(pts_list, ignore_index=True)
    anchors = gpd.GeoDataFrame(anchors, geometry="geometry", crs="EPSG:4326").to_crs(3857)
    grid_m = grid.to_crs(3857)
    anchor_xy = np.column_stack([anchors.geometry.x.values, anchors.geometry.y.values])
    cell_xy = np.column_stack(
        [grid_m.geometry.centroid.x.values, grid_m.geometry.centroid.y.values]
    )
    tree = cKDTree(anchor_xy)
    # average distance to 3 nearest anchors = smoother, less sensitive to a
    # single stray POI.
    k = min(3, len(anchor_xy))
    dists, _ = tree.query(cell_xy, k=k)
    if k == 1:
        d = dists
    else:
        d = dists.mean(axis=1)
    # Rational decay keeps far cells distinguishable (exp decay crushes them).
    # prox=1 at d=0, prox=0.5 at d=scale, prox=0.1 at d=9*scale.
    scale_m = 500.0
    prox = 1.0 / (1.0 + d / scale_m)
    return pd.Series(prox, index=grid.index, name="anchor_proximity")


def compute_landuse_fractions(
    grid: gpd.GeoDataFrame, landuse_layers: dict[str, gpd.GeoDataFrame]
) -> pd.DataFrame:
    out = pd.DataFrame(index=grid.index)
    for cat, gdf in landuse_layers.items():
        out[f"lu_frac_{cat}"] = G.cell_overlap_fraction(gdf, grid, f"lu_frac_{cat}")
    return out


# ----------------------------------------------------------------------------
# Spatial smoothing over H3 neighborhood
# ----------------------------------------------------------------------------
def smooth_over_rings(
    grid: gpd.GeoDataFrame,
    values: pd.DataFrame,
    rings: int = 2,
    decay: float = 0.55,
) -> pd.DataFrame:
    """Enrich each cell with a weighted sum of its H3 ring-neighbors.

    smoothed[c] = values[c] + decay * sum(ring1) + decay^2 * sum(ring2) + ...
    """
    if rings <= 0:
        return values.copy()
    h3_ids = grid["h3"].tolist()
    idx_by_h3 = {h: i for i, h in enumerate(h3_ids)}
    idx_array = grid.index.to_numpy()
    result = values.copy().astype(float)
    val_arr = values.to_numpy(dtype=float)
    smoothed = val_arr.copy()

    for ring in range(1, rings + 1):
        w = decay ** ring
        for i, h in enumerate(h3_ids):
            # grid_disk_distances returns lists per distance; simpler: grid_ring
            try:
                ring_ids = h3.grid_ring(h, ring)
            except Exception:
                continue
            acc = None
            for rh in ring_ids:
                j = idx_by_h3.get(rh)
                if j is None:
                    continue
                if acc is None:
                    acc = val_arr[j].copy()
                else:
                    acc += val_arr[j]
            if acc is not None:
                smoothed[i] += w * acc
    result.iloc[:, :] = smoothed
    result.columns = [f"{c}_s" for c in values.columns]
    return result


# ----------------------------------------------------------------------------
# Diversity (Shannon entropy over normalized POI categories)
# ----------------------------------------------------------------------------
def diversity_score(poi_counts_smoothed: pd.DataFrame, categories: list[str]) -> pd.Series:
    cols = [f"count_{c}_s" for c in categories if f"count_{c}_s" in poi_counts_smoothed.columns]
    if not cols:
        return pd.Series(0.0, index=poi_counts_smoothed.index, name="mixed_use")
    arr = poi_counts_smoothed[cols].to_numpy(dtype=float)
    totals = arr.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.divide(arr, totals, where=totals > 0, out=np.zeros_like(arr))
    # shannon entropy, normalized by log(n_cats)
    with np.errstate(divide="ignore", invalid="ignore"):
        logp = np.where(p > 0, np.log(p), 0.0)
    ent = -(p * logp).sum(axis=1)
    max_ent = np.log(len(cols)) if len(cols) > 1 else 1.0
    div = ent / max_ent if max_ent > 0 else ent
    # gate by having at least some POIs (avoid pure diversity on near-empty cells)
    gated = div * (1.0 - np.exp(-totals.ravel() / 3.0))
    return pd.Series(gated, index=poi_counts_smoothed.index, name="mixed_use")


# ----------------------------------------------------------------------------
# Isolation (few POIs around → penalty)
# ----------------------------------------------------------------------------
def isolation_penalty(
    poi_counts_smoothed: pd.DataFrame,
    categories: list[str],
    low_threshold: float = 3.0,
) -> pd.Series:
    """1.0 when total smoothed POIs is ~0, drops to 0 as activity rises."""
    cols = [f"count_{c}_s" for c in categories if f"count_{c}_s" in poi_counts_smoothed.columns]
    if not cols:
        return pd.Series(1.0, index=poi_counts_smoothed.index, name="isolation")
    totals = poi_counts_smoothed[cols].sum(axis=1)
    pen = np.exp(-totals / low_threshold)
    return pd.Series(pen, index=poi_counts_smoothed.index, name="isolation")
