"""Scenario adjustment: convenience_urban vs beach_tourism.

We do NOT touch the base score. A scenario multiplier is applied *on top
of* score_final and actionability_score to produce `score_scenario` and
`actionability_scenario`, for apples-to-apples comparison.

Detection of "beachfront" cells uses two signals:
  1. Overlap with natural=beach landuse polygons (fetched on demand).
  2. Cells whose centroid is within N metres of any beach polygon.
"""
from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from . import geometry as G
from .utils import setup_logging

LOG = setup_logging()


BEACH_TAGS = ["natural=beach", "leisure=beach_resort"]


def fetch_beach_polygons(ds, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Use the existing Overpass DataSources client to fetch beaches."""
    data = ds.fetch_landuse("beach", BEACH_TAGS)
    return G.polygons_from_overpass(data)


def compute_beach_proximity(
    grid: gpd.GeoDataFrame,
    beach_gdf: gpd.GeoDataFrame,
    proximity_m: float = 180.0,
) -> pd.Series:
    """Return a 0..1 score: 1 for cells fully overlapping beach OR
    whose centroid is ≤ proximity_m from any beach polygon edge."""
    if beach_gdf is None or beach_gdf.empty:
        return pd.Series(0.0, index=grid.index, name="beach_proximity")

    # Work in metric CRS for buffers.
    beaches_m = beach_gdf.to_crs(3857)
    try:
        beach_union = unary_union(beaches_m.geometry.values).buffer(proximity_m)
    except Exception:
        return pd.Series(0.0, index=grid.index, name="beach_proximity")

    grid_m = grid.to_crs(3857)
    # fraction of each cell falling within the buffered beach union
    overlaps = grid_m.geometry.intersection(beach_union).area
    cell_area = grid_m.geometry.area.replace(0, np.nan)
    frac = (overlaps / cell_area).fillna(0.0).clip(0.0, 1.0)
    return pd.Series(frac.values, index=grid.index, name="beach_proximity")


SCENARIOS: dict[str, dict[str, float]] = {
    # Convenience urban: discount cells whose value depends on beach/orla.
    # score_scenario = score_final * (1 - k * beach_proximity)
    "convenience_urban": {"multiplier_k": 0.45, "description": (
        "Vending de conveniência urbana. Dá desconto em cells próximas à "
        "faixa de praia/orla porque a dinâmica de kiosk/tourism não "
        "traduz em fluxo de comércio de rua para a máquina."
    )},
    # Beach tourism: slight boost for beach-adjacent cells.
    "beach_tourism": {"multiplier_k": -0.15, "description": (
        "Vending de orla/turismo. Pequeno boost para cells com faixa de "
        "praia próxima (fluxo turístico, kiosques, bares, pousadas)."
    )},
}


def apply_scenario(
    grid_scored: pd.DataFrame,
    beach_proximity: pd.Series,
    scenario: str,
) -> pd.DataFrame:
    """Returns a copy of grid_scored with two added columns:
        score_scenario_<scenario>
        actionability_scenario_<scenario>
    Plus the shared column `beach_proximity` (0..1).
    """
    if scenario not in SCENARIOS:
        LOG.warning("unknown scenario '%s'; treating as convenience_urban", scenario)
        scenario = "convenience_urban"

    k = SCENARIOS[scenario]["multiplier_k"]
    out = grid_scored.copy()
    out["beach_proximity"] = beach_proximity.values

    mult = (1.0 - k * out["beach_proximity"]).clip(lower=0.0, upper=1.25)
    out[f"score_scenario_{scenario}"] = (out["score"] * mult).clip(0, 100).round(2)
    if "actionability_score" in out.columns:
        out[f"actionability_scenario_{scenario}"] = (
            out["actionability_score"] * mult
        ).clip(0, 100).round(2)
    return out


def compare_scenarios(
    grid_scored: pd.DataFrame,
    beach_proximity: pd.Series,
) -> pd.DataFrame:
    """Return one row per cell with score in both scenarios for audit."""
    rows = []
    for scenario in ("convenience_urban", "beach_tourism"):
        k = SCENARIOS[scenario]["multiplier_k"]
        mult = (1.0 - k * beach_proximity.values).clip(0.0, 1.25)
        rows.append(pd.DataFrame({
            "h3": grid_scored["h3"].values,
            "lat": grid_scored["lat"].values,
            "lon": grid_scored["lon"].values,
            "bairro": grid_scored.get("bairro", "?"),
            "score_final": grid_scored["score"].values,
            "beach_proximity": beach_proximity.values,
            "scenario": scenario,
            "score_scenario": np.clip(grid_scored["score"].values * mult, 0, 100).round(2),
            "actionability_base": grid_scored.get("actionability_score", grid_scored["score"]).values,
            "actionability_scenario": np.clip(
                grid_scored.get("actionability_score", grid_scored["score"]).values * mult, 0, 100
            ).round(2),
        }))
    long = pd.concat(rows, ignore_index=True)
    # also emit a wide table so user can diff easily
    wide = (
        long.pivot_table(
            index=["h3", "lat", "lon", "bairro", "score_final", "beach_proximity"],
            columns="scenario",
            values=["score_scenario", "actionability_scenario"],
            aggfunc="first",
        ).reset_index()
    )
    # flatten multi-index columns
    wide.columns = [
        "_".join([c for c in col if c]) if isinstance(col, tuple) else col
        for col in wide.columns.values
    ]
    wide["delta_score_urban_minus_beach"] = (
        wide["score_scenario_convenience_urban"] - wide["score_scenario_beach_tourism"]
    ).round(2)
    return wide.sort_values("delta_score_urban_minus_beach").reset_index(drop=True)
