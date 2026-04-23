"""Overpass API client with on-disk cache and graceful degradation.

We only query for *elements* (node/way/relation) that match simple key/value
filters. Results are returned in raw Overpass JSON form; geometry handling is
done in ``geometry.py``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

import requests

from .utils import ensure_dir, setup_logging, stable_hash

LOG = setup_logging()


class OverpassError(RuntimeError):
    pass


USER_AGENT = (
    "vending-heatmap/0.1 (+https://github.com/zulsirc/vmtracker; "
    "contact: ops@example.com)"
)


class OverpassClient:
    def __init__(
        self,
        endpoint: str,
        cache_dir: str | Path,
        timeout_s: int = 180,
        retries: int = 3,
        retry_backoff_s: float = 5.0,
    ) -> None:
        self.endpoint = endpoint
        self.cache_dir = ensure_dir(cache_dir)
        self.timeout_s = timeout_s
        self.retries = retries
        self.retry_backoff_s = retry_backoff_s
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en,pt-BR;q=0.8",
            }
        )

    # ---------------------------------------------------------------- cache
    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"overpass_{key}.json"

    # ----------------------------------------------------------- query build
    @staticmethod
    def _tag_filters(tag_queries: Iterable[str]) -> list[str]:
        """Translate human 'k=v' / 'k' expressions to Overpass QL filters."""
        filters = []
        for raw in tag_queries:
            q = raw.strip()
            if "=" in q:
                k, v = q.split("=", 1)
                filters.append(f'["{k}"="{v}"]')
            else:
                filters.append(f'["{q}"]')
        return filters

    def build_query(
        self,
        bbox: tuple[float, float, float, float],
        tag_queries: Iterable[str],
        element_types: tuple[str, ...] = ("node", "way", "relation"),
        timeout: int | None = None,
    ) -> str:
        """Build an Overpass QL query fetching elements with any of the tags.

        bbox is (south, west, north, east) in lat/lon.
        """
        s, w, n, e = bbox
        filters = self._tag_filters(tag_queries)
        if not filters:
            raise ValueError("tag_queries must not be empty")
        timeout = timeout or self.timeout_s
        parts: list[str] = [f"[out:json][timeout:{timeout}];", "("]
        for et in element_types:
            for f in filters:
                parts.append(f"  {et}{f}({s},{w},{n},{e});")
        parts.append(");")
        parts.append("out center tags;")
        return "\n".join(parts)

    # --------------------------------------------------------------- query
    def fetch(
        self,
        bbox: tuple[float, float, float, float],
        tag_queries: Iterable[str],
        element_types: tuple[str, ...] = ("node", "way", "relation"),
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        tag_queries = list(tag_queries)
        key = cache_key or stable_hash({"bbox": bbox, "tags": tag_queries, "et": element_types})
        cache_file = self._cache_path(key)
        if cache_file.exists():
            try:
                with cache_file.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                LOG.info("cache hit: %s (%d elements)", cache_file.name, len(data.get("elements", [])))
                return data
            except json.JSONDecodeError:
                LOG.warning("cache corrupted, refetching: %s", cache_file)

        query = self.build_query(bbox, tag_queries, element_types)
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                LOG.info("overpass POST attempt %d/%d for tags=%s", attempt, self.retries, tag_queries)
                r = self.session.post(self.endpoint, data={"data": query}, timeout=self.timeout_s + 30)
                if r.status_code == 429 or r.status_code == 504:
                    raise OverpassError(f"transient HTTP {r.status_code}")
                r.raise_for_status()
                data = r.json()
                with cache_file.open("w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                LOG.info("overpass OK: %d elements", len(data.get("elements", [])))
                return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                LOG.warning("overpass attempt %d failed: %s", attempt, exc)
                if attempt < self.retries:
                    time.sleep(self.retry_backoff_s * attempt)
        # final fallback: empty dataset (caller decides what to do)
        LOG.error("overpass exhausted retries; returning empty: %s", last_err)
        return {"elements": [], "_error": str(last_err) if last_err else "unknown"}
