"""Field-visit routing over super-clusters + isolated top cells.

We are not solving a real TSP (too few stops). A deterministic greedy
nearest-neighbor from a sensible start is enough for ~10-15 points and
produces a walkable order with very little zig-zag in practice."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

import numpy as np
import pandas as pd


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _nn_route(points: list[dict], start_idx: int = 0) -> list[dict]:
    """Greedy nearest-neighbor ordering, followed by a single 2-opt sweep."""
    if len(points) <= 2:
        return list(points)
    remaining = list(range(len(points)))
    order = [remaining.pop(start_idx)]
    while remaining:
        last = order[-1]
        lat0, lon0 = points[last]["lat"], points[last]["lon"]
        best_j = min(
            remaining,
            key=lambda j: _haversine_m(lat0, lon0, points[j]["lat"], points[j]["lon"]),
        )
        remaining.remove(best_j)
        order.append(best_j)

    # 2-opt: try reversing each sub-segment if it shortens total tour length
    def tour_len(idxs):
        s = 0.0
        for a, b in zip(idxs[:-1], idxs[1:]):
            s += _haversine_m(
                points[a]["lat"], points[a]["lon"],
                points[b]["lat"], points[b]["lon"],
            )
        return s

    improved = True
    best_len = tour_len(order)
    while improved:
        improved = False
        for i in range(1, len(order) - 1):
            for j in range(i + 1, len(order)):
                new_order = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                nl = tour_len(new_order)
                if nl + 1e-6 < best_len:
                    order = new_order
                    best_len = nl
                    improved = True
    return [points[i] for i in order]


def build_routes(
    super_clusters: pd.DataFrame,
    micro_clusters: pd.DataFrame,
    grid_scored: pd.DataFrame,
    *,
    max_stops_day1: int = 8,
    max_stops_day2: int = 8,
    reason_col: str = "priority_tier",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Produce day1/day2 field-visit routes.

    Strategy:
      - Day 1 = top super_clusters (already by priority), ordered NN.
      - Day 2 = remaining super_clusters + micro-clusters not contained
        in any super-cluster whose priority is média+.
    """
    stops: list[dict] = []

    # Map cluster_id -> super_cluster_id for cross-referencing
    micro_to_super: dict[int, int] = {}
    for _, sc in super_clusters.iterrows():
        for cid in sc["micro_cluster_ids"]:
            micro_to_super[int(cid)] = int(sc["super_cluster_id"])

    # 1) super clusters
    for _, sc in super_clusters.iterrows():
        reason = (
            f"{int(sc['n_micro_clusters'])} micro-cluster(s) unidos; "
            f"{int(sc['n_cells_total'])} cells; score médio "
            f"{sc['score_medio']:.0f}; {sc['principais_sinais']}."
        )
        validation = (
            "Caminhar o corredor inteiro; validar presença de comércio "
            "denso + fluxo; anotar hosts candidatos (padaria, farmácia, "
            "academia, mercado, salão)."
        )
        stops.append({
            "kind": "super_cluster",
            "lat": float(sc["centroid_lat"]),
            "lon": float(sc["centroid_lon"]),
            "bairro": sc["bairro_principal"],
            "cluster_id": "|".join(str(x) for x in sc["micro_cluster_ids"]),
            "super_cluster_id": int(sc["super_cluster_id"]),
            "prioridade": sc["prioridade_visita"],
            "score_medio": float(sc["score_medio"]),
            "n_cells": int(sc["n_cells_total"]),
            "raio_m": float(sc["raio_m"]),
            "inherited_share": float(sc["inherited_share_medio"]),
            "motivo_parada": reason,
            "tipo_validacao": validation,
        })

    # 2) isolated micro-clusters that didn't become super_clusters on their own
    #    (single-member super_clusters) -- we skip those because they ARE
    #    already represented in the super_clusters frame. Instead, fall back
    #    to micro-clusters whose priority is média/alta but weren't in top
    #    super clusters.
    used_micro_ids = set(micro_to_super.keys())
    leftover_micros = micro_clusters[
        ~micro_clusters["cluster_id"].isin(used_micro_ids)
    ]
    # (In the Macaé case this is usually empty, but keeping the logic clean.)
    for _, mc in leftover_micros.iterrows():
        reason = (
            f"Micro-cluster isolado em {mc['bairro']}, {int(mc['n_cells'])} cells, "
            f"score médio {mc['score_mean']:.0f}."
        )
        stops.append({
            "kind": "micro_cluster",
            "lat": float(mc["centroid_lat"]),
            "lon": float(mc["centroid_lon"]),
            "bairro": mc["bairro"],
            "cluster_id": str(int(mc["cluster_id"])),
            "super_cluster_id": "",
            "prioridade": "média",
            "score_medio": float(mc["score_mean"]),
            "n_cells": int(mc["n_cells"]),
            "raio_m": float(mc["radius_m"]),
            "inherited_share": 0.0,
            "motivo_parada": reason,
            "tipo_validacao": "Validar presença comercial real no pé-de-porta.",
        })

    if not stops:
        return pd.DataFrame(), pd.DataFrame()

    # priority-rank stops
    prio_rank = {"alta": 0, "média": 1, "baixa": 2, "": 3}
    stops.sort(
        key=lambda s: (prio_rank.get(s["prioridade"], 3), -s["score_medio"])
    )

    # Split priority:
    #   day 1 = all "alta" stops up to max_stops_day1
    #   day 2 = remainder (média/baixa + leftover alta)
    alta = [s for s in stops if s["prioridade"] == "alta"]
    rest = [s for s in stops if s["prioridade"] != "alta"]

    day1_raw = alta[:max_stops_day1]
    # leftover alta goes to day 2 first, then rest
    day2_raw = (alta[max_stops_day1:] + rest)[:max_stops_day2]

    # If day 1 is too short (few altas), pull top of 'rest' into day 1
    if len(day1_raw) < max_stops_day1 and rest:
        pad = max_stops_day1 - len(day1_raw)
        taken = rest[:pad]
        day1_raw += taken
        day2_raw = [s for s in day2_raw if s not in taken][:max_stops_day2]
        # refill day2 with any remaining rest not already used
        used = set(id(s) for s in day1_raw + day2_raw)
        leftover = [s for s in rest if id(s) not in used]
        if len(day2_raw) < max_stops_day2 and leftover:
            day2_raw += leftover[: max_stops_day2 - len(day2_raw)]

    # Start day 1 from the northernmost alta-priority stop (typical choice for
    # a morning walking route: north -> south) — or simply from the first one.
    start1 = 0
    if day1_raw:
        start1 = max(range(len(day1_raw)), key=lambda i: day1_raw[i]["lat"])
    start2 = 0
    if day2_raw:
        start2 = max(range(len(day2_raw)), key=lambda i: day2_raw[i]["lat"])

    day1 = _nn_route(day1_raw, start_idx=start1)
    day2 = _nn_route(day2_raw, start_idx=start2)

    def _to_df(route, day_label):
        rows = []
        for i, s in enumerate(route, start=1):
            rows.append({
                "dia": day_label,
                "ordem": i,
                "lat": round(s["lat"], 6),
                "lon": round(s["lon"], 6),
                "bairro": s["bairro"],
                "cluster_id": s["cluster_id"],
                "super_cluster_id": s["super_cluster_id"],
                "prioridade": s["prioridade"],
                "score_medio": round(s["score_medio"], 2),
                "n_cells": s["n_cells"],
                "raio_m": s["raio_m"],
                "inherited_share": round(s["inherited_share"], 3),
                "motivo_parada": s["motivo_parada"],
                "tipo_validacao": s["tipo_validacao"],
            })
        return pd.DataFrame(rows)

    return _to_df(day1, "day1"), _to_df(day2, "day2")


def route_to_kml(route: pd.DataFrame, path, title: str) -> None:
    if route.empty:
        return
    placemarks = []
    coords = []
    for _, r in route.iterrows():
        coords.append(f"{r['lon']:.6f},{r['lat']:.6f},0")
        placemarks.append(
            f"""    <Placemark>
      <name>#{int(r['ordem'])} — {r['bairro']} ({r['prioridade']})</name>
      <description><![CDATA[
        Cluster: {r['cluster_id']} | Super: {r['super_cluster_id']}<br/>
        Score médio: {r['score_medio']:.1f}<br/>
        {r['motivo_parada']}<br/><br/>
        <i>{r['tipo_validacao']}</i>
      ]]></description>
      <Point><coordinates>{r['lon']:.6f},{r['lat']:.6f},0</coordinates></Point>
    </Placemark>"""
        )
    line = f"""    <Placemark>
      <name>{title} — rota</name>
      <LineString><tessellate>1</tessellate>
        <coordinates>{' '.join(coords)}</coordinates>
      </LineString>
    </Placemark>"""
    body = line + "\n" + "\n".join(placemarks)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{title}</name>
{body}
  </Document>
</kml>"""
    from pathlib import Path as _P
    _P(path).write_text(kml, encoding="utf-8")
