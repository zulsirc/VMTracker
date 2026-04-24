"""`actionability_score`: operational adjustment on top of score_final.

Does NOT alter the heuristic base score. Applied as a post-processing
layer that discounts cells whose score is largely inherited from the
neighborhood or flagged as halo-dominated."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_actionability(
    grid_scored: pd.DataFrame,
    flags_series: pd.Series | None = None,
    inherited_threshold: float = 0.40,
    halo_flag_penalty: float = 20.0,
    inherited_majority_penalty: float = 12.0,
    inviable_penalty: float = 10.0,
) -> pd.Series:
    """Return 0..100 series aligned to grid_scored.index.

    Formula:
        base = score_final
        s_inh = max(0, inherited_share - inherited_threshold)
        actionability = base
                      - 50 * s_inh                        (linear beyond threshold)
                      - halo_flag_penalty       if halo_dominated flag
                      - inherited_majority_pen  if inherited_majority flag
                      - inviable_penalty        if inviable_landuse_present flag
        clipped to [0, 100]

    Meaning: two cells with score_final=82 may get actionability 78 (genuine
    direct activity) vs 49 (heavy halo) — used to decide where to step first.
    """
    score = grid_scored["score"].astype(float)
    inherited = grid_scored.get(
        "neighborhood_inherited_score",
        pd.Series(0.0, index=grid_scored.index),
    ).astype(float)

    # inherited share
    inh_share = inherited / score.clip(lower=1.0)
    inh_share = inh_share.clip(0.0, 1.0)

    excess = (inh_share - inherited_threshold).clip(lower=0.0)
    adj = score - 50.0 * excess

    # flag penalties
    if flags_series is not None:
        for i in grid_scored.index:
            f = str(flags_series.get(i, "") or "")
            if not f:
                continue
            if "halo_dominated" in f:
                adj.loc[i] = adj.loc[i] - halo_flag_penalty
            if "inherited_majority" in f:
                adj.loc[i] = adj.loc[i] - inherited_majority_penalty
            if "inviable_landuse_present" in f:
                adj.loc[i] = adj.loc[i] - inviable_penalty

    return adj.clip(0.0, 100.0).rename("actionability_score")


def priority_tier(
    grid_scored: pd.DataFrame,
    actionability: pd.Series,
    flags_series: pd.Series,
) -> pd.Series:
    """Classify each cell into one of three operational tiers.

    - visitar_agora:     direct_activity high + low penalty + no halo flag
    - validar_visualmente: score good but inherited_share relevant
    - suspeita_halo:     any halo/inviable flag or >= 55% inherited
    """
    tiers = []
    inh = grid_scored.get(
        "neighborhood_inherited_score",
        pd.Series(0.0, index=grid_scored.index),
    )
    direct = grid_scored.get(
        "direct_activity_score",
        grid_scored["score"],
    )
    score = grid_scored["score"]

    for i in grid_scored.index:
        f = str(flags_series.get(i, "") or "")
        sh = float(inh.get(i, 0) or 0) / max(float(score.get(i, 1) or 1), 1.0)
        da = float(direct.get(i, 0) or 0)
        sf = float(score.get(i, 0) or 0)
        act = float(actionability.get(i, 0) or 0)

        if "halo_dominated" in f or "inviable_landuse_present" in f or sh >= 0.55:
            tiers.append("suspeita_halo")
        elif sf >= 60 and da >= 55 and act >= 60:
            tiers.append("visitar_agora")
        elif sf >= 50:
            tiers.append("validar_visualmente")
        else:
            tiers.append("-")  # below operational threshold
    return pd.Series(tiers, index=grid_scored.index, name="priority_tier")
