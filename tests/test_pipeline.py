"""Unit tests: config, grid, scoring, rendering — all offline."""
from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src import features as FEAT
from src import geometry as G
from src import scoring as S
from src.utils import load_config
from src.visualization import build_map


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config(REPO / "configs" / "macae.yaml")


# ----------------------------------------------------------------------------
# Config loading
# ----------------------------------------------------------------------------
def test_config_loads_and_has_required_keys(cfg):
    for k in ("city", "study_area", "grid", "poi_categories", "weights", "output", "map"):
        assert k in cfg, f"missing top-level config key: {k}"
    assert cfg["grid"]["h3_resolution"] >= 7


def test_study_polygon_is_valid(cfg):
    poly = G.study_polygon(cfg)
    assert poly.is_valid
    assert poly.area > 0


# ----------------------------------------------------------------------------
# Grid
# ----------------------------------------------------------------------------
def test_h3_grid_small_polygon_has_cells():
    # small polygon around Cavaleiros, Macaé
    poly = Polygon(
        [(-41.810, -22.420), (-41.790, -22.420), (-41.790, -22.405), (-41.810, -22.405)]
    )
    grid = G.build_h3_grid(poly, resolution=9)
    assert len(grid) > 5
    assert "h3" in grid.columns
    assert grid.geometry.is_valid.all()
    assert grid["area_km2"].mean() > 0


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def _toy_frame(n: int = 20) -> pd.DataFrame:
    idx = pd.RangeIndex(n)
    df = pd.DataFrame(index=idx)
    rng = list(range(n))
    df["food"] = rng
    df["shop"] = [x * 0.5 for x in rng]
    df["supermarket"] = [1 if x % 5 == 0 else 0 for x in rng]
    df["pharmacy"] = [1 if x % 3 == 0 else 0 for x in rng]
    df["fitness"] = 0
    df["education"] = [x % 4 for x in rng]
    df["healthcare"] = 0
    df["office"] = 0
    df["bank"] = 0
    df["transport"] = [x % 2 for x in rng]
    df["leisure"] = 0
    df["fuel"] = 0
    df["residential"] = [x / n for x in rng]
    df["commercial"] = [x / (2 * n) for x in rng]
    df["industrial_frac"] = 0.0
    df["unsuitable_frac"] = [0.9 if x == 0 else 0.0 for x in rng]
    df["road_density"] = [x * 100 for x in rng]
    df["mixed_use"] = [min(1.0, x / n) for x in rng]
    df["isolation"] = [1.0 if x == 1 else 0.0 for x in rng]
    df["low_connectivity"] = [1.0 - x / (n - 1) for x in rng]
    return df


def test_robust_minmax_bounds():
    s = pd.Series([0, 1, 2, 3, 100])
    out = S.robust_minmax(s, 0.0, 0.95)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_score_is_in_0_100_and_monotonic(cfg):
    feats = _toy_frame()
    score, breakdown = S.compute_score(feats, cfg["weights"])
    assert score.min() >= 0.0
    assert score.max() <= 100.0
    # the cell with heavy unsuitable landuse should be capped low
    assert score.iloc[0] <= 12.0
    # roughly, higher food/shop/... should trend to higher scores
    mid = score.iloc[len(feats) // 2]
    assert score.iloc[-1] > mid


def test_classify_labels(cfg):
    feats = _toy_frame()
    score, _ = S.compute_score(feats, cfg["weights"])
    cls = S.classify(score)
    assert set(cls.unique()).issubset({"muito ruim", "ruim", "médio", "bom", "muito bom"})


# ----------------------------------------------------------------------------
# Rendering (smoke test, no network)
# ----------------------------------------------------------------------------
def test_build_map_smoke(cfg, tmp_path):
    poly = Polygon(
        [(-41.810, -22.420), (-41.790, -22.420), (-41.790, -22.405), (-41.810, -22.405)]
    )
    grid = G.build_h3_grid(poly, resolution=9)
    n = len(grid)
    grid["score"] = [20 + i for i in range(n)]
    grid["class"] = "médio"
    grid["bairro"] = "Cavaleiros"
    grid["cluster_id"] = -1
    grid["direct_activity_score"] = grid["score"] * 0.7
    grid["neighborhood_inherited_score"] = grid["score"] * 0.3
    grid["penalty_total"] = 0.0
    grid["actionability_score"] = grid["score"] * 0.9
    grid["priority_tier"] = "validar_visualmente"
    grid["flag_visual_review"] = ""
    for col in [
        "pos_food","pos_shop","pos_supermarket","pos_pharmacy","pos_education",
        "pos_fitness","pos_healthcare","pos_office","pos_transport","pos_bank",
        "pos_leisure","pos_residential","pos_commercial","pos_mixed_use",
        "pos_road_density","pos_anchor_proximity",
        "pen_unsuitable_landuse","pen_industrial","pen_isolation","pen_low_connectivity",
    ]:
        grid[col] = 0.0
    m = build_map(grid, cfg, top_cells=None, study_polygon_wkt=poly.wkt)
    out = tmp_path / "smoke.html"
    m.save(str(out))
    assert out.exists() and out.stat().st_size > 1000
