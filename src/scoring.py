"""Normalization + weighted-sum score with transparent breakdown."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Normalization
# ----------------------------------------------------------------------------
def robust_minmax(series: pd.Series, p_low: float = 0.0, p_high: float = 0.95) -> pd.Series:
    """Robust min-max scaling to [0,1], winsorized at given percentiles.

    Using p_high=0.95 avoids a single outlier (e.g. one giant mall) from
    crushing every other cell into zero.
    """
    if series.empty:
        return series
    vals = series.to_numpy(dtype=float)
    lo = np.nanpercentile(vals, p_low * 100.0) if p_low > 0 else np.nanmin(vals)
    hi = np.nanpercentile(vals, p_high * 100.0) if p_high < 1 else np.nanmax(vals)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
        return pd.Series(np.zeros_like(vals), index=series.index, name=series.name)
    clipped = np.clip(vals, lo, hi)
    out = (clipped - lo) / (hi - lo)
    return pd.Series(out, index=series.index, name=series.name)


# ----------------------------------------------------------------------------
# Feature assembly
# ----------------------------------------------------------------------------
# Map weight-key -> underlying column in the smoothed POI counts frame.
POI_WEIGHT_MAP: dict[str, str] = {
    "food": "count_food_s",
    "shop": "count_shop_s",
    "supermarket": "count_supermarket_s",
    "pharmacy": "count_pharmacy_s",
    "fitness": "count_fitness_s",
    "education": "count_education_s",
    "healthcare": "count_healthcare_s",
    "office": "count_office_s",
    "bank": "count_bank_s",
    "transport": "count_transport_s",
    "leisure": "count_leisure_s",
    "fuel": "count_fuel_s",
}


def assemble_feature_frame(
    grid_index: pd.Index,
    poi_counts_smoothed: pd.DataFrame,
    road_df: pd.DataFrame,
    landuse_df: pd.DataFrame,
    mixed_use: pd.Series,
    isolation: pd.Series,
    anchor_proximity: pd.Series | None = None,
) -> pd.DataFrame:
    feats = pd.DataFrame(index=grid_index)

    for key, col in POI_WEIGHT_MAP.items():
        feats[key] = poi_counts_smoothed[col] if col in poi_counts_smoothed.columns else 0.0

    feats["residential"] = landuse_df.get("lu_frac_residential", pd.Series(0.0, index=grid_index))
    feats["commercial"] = landuse_df.get("lu_frac_commercial", pd.Series(0.0, index=grid_index))
    feats["industrial_frac"] = landuse_df.get("lu_frac_industrial", pd.Series(0.0, index=grid_index))
    feats["unsuitable_frac"] = landuse_df.get("lu_frac_unsuitable", pd.Series(0.0, index=grid_index))

    feats["road_density"] = road_df.get("road_density_m_per_km2", pd.Series(0.0, index=grid_index))
    feats["mixed_use"] = mixed_use
    feats["isolation"] = isolation

    if anchor_proximity is None:
        feats["anchor_proximity"] = 0.0
    else:
        feats["anchor_proximity"] = anchor_proximity.values

    # low connectivity: 1 - normalized road density (roughly)
    rd_norm = robust_minmax(feats["road_density"], 0.0, 0.95)
    feats["low_connectivity"] = (1.0 - rd_norm).clip(0.0, 1.0)

    return feats


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
def compute_score(
    features: pd.DataFrame,
    weights: dict[str, Any],
    raw_unsuitable_frac: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Return (score_0_100, breakdown_frame).

    Score pipeline:
      1) each positive feature -> robust_minmax -> multiply by weight
      2) sum of weighted positives
      3) subtract weighted penalties
      4) shift/scale to 0..100
    """
    pos_w = weights["positive"]
    pen_w = weights["penalties"]

    breakdown = pd.DataFrame(index=features.index)

    # --- positives ------------------------------------------------------
    pos_total = pd.Series(0.0, index=features.index)
    for key, w in pos_w.items():
        if key not in features.columns:
            continue
        norm = robust_minmax(features[key], 0.0, 0.95)
        contrib = norm * float(w)
        breakdown[f"pos_{key}"] = contrib
        pos_total = pos_total.add(contrib, fill_value=0.0)
    breakdown["positive_total"] = pos_total

    # --- penalties ------------------------------------------------------
    pen_total = pd.Series(0.0, index=features.index)

    if "unsuitable_landuse" in pen_w and "unsuitable_frac" in features.columns:
        u = features["unsuitable_frac"].clip(0, 1)  # already 0..1
        contrib = u * float(pen_w["unsuitable_landuse"])
        breakdown["pen_unsuitable_landuse"] = contrib
        pen_total = pen_total.add(contrib, fill_value=0.0)

    if "industrial" in pen_w and "industrial_frac" in features.columns:
        u = features["industrial_frac"].clip(0, 1)
        contrib = u * float(pen_w["industrial"])
        breakdown["pen_industrial"] = contrib
        pen_total = pen_total.add(contrib, fill_value=0.0)

    if "isolation" in pen_w and "isolation" in features.columns:
        u = features["isolation"].clip(0, 1)  # already 0..1
        contrib = u * float(pen_w["isolation"])
        breakdown["pen_isolation"] = contrib
        pen_total = pen_total.add(contrib, fill_value=0.0)

    if "low_connectivity" in pen_w and "low_connectivity" in features.columns:
        u = features["low_connectivity"].clip(0, 1)
        contrib = u * float(pen_w["low_connectivity"])
        breakdown["pen_low_connectivity"] = contrib
        pen_total = pen_total.add(contrib, fill_value=0.0)

    breakdown["penalty_total"] = pen_total

    # --- combine + rescale ---------------------------------------------
    raw = pos_total - pen_total

    # Blend two normalizations so the final score is both:
    #   1) ordinally correct     (preserves rank)
    #   2) visually distributed  (no giant mass at a single bucket)
    # Physical dominates (70%) — rank only adds spread in the low band so
    # the map reads with nuance instead of collapsing empty cells into one
    # bucket. Previous 60%-rank blend was inflating empty cells to "médio".
    lo = float(raw.min())
    hi = float(np.nanpercentile(raw, 97))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-9:
        lo, hi = float(raw.min()), float(raw.max()) + 1e-9
    physical = ((raw.clip(lo, hi) - lo) / (hi - lo)).clip(0.0, 1.0)
    physical = np.sqrt(physical)

    rank_pct = raw.rank(pct=True, method="average").astype(float)

    mixed = 0.70 * physical + 0.30 * rank_pct
    scaled = (mixed * 100.0).clip(0.0, 100.0)

    # Empty-cell guard: cells that have *no* real urban substance (no
    # commercial, no residential, no road density, no mixed-use) cannot
    # be "médio" just because they rank in the middle of an empty tail.
    # Cap them at 30 so they read as "ruim" regardless of rank.
    core_cols = ["commercial", "residential", "road_density", "mixed_use"]
    core = features[[c for c in core_cols if c in features.columns]].sum(axis=1)
    empty_mask = core < 1e-6
    scaled[empty_mask] = np.minimum(scaled[empty_mask], 30.0)

    # Hard safeguard: cells dominated by unsuitable landuse (water, wood,
    # airport, military, wetland, farmland) must never read "green" no
    # matter what accidental POI exists. We use the RAW (un-smoothed)
    # cell-own fraction so neighbors' unsuitable landuse doesn't produce
    # false-negatives for legitimate urban cells adjacent to parks.
    if raw_unsuitable_frac is not None:
        hard_mask = raw_unsuitable_frac > 0.5
        scaled[hard_mask] = np.minimum(scaled[hard_mask], 15.0)

    scaled = scaled.clip(0.0, 100.0)
    breakdown["score"] = scaled
    breakdown["raw"] = raw
    breakdown["score_physical"] = (physical * 100.0).round(2)
    breakdown["score_rank_pct"] = (rank_pct * 100.0).round(2)

    return scaled.rename("score"), breakdown


def classify(score: pd.Series) -> pd.Series:
    labels = pd.cut(
        score,
        bins=[-0.01, 20, 40, 60, 80, 100.01],
        labels=["muito ruim", "ruim", "médio", "bom", "muito bom"],
    )
    return labels.astype(str).rename("class")
