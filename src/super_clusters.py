"""Super-clusters: merge micro-clusters that form a continuous commercial
corridor.

Rule of merging two micro-clusters m1 and m2 into the same super-cluster:
  (a) haversine distance between their centroids <= merge_distance_m, OR
  (b) any cell in m1 is H3-adjacent (ring 1) to any cell in m2.

Both rules are combined via union-find. Output: one row per super-cluster
with aggregated metrics."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import h3
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from .clusters import POS_COLS_PRIORITY


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * asin(sqrt(a))


def build_super_clusters(
    grid_scored: pd.DataFrame,
    cluster_meta: pd.DataFrame,
    merge_distance_m: float = 400.0,
    seed_h3_distance: int = 2,
) -> pd.DataFrame:
    """Build super-clusters from micro-cluster metadata.

    Merge rule (applied via union-find across micro-clusters):
      (a) centroid-haversine distance <= merge_distance_m, OR
      (b) H3 grid-distance between the two SEEDS <= seed_h3_distance.

    The second criterion captures "same corridor" while avoiding the
    transitive-collapse problem that full cell-adjacency has in dense
    commercial areas (where every cell touches something).
    """
    if cluster_meta.empty:
        return pd.DataFrame()

    m = cluster_meta.reset_index(drop=True).copy()
    n = len(m)
    seeds = m["h3_root"].tolist()

    if n == 1:
        groups: dict[int, list[int]] = {0: [0]}
    else:
        # Build a *effective* distance matrix that bends pairs down if they
        # also satisfy the seed-H3-ring criterion. Then agglomerative
        # clustering with complete linkage + threshold.
        H3_STEP_M = 200.0  # ≈ H3 res-9 edge length (projected)

        dmat = np.zeros((n, n), dtype=float)
        for i in range(n):
            for j in range(i + 1, n):
                d = _haversine_m(
                    m.iloc[i]["centroid_lat"], m.iloc[i]["centroid_lon"],
                    m.iloc[j]["centroid_lat"], m.iloc[j]["centroid_lon"],
                )
                try:
                    hd = h3.grid_distance(seeds[i], seeds[j])
                except Exception:
                    hd = 10**6
                if hd != 10**6:
                    d = min(d, hd * H3_STEP_M)
                dmat[i, j] = dmat[j, i] = d

        Z = linkage(squareform(dmat, checks=False), method="complete")
        labels = fcluster(Z, t=merge_distance_m, criterion="distance")
        groups = {}
        for idx, lab in enumerate(labels):
            groups.setdefault(int(lab), []).append(idx)

    # unused parameter kept for back-compat in signature
    _ = seed_h3_distance

    rows: list[dict] = []
    for root, member_idxs in groups.items():
        members = m.iloc[member_idxs]
        micro_ids = [int(x) for x in members["cluster_id"].tolist()]
        # pool all cells from member micro-clusters
        all_cell_idxs: list[int] = []
        for _, mem in members.iterrows():
            all_cell_idxs.extend(mem["cell_idx"])
        all_cell_idxs = sorted(set(all_cell_idxs))
        cells = grid_scored.iloc[all_cell_idxs]

        n_cells = len(cells)
        score_max = float(cells["score"].max())
        score_mean_w = float(
            (cells["score"] * cells.get("direct_activity_score", cells["score"]).clip(lower=1))
            .sum() / cells.get("direct_activity_score", cells["score"]).clip(lower=1).sum()
        )
        score_mean = float(cells["score"].mean())

        # inherited / direct shares averaged
        if "neighborhood_inherited_score" in cells.columns:
            inh_share = (
                cells["neighborhood_inherited_score"] /
                cells["score"].clip(lower=1)
            )
            inh_share_mean = float(inh_share.mean())
        else:
            inh_share_mean = 0.0
        direct_share_mean = 1.0 - inh_share_mean

        clat = float(cells["lat"].mean())
        clon = float(cells["lon"].mean())
        radius_m = float(
            max(_haversine_m(clat, clon, r.lat, r.lon) for r in cells.itertuples())
        ) if n_cells > 1 else 0.0

        # bairros involved (unique, ordered by weight)
        bairros = (
            cells["bairro"].value_counts()
            if "bairro" in cells.columns else pd.Series(dtype=int)
        )
        bairros_list = bairros.index.tolist()

        # consolidated signals (sum of positive contributions)
        sums: list[tuple[str, float]] = []
        for col, label in POS_COLS_PRIORITY:
            if col in cells.columns:
                sums.append((label, float(cells[col].sum())))
        sums.sort(key=lambda x: x[1], reverse=True)
        top_signals = [lab for lab, v in sums if v > 0.01][:4]
        signals_str = " + ".join(top_signals) if top_signals else "(sem sinal forte)"

        # priority heuristic (on super-cluster level)
        if score_mean >= 75 and n_cells >= 8 and inh_share_mean < 0.45:
            prio = "alta"
        elif score_mean >= 60 and inh_share_mean < 0.55:
            prio = "média"
        else:
            prio = "baixa"

        justification = (
            f"{len(members)} micro-cluster(s) unidos, {n_cells} células, "
            f"raio ~{radius_m:.0f}m, score médio {score_mean:.0f} "
            f"(máx {score_max:.0f}); direct share {direct_share_mean*100:.0f}%. "
            f"Sinais: {signals_str}."
        )

        rows.append({
            "micro_cluster_ids": micro_ids,
            "cell_idx": all_cell_idxs,
            "bairros": bairros_list,
            "bairro_principal": bairros_list[0] if bairros_list else "?",
            "n_micro_clusters": len(members),
            "n_cells_total": n_cells,
            "score_medio": round(score_mean, 2),
            "score_medio_ponderado": round(score_mean_w, 2),
            "score_max": round(score_max, 2),
            "inherited_share_medio": round(inh_share_mean, 3),
            "direct_share_medio": round(direct_share_mean, 3),
            "centroid_lat": round(clat, 6),
            "centroid_lon": round(clon, 6),
            "raio_m": round(radius_m, 0),
            "principais_sinais": signals_str,
            "justificativa": justification,
            "prioridade_visita": prio,
        })

    meta = pd.DataFrame(rows).sort_values(
        ["score_medio_ponderado", "n_cells_total"], ascending=[False, False]
    ).reset_index(drop=True)
    meta.insert(0, "super_cluster_id", np.arange(1, len(meta) + 1))
    meta.insert(0, "super_cluster_rank", np.arange(1, len(meta) + 1))
    return meta
