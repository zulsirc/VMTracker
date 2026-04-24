"""Anti-halo metric: distinguish *own* activity from *neighborhood* inheritance.

The smoothing in features.py propagates POI signal across the H3 ring, which
is correct for prospection but produces "halo" cells that look strong only
because their neighbors are. This module re-runs the scoring pipeline with
ZERO smoothing rings on the same features, then aligns both passes onto a
shared 0..100 scale so the popup can show the breakdown.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import scoring as S


def _direct_assemble(
    poi_counts_unsmoothed: pd.DataFrame,
    road_df_unsmoothed: pd.DataFrame,
    landuse_df_unsmoothed: pd.DataFrame,
    grid_index: pd.Index,
    anchor_proximity: pd.Series,
) -> pd.DataFrame:
    """Same as scoring.assemble_feature_frame but with no smoothing applied.

    The `count_X_s` aliasing keeps POI_WEIGHT_MAP happy.
    """
    poi_aliased = poi_counts_unsmoothed.copy()
    poi_aliased.columns = [f"{c}_s" for c in poi_aliased.columns]
    # diversity computed on unsmoothed counts, gated by total
    cols = [c for c in poi_aliased.columns if c.startswith("count_")]
    arr = poi_aliased[cols].to_numpy(dtype=float)
    totals = arr.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.divide(arr, totals, where=totals > 0, out=np.zeros_like(arr))
        logp = np.where(p > 0, np.log(p), 0.0)
    ent = -(p * logp).sum(axis=1)
    max_ent = np.log(len(cols)) if len(cols) > 1 else 1.0
    div = ent / max_ent if max_ent > 0 else ent
    mixed = pd.Series(div * (1.0 - np.exp(-totals.ravel() / 3.0)),
                      index=grid_index, name="mixed_use")
    isolation = pd.Series(np.exp(-totals.ravel() / 3.0),
                          index=grid_index, name="isolation")
    return S.assemble_feature_frame(
        grid_index, poi_aliased, road_df_unsmoothed, landuse_df_unsmoothed,
        mixed, isolation, anchor_proximity=anchor_proximity,
    )


def compute_direct_and_inherited(
    *,
    grid: pd.DataFrame,
    poi_counts_unsmoothed: pd.DataFrame,
    road_df_unsmoothed: pd.DataFrame,
    landuse_df_unsmoothed: pd.DataFrame,
    features_smoothed: pd.DataFrame,
    anchor_proximity: pd.Series,
    weights: dict[str, Any],
    score_total: pd.Series,
    raw_total: pd.Series,
    raw_unsuitable_frac: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """Returns (direct_score 0..100, inherited_score, breakdown_direct).

    Both scores use the SAME (lo, hi) anchor and the SAME blend so they are
    visually comparable. inherited = total - direct.
    """
    feats_direct = _direct_assemble(
        poi_counts_unsmoothed, road_df_unsmoothed, landuse_df_unsmoothed,
        grid.index, anchor_proximity,
    )
    score_direct, breakdown_direct = S.compute_score(
        feats_direct, weights, raw_unsuitable_frac=raw_unsuitable_frac,
        anchor_for_blend=raw_total,
    )
    # inherited share — non-negative for clarity (smoothing rarely lowers score)
    inherited = (score_total - score_direct).clip(lower=0.0)
    return score_direct.rename("direct_score"), inherited.rename("inherited_score"), breakdown_direct
