"""Group high-score H3 cells into adjacency clusters and characterize them.

A "cluster" is a connected component of H3-adjacent cells whose score
crosses a threshold. This is the operational unit for prospection: a
single vending-machine route can cover a 200-400m radius, so contiguous
high-score cells should be visited as a group.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Iterable

import h3
import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
# Static bairro centroids for Macaé south zone
# ----------------------------------------------------------------------------
# Approximate; used to label cells/clusters textually. Falls back to
# nearest-centroid when no Nominatim is available. Add new bairros here when
# parameterizing for other cities or refining Macaé.
MACAE_BAIRROS: dict[str, tuple[float, float]] = {
    "Centro":                 (-22.373, -41.785),
    "Imbetiba":               (-22.385, -41.780),
    "Aroeira":                (-22.388, -41.787),
    "Visconde de Araújo":     (-22.388, -41.797),
    "Granja dos Cavaleiros":  (-22.397, -41.797),
    "Glória":                 (-22.402, -41.793),
    "Cavaleiros":             (-22.413, -41.790),
    "Praia Campista":         (-22.420, -41.785),
    "Bosque Azul":            (-22.408, -41.808),
    "Nova Holanda":           (-22.398, -41.808),
    "Virgem Santa":           (-22.420, -41.815),
    "Costa do Sol":           (-22.435, -41.793),
    "Riviera Fluminense":     (-22.445, -41.797),
    "Lagomar":                (-22.450, -41.795),
    "Morro de São Jorge":     (-22.395, -41.802),
    "Botafogo":               (-22.385, -41.802),
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * asin(sqrt(a))


def nearest_bairro(lat: float, lon: float, table: dict[str, tuple[float, float]] | None = None) -> str:
    table = table or MACAE_BAIRROS
    best, dmin = None, float("inf")
    for name, (blat, blon) in table.items():
        d = _haversine_m(lat, lon, blat, blon)
        if d < dmin:
            dmin = d
            best = name
    return best or "?"


# ----------------------------------------------------------------------------
# Union-find clustering on H3 adjacency
# ----------------------------------------------------------------------------
@dataclass
class Cluster:
    cluster_id: int
    h3_root: str
    cell_idx: list[int] = field(default_factory=list)
    rank: int = 0


def build_clusters(
    grid_scored: pd.DataFrame,
    score_threshold: float,
    min_cells: int = 2,
    peak_radius_rings: int = 3,
    target_clusters: int = 10,
) -> tuple[pd.Series, pd.DataFrame]:
    """Build clusters via *local peak seeding*.

    Naive H3-adjacency clustering collapses the entire commercial core of a
    city like Macaé into one giant blob. For operational prospection we want
    multiple distinguishable pockets. So we:
      1. select cells with score >= threshold;
      2. iterate cells in score-descending order;
      3. each cell becomes the *seed* of a new cluster IF it is not already
         within `peak_radius_rings` rings of a previously-chosen seed;
      4. assign every other qualifying cell to its NEAREST seed (in H3
         grid-distance, ties broken by raw distance);
      5. drop clusters smaller than `min_cells`.
    """
    sub = grid_scored[grid_scored["score"] >= score_threshold].copy()
    if sub.empty:
        return pd.Series(-1, index=grid_scored.index, name="cluster_id"), pd.DataFrame()

    sub = sub.sort_values("score", ascending=False)
    h3_to_idx_global = {h: i for i, h in enumerate(grid_scored["h3"])}

    seeds: list[str] = []
    seed_idx_global: list[int] = []
    for h, _idx in zip(sub["h3"].tolist(), sub.index):
        too_close = False
        for s in seeds:
            try:
                d = h3.grid_distance(h, s)
            except Exception:
                d = peak_radius_rings + 99  # disconnected → far
            if d <= peak_radius_rings:
                too_close = True
                break
        if not too_close:
            seeds.append(h)
            seed_idx_global.append(h3_to_idx_global[h])
            if len(seeds) >= max(target_clusters, 1) * 3:
                # stop when we have plenty; final selection happens by ranking
                break

    if not seeds:
        return pd.Series(-1, index=grid_scored.index, name="cluster_id"), pd.DataFrame()

    # Assign each qualifying cell to nearest seed (by H3 grid distance).
    assignments: dict[str, list[int]] = {s: [] for s in seeds}
    for h in sub["h3"].tolist():
        best_seed = None
        best_d = float("inf")
        for s in seeds:
            try:
                d = h3.grid_distance(h, s)
            except Exception:
                continue
            if d < best_d:
                best_d = d
                best_seed = s
        # only assign if reasonably close to the seed
        if best_seed is not None and best_d <= peak_radius_rings + 2:
            assignments[best_seed].append(h3_to_idx_global[h])

    rows: list[dict] = []
    for seed, idxs in assignments.items():
        if len(idxs) < min_cells:
            continue
        cells = grid_scored.iloc[idxs]
        score_max = float(cells["score"].max())
        score_mean = float(cells["score"].mean())
        n = len(cells)
        # weight ranking by quality and breadth
        ranking_key = score_mean * (n ** 0.4) + 0.3 * score_max
        clat = float(cells["lat"].mean())
        clon = float(cells["lon"].mean())
        radius_m = float(
            max(_haversine_m(clat, clon, r.lat, r.lon) for r in cells.itertuples())
        ) if n > 1 else 0.0
        rows.append(
            {
                "h3_root": seed,
                "cell_idx": idxs,
                "n_cells": n,
                "score_mean": score_mean,
                "score_max": score_max,
                "ranking_key": ranking_key,
                "centroid_lat": clat,
                "centroid_lon": clon,
                "radius_m": radius_m,
            }
        )
    if not rows:
        return pd.Series(-1, index=grid_scored.index, name="cluster_id"), pd.DataFrame()

    meta = pd.DataFrame(rows).sort_values("ranking_key", ascending=False).reset_index(drop=True)
    meta["cluster_id"] = np.arange(1, len(meta) + 1)
    meta["bairro"] = [
        nearest_bairro(lat, lon)
        for lat, lon in zip(meta["centroid_lat"], meta["centroid_lon"])
    ]

    cluster_id_series = pd.Series(-1, index=grid_scored.index, name="cluster_id", dtype="int64")
    for _, row in meta.iterrows():
        for idx in row["cell_idx"]:
            cluster_id_series.iloc[idx] = int(row["cluster_id"])
    return cluster_id_series, meta


# ----------------------------------------------------------------------------
# Per-cluster signal characterization
# ----------------------------------------------------------------------------
POS_COLS_PRIORITY = [
    ("pos_food",            "alimentação"),
    ("pos_shop",            "comércio"),
    ("pos_supermarket",     "mercado/conveniência"),
    ("pos_pharmacy",        "farmácia"),
    ("pos_education",       "educação"),
    ("pos_fitness",         "academia"),
    ("pos_healthcare",      "saúde"),
    ("pos_office",          "escritórios"),
    ("pos_transport",       "transporte"),
    ("pos_bank",            "bancos/ATMs"),
    ("pos_leisure",         "lazer/turismo"),
    ("pos_residential",     "densidade residencial"),
    ("pos_commercial",      "uso comercial"),
    ("pos_mixed_use",       "diversidade de usos"),
    ("pos_road_density",    "conectividade viária"),
    ("pos_anchor_proximity","proximidade a âncoras"),
]


def cluster_top_signals(grid_scored: pd.DataFrame, idxs: Iterable[int], top_k: int = 3) -> str:
    cells = grid_scored.iloc[list(idxs)]
    sums: list[tuple[str, float]] = []
    for col, label in POS_COLS_PRIORITY:
        if col in cells.columns:
            sums.append((label, float(cells[col].sum())))
    sums.sort(key=lambda x: x[1], reverse=True)
    top = [label for label, v in sums if v > 0.01][:top_k]
    return " + ".join(top) if top else "(sem sinal forte)"


def shortlist(
    grid_scored: pd.DataFrame,
    cluster_meta: pd.DataFrame,
    top_n: int = 10,
) -> pd.DataFrame:
    """Build the field-visit shortlist out of the top clusters."""
    out_rows: list[dict] = []
    for i, row in cluster_meta.head(top_n).iterrows():
        cid = int(row["cluster_id"])
        idxs = row["cell_idx"]
        signals = cluster_top_signals(grid_scored, idxs)
        # priority heuristic
        if row["score_mean"] >= 75 and row["n_cells"] >= 4:
            prio = "alta"
        elif row["score_mean"] >= 60:
            prio = "média"
        else:
            prio = "baixa"
        # justification + expected observation
        justification = (
            f"{int(row['n_cells'])} células contíguas, score médio {row['score_mean']:.0f} "
            f"(máx {row['score_max']:.0f}); sinais: {signals}."
        )
        expectation = (
            "Espera-se ver fluxo contínuo de pedestres, presença de "
            "comércio/serviços ativo nas calçadas e mistura de usos. "
            "Procurar hosts: padaria, farmácia, mercado, academia, "
            "lan-house, salão, lavanderia, lojas de conveniência."
        )
        out_rows.append(
            {
                "cluster_rank": int(i) + 1,
                "cluster_id": cid,
                "lat": round(float(row["centroid_lat"]), 6),
                "lon": round(float(row["centroid_lon"]), 6),
                "bairro_aproximado": row["bairro"],
                "score_cluster": round(float(row["score_mean"]), 2),
                "score_max_cell": round(float(row["score_max"]), 2),
                "n_cells": int(row["n_cells"]),
                "raio_m": round(float(row["radius_m"]), 0),
                "principais_sinais": signals,
                "justificativa": justification,
                "observacao_esperada_em_campo": expectation,
                "prioridade_visita": prio,
            }
        )
    return pd.DataFrame(out_rows)
