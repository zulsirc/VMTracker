"""Audit the pipeline: ranks, breakdowns, false-positive checks."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np


CSV = Path("/home/user/VMTracker/output/macae_all_cells.csv")
OUT = Path("/home/user/VMTracker/output/audit")
OUT.mkdir(parents=True, exist_ok=True)

# Map output-file columns to the user-requested audit columns
REPORT_COLS = {
    "rank":                     "rank",
    "h3":                       "h3_id",
    "score":                    "score_final",
    "lat":                      "lat",
    "lon":                      "lon",
    "pos_commercial":           "score_commercial_density",
    "pos_mixed_use":            "score_mixed_use",
    "pos_anchor_proximity":     "score_anchor_proximity",
    "pos_residential":          "score_residential",
    "pos_road_density":         "score_connectivity",
    "pen_unsuitable_landuse":   "penalty_void_or_inviable",
    "pen_isolation":            "penalty_isolation",
    "feat_unsuitable_frac":     "landuse_inviavel_pct",
}


def _prepare(df: pd.DataFrame, rank_start: int = 1) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "rank", np.arange(rank_start, rank_start + len(df)))
    cols = [c for c in REPORT_COLS if c in df.columns]
    out = df[cols].rename(columns=REPORT_COLS)
    for c in ("score_final", "score_commercial_density", "score_mixed_use",
              "score_anchor_proximity", "score_residential", "score_connectivity",
              "penalty_void_or_inviable", "penalty_isolation",
              "landuse_inviavel_pct", "lat", "lon"):
        if c in out.columns:
            out[c] = out[c].astype(float).round(3)
    return out


def main() -> None:
    df = pd.read_csv(CSV)
    assert "score" in df.columns, "score column missing"
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    top20 = _prepare(df.head(20), rank_start=1)
    bottom20 = _prepare(df.tail(20).sort_values("score").reset_index(drop=True),
                        rank_start=len(df) - 19)

    mid_df = df[(df["score"] >= 40) & (df["score"] < 60)].copy()
    # take 10 spread across the middle, not the same corner
    mid_sample = mid_df.sort_values("score").iloc[::max(1, len(mid_df)//10)].head(10)
    mid_sample = mid_sample.reset_index(drop=True)
    mid_sample.insert(0, "_rank", mid_sample.index + 1)
    mid_out = _prepare(mid_sample, rank_start=1)

    top20.to_csv(OUT / "top20.csv", index=False)
    bottom20.to_csv(OUT / "bottom20.csv", index=False)
    mid_out.to_csv(OUT / "mid10.csv", index=False)

    print("\n=== TOP 20 ===")
    print(top20.to_string(index=False))
    print("\n=== BOTTOM 20 ===")
    print(bottom20.to_string(index=False))
    print("\n=== MID (10 cells, 40-60 score) ===")
    print(mid_out.to_string(index=False))

    # -------- overall stats ---------
    print("\n=== OVERALL ===")
    print(df["score"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.95]).round(2))
    print("\nby class:")
    print(df["class"].value_counts())

    # -------- red flags ---------
    flags = []
    # (a) very high score + RAW (cell-own, un-smoothed) unsuitable >0.3
    #     => green cell inside inviable landuse footprint.
    raw_u = df.get("raw_lu_frac_unsuitable")
    if raw_u is not None:
        mask = (df["score"] > 70) & (raw_u > 0.3)
        if mask.any():
            flags.append(
                f"{mask.sum()} cells score>70 with raw unsuitable_frac>0.3 "
                "(cell itself sits on inviable landuse)"
            )
    # (b) very high score but no anchor POIs nearby -> isolated top
    mask = (df["score"] > 80) & (df.get("feat_isolation", 0) > 0.4)
    if mask.any():
        flags.append(f"{mask.sum()} cells score>80 but isolation>0.4 (thin ecosystem)")
    # (c) dominated by a single POI type at top
    top30 = df.head(30)
    poi_cols = [c for c in top30.columns if c.startswith("count_")]
    for col in poi_cols:
        share = top30[col].sum() / (top30[poi_cols].sum().sum() + 1e-9)
        if share > 0.5:
            flags.append(f"{col} accounts for {share*100:.0f}% of POIs in top 30 — single-category dominance")
    # (d) bucket 80-100 > 60-80 -- rank blend distortion
    b8 = ((df["score"] >= 80) & (df["score"] <= 100)).sum()
    b6 = ((df["score"] >= 60) & (df["score"] < 80)).sum()
    if b8 > b6:
        flags.append(f"bucket 80-100 ({b8}) larger than 60-80 ({b6}) — possible rank-blend distortion")

    print("\n=== RED FLAGS ===")
    if flags:
        for f in flags:
            print(f" - {f}")
    else:
        print(" (none)")

    # -------- POI composition of top 10 ---------
    print("\n=== POI composition of TOP 10 cells (raw counts per cell) ===")
    poi_cols = [c for c in df.columns if c.startswith("count_")]
    comp = df.head(10)[["h3", "score", "lat", "lon"] + poi_cols].copy()
    comp.columns = [c.replace("count_", "") for c in comp.columns]
    print(comp.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
