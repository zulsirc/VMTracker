"""Coordinates the fetching of OSM layers needed for scoring."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from .overpass_client import OverpassClient
from .utils import ensure_dir, setup_logging, stable_hash

LOG = setup_logging()


def _roads_query(bbox: tuple[float, float, float, float], tag_queries: list[str], timeout: int) -> str:
    """Roads need 'out geom' to recover full LineStrings."""
    s, w, n, e = bbox
    filters = []
    for q in tag_queries:
        if "=" in q:
            k, v = q.split("=", 1)
            filters.append(f'["{k}"="{v}"]')
        else:
            filters.append(f'["{q}"]')
    parts: list[str] = [f"[out:json][timeout:{timeout}];", "("]
    for f in filters:
        parts.append(f"  way{f}({s},{w},{n},{e});")
    parts.append(");")
    parts.append("out geom tags;")
    return "\n".join(parts)


def _landuse_query(bbox: tuple[float, float, float, float], tag_queries: list[str], timeout: int) -> str:
    """Landuse polygons: also need 'out geom' to recover polygon rings."""
    s, w, n, e = bbox
    filters = []
    for q in tag_queries:
        if "=" in q:
            k, v = q.split("=", 1)
            filters.append(f'["{k}"="{v}"]')
        else:
            filters.append(f'["{q}"]')
    parts: list[str] = [f"[out:json][timeout:{timeout}];", "("]
    for f in filters:
        parts.append(f"  way{f}({s},{w},{n},{e});")
        parts.append(f"  relation{f}({s},{w},{n},{e});")
    parts.append(");")
    parts.append("out geom tags;")
    return "\n".join(parts)


class DataSources:
    """Thin orchestrator pulling POIs, landuse and roads from Overpass."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        ov = cfg["overpass"]
        self.cache_dir = ensure_dir(ov["cache_dir"])
        self.client = OverpassClient(
            endpoint=ov["endpoint"],
            cache_dir=self.cache_dir,
            timeout_s=ov.get("timeout_s", 180),
            retries=ov.get("retries", 3),
            retry_backoff_s=ov.get("retry_backoff_s", 5.0),
        )
        self.bbox = (
            cfg["study_area"]["bbox"]["min_lat"],
            cfg["study_area"]["bbox"]["min_lon"],
            cfg["study_area"]["bbox"]["max_lat"],
            cfg["study_area"]["bbox"]["max_lon"],
        )

    # -------- POIs --------
    def fetch_poi(self, category: str, tag_queries: list[str]) -> dict[str, Any]:
        key = f"poi_{category}_" + stable_hash({"bbox": self.bbox, "tags": tag_queries})
        return self.client.fetch(self.bbox, tag_queries, ("node", "way", "relation"), cache_key=key)

    # -------- Roads (with geometry) --------
    def fetch_roads(self, tag_queries: list[str]) -> dict[str, Any]:
        key = f"roads_" + stable_hash({"bbox": self.bbox, "tags": tag_queries})
        cache_file = self.cache_dir / f"overpass_{key}.json"
        if cache_file.exists():
            try:
                with cache_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except json.JSONDecodeError:
                LOG.warning("corrupted roads cache, refetching")
        query = _roads_query(self.bbox, tag_queries, self.client.timeout_s)
        data = self._raw_post(query)
        with cache_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return data

    # -------- Landuse (with geometry) --------
    def fetch_landuse(self, category: str, tag_queries: list[str]) -> dict[str, Any]:
        key = f"landuse_{category}_" + stable_hash({"bbox": self.bbox, "tags": tag_queries})
        cache_file = self.cache_dir / f"overpass_{key}.json"
        if cache_file.exists():
            try:
                with cache_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except json.JSONDecodeError:
                LOG.warning("corrupted landuse cache, refetching")
        query = _landuse_query(self.bbox, tag_queries, self.client.timeout_s)
        data = self._raw_post(query)
        with cache_file.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return data

    # -------- low-level HTTP with retries --------
    def _raw_post(self, query: str) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(1, self.client.retries + 1):
            try:
                LOG.info("overpass POST (raw) attempt %d", attempt)
                r = self.client.session.post(
                    self.client.endpoint,
                    data={"data": query},
                    timeout=self.client.timeout_s + 30,
                )
                r.raise_for_status()
                data = r.json()
                LOG.info("overpass raw OK: %d elements", len(data.get("elements", [])))
                return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                LOG.warning("overpass raw failed attempt %d: %s", attempt, exc)
                import time as _t
                _t.sleep(self.client.retry_backoff_s * attempt)
        LOG.error("overpass raw exhausted: %s", last_err)
        return {"elements": [], "_error": str(last_err) if last_err else "unknown"}
