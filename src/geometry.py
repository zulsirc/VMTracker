"""Study-area handling, H3 hex grid, and OSM geometry extraction."""
from __future__ import annotations

from typing import Any, Iterable

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

from .utils import setup_logging

LOG = setup_logging()

# ----------------------------------------------------------------------------
# Study area
# ----------------------------------------------------------------------------
def study_polygon(cfg: dict[str, Any]) -> Polygon:
    coords = cfg["study_area"]["polygon"]
    poly = Polygon([(lon, lat) for lon, lat in coords])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def study_bbox(cfg: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for Overpass."""
    b = cfg["study_area"]["bbox"]
    return (b["min_lat"], b["min_lon"], b["max_lat"], b["max_lon"])


# ----------------------------------------------------------------------------
# H3 grid
# ----------------------------------------------------------------------------
def build_h3_grid(polygon: Polygon, resolution: int) -> gpd.GeoDataFrame:
    """Fill a polygon with H3 cells and return a GeoDataFrame (EPSG:4326).

    Uses h3 v4 API: h3shape_to_cells + cells_to_h3shape.
    """
    coords = list(polygon.exterior.coords)
    # h3 v4 expects (lat, lng) tuples
    latlng = [(lat, lon) for lon, lat in coords]
    holes: list[list[tuple[float, float]]] = []
    for interior in polygon.interiors:
        holes.append([(lat, lon) for lon, lat in interior.coords])
    shape_obj = h3.LatLngPoly(latlng, *holes)
    cells = h3.h3shape_to_cells(shape_obj, resolution)

    polys: list[Polygon] = []
    for c in cells:
        boundary = h3.cell_to_boundary(c)  # list of (lat, lng)
        polys.append(Polygon([(lon, lat) for lat, lon in boundary]))

    gdf = gpd.GeoDataFrame(
        {"h3": list(cells), "geometry": polys},
        crs="EPSG:4326",
    )
    # precompute centroid lat/lon for later operations
    cent = gdf.geometry.representative_point()
    gdf["lat"] = cent.y
    gdf["lon"] = cent.x
    # area in km² via metric projection
    gdf["area_km2"] = gdf.to_crs(3857).geometry.area / 1_000_000.0
    LOG.info("h3 grid built: %d cells at resolution %d", len(gdf), resolution)
    return gdf


# ----------------------------------------------------------------------------
# OSM element → shapely
# ----------------------------------------------------------------------------
def _element_to_geom(el: dict[str, Any]) -> tuple[Any, str] | tuple[None, str]:
    et = el.get("type")
    if et == "node":
        lon, lat = el.get("lon"), el.get("lat")
        if lon is None or lat is None:
            return None, "missing"
        return Point(lon, lat), "point"
    if et in ("way", "relation"):
        center = el.get("center")
        if center and "lon" in center and "lat" in center:
            return Point(center["lon"], center["lat"]), "point"
    return None, "unsupported"


def overpass_to_gdf(data: dict[str, Any]) -> gpd.GeoDataFrame:
    rows = []
    for el in data.get("elements", []):
        geom, kind = _element_to_geom(el)
        if geom is None:
            continue
        tags = el.get("tags", {}) or {}
        rows.append(
            {
                "osm_type": el.get("type"),
                "osm_id": el.get("id"),
                "tags": tags,
                "geometry": geom,
                "kind": kind,
            }
        )
    if not rows:
        return gpd.GeoDataFrame(
            {"osm_type": [], "osm_id": [], "tags": [], "kind": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


# ----------------------------------------------------------------------------
# Road lines (Overpass LineStrings)
# ----------------------------------------------------------------------------
def overpass_roads_to_gdf(data: dict[str, Any]) -> gpd.GeoDataFrame:
    """Roads queries return ways with 'geometry' arrays (only when we use 'out geom')."""
    rows = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            # fallback: degrade to center point, useful only as proxy
            c = el.get("center")
            if c:
                rows.append(
                    {
                        "osm_id": el.get("id"),
                        "tags": el.get("tags", {}) or {},
                        "geometry": Point(c["lon"], c["lat"]),
                    }
                )
            continue
        line = LineString([(p["lon"], p["lat"]) for p in geom])
        rows.append(
            {
                "osm_id": el.get("id"),
                "tags": el.get("tags", {}) or {},
                "geometry": line,
            }
        )
    if not rows:
        return gpd.GeoDataFrame(
            {"osm_id": [], "tags": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


# ----------------------------------------------------------------------------
# Clip helpers
# ----------------------------------------------------------------------------
def clip_to_polygon(gdf: gpd.GeoDataFrame, polygon: Polygon) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    mask = gpd.GeoSeries([polygon], crs="EPSG:4326")
    # use spatial index for speed
    return gpd.sjoin(gdf, gpd.GeoDataFrame(geometry=mask, crs="EPSG:4326"), predicate="intersects", how="inner").drop(columns=["index_right"])


def point_in_cell_counts(
    points: gpd.GeoDataFrame, grid: gpd.GeoDataFrame, column_name: str
) -> pd.Series:
    """Count how many points fall in each grid cell; returns a Series aligned to grid.index."""
    if points.empty:
        return pd.Series(0, index=grid.index, name=column_name)
    joined = gpd.sjoin(points, grid[["geometry"]], predicate="within", how="left")
    counts = joined.groupby("index_right").size()
    out = pd.Series(0, index=grid.index, name=column_name, dtype="int64")
    out.loc[counts.index.astype(int)] = counts.astype("int64")
    return out


def road_length_per_cell(
    roads: gpd.GeoDataFrame, grid: gpd.GeoDataFrame
) -> pd.Series:
    """Sum road length (meters) intersecting each cell."""
    if roads.empty:
        return pd.Series(0.0, index=grid.index, name="road_length_m")
    # project to metric CRS
    roads_m = roads.to_crs(3857)
    grid_m = grid.to_crs(3857)[["geometry"]].copy()
    grid_m["cell_idx"] = grid_m.index
    overlay = gpd.overlay(
        gpd.GeoDataFrame(geometry=roads_m.geometry, crs=3857),
        grid_m,
        how="intersection",
        keep_geom_type=True,
    )
    if overlay.empty:
        return pd.Series(0.0, index=grid.index, name="road_length_m")
    overlay["length_m"] = overlay.geometry.length
    agg = overlay.groupby("cell_idx")["length_m"].sum()
    out = pd.Series(0.0, index=grid.index, name="road_length_m")
    out.loc[agg.index] = agg.values
    return out


# ----------------------------------------------------------------------------
# Landuse polygon union (for unsuitable-area penalty)
# ----------------------------------------------------------------------------
def mask_water_cells(
    grid: gpd.GeoDataFrame,
    water_gdf: gpd.GeoDataFrame,
    overlap_threshold: float = 0.4,
) -> gpd.GeoDataFrame:
    """Drop cells that are mostly over water.

    A cell is dropped if EITHER:
      - its centroid falls inside a water polygon, OR
      - more than `overlap_threshold` of its area is covered by water.
    """
    if water_gdf is None or water_gdf.empty or grid.empty:
        return grid
    water_m = water_gdf.to_crs(3857)
    try:
        water_union = unary_union(water_m.geometry.values)
    except Exception:
        return grid
    if water_union.is_empty:
        return grid

    grid_m = grid.to_crs(3857)
    cell_area = grid_m.geometry.area.replace(0, np.nan)
    overlap_area = grid_m.geometry.intersection(water_union).area
    overlap_frac = (overlap_area / cell_area).fillna(0.0)
    centroid_in_water = grid_m.geometry.representative_point().within(water_union)

    keep = (~centroid_in_water.values) & (overlap_frac.values < overlap_threshold)
    out = grid.loc[keep].copy().reset_index(drop=True)
    return out


def polygons_from_overpass(data: dict[str, Any]) -> gpd.GeoDataFrame:
    """Best-effort polygon extraction for Overpass ways/relations with 'geometry'."""
    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        geom = None
        if el.get("type") == "way" and el.get("geometry"):
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(coords) >= 3 and coords[0] == coords[-1]:
                try:
                    geom = Polygon(coords).buffer(0)
                except Exception:
                    geom = None
        # fallback: use center as a tiny buffer so it still contributes
        if geom is None:
            c = el.get("center") or (
                {"lat": el.get("lat"), "lon": el.get("lon")} if el.get("type") == "node" else None
            )
            if c and c.get("lat") is not None and c.get("lon") is not None:
                geom = Point(c["lon"], c["lat"]).buffer(0.0003)  # ~30m in lat
        if geom is None or geom.is_empty:
            continue
        rows.append({"osm_id": el.get("id"), "tags": tags, "geometry": geom})
    if not rows:
        return gpd.GeoDataFrame(
            {"osm_id": [], "tags": []},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def cell_overlap_fraction(
    polys: gpd.GeoDataFrame, grid: gpd.GeoDataFrame, column_name: str
) -> pd.Series:
    """For each cell, fraction of its area covered by the input polygons (0..1)."""
    if polys.empty:
        return pd.Series(0.0, index=grid.index, name=column_name)
    polys_m = polys.to_crs(3857)
    grid_m = grid.to_crs(3857)[["geometry"]].copy()
    grid_m["cell_idx"] = grid_m.index
    grid_m["cell_area"] = grid_m.geometry.area
    unioned = unary_union(polys_m.geometry.values)
    if unioned.is_empty:
        return pd.Series(0.0, index=grid.index, name=column_name)
    gdf_union = gpd.GeoDataFrame(geometry=[unioned], crs=3857)
    inter = gpd.overlay(grid_m, gdf_union, how="intersection", keep_geom_type=True)
    if inter.empty:
        return pd.Series(0.0, index=grid.index, name=column_name)
    inter["inter_area"] = inter.geometry.area
    agg = inter.groupby("cell_idx")["inter_area"].sum()
    out = pd.Series(0.0, index=grid.index, name=column_name)
    cell_areas = grid_m.set_index("cell_idx")["cell_area"]
    for idx, area in agg.items():
        ca = cell_areas.loc[idx]
        out.loc[idx] = min(1.0, float(area) / float(ca) if ca else 0.0)
    return out
