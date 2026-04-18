"""HTTP client for api-ninjas nutrition API with a persistent JSON cache.

Why a cache?
- The API is metered. The raw CSV has ~1000 rows but only a few hundred
  *distinct* meals, and even across runs we should never re-fetch something
  we've already seen.
- The cache key is the already-normalized query string (see meal_parser),
  so "Had a caprese salad for lunch" and "Ate a caprese salad for lunch"
  both resolve to one entry.
- We cache the RAW API response (list of dicts) — NOT the parsed
  NutritionFact objects. If we add/rename fields later we can re-parse
  without re-hitting the API.
- Negative results (empty lists, failures) are also cached so unparseable
  meals like "water throughout the day" don't keep retrying.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from .models import NutritionFact

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 15


def _safe_float(val: Any) -> float:
    """Best-effort float conversion.

    The API sometimes returns missing fields, None, empty strings, or the
    literal string "Only available for premium subscribers." for paywalled
    fields — all of those must become 0.0 so downstream sums don't crash.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError:
            return 0.0
    return 0.0


class NutritionClient:
    def __init__(self, api_key: str, api_url: str, cache_path: Path):
        self.api_key = api_key
        self.api_url = api_url
        self.cache_path = Path(cache_path)
        self._cache: dict[str, list[dict]] = self._load_cache()

    def get_nutrition(self, normalized_query: str) -> list[NutritionFact]:
        """Return parsed nutrition facts for a query, using the cache first."""
        if not normalized_query:
            return []

        if normalized_query in self._cache:
            logger.debug("cache HIT: %s", normalized_query)
            return self._parse_items(self._cache[normalized_query])

        logger.info("cache MISS — fetching: %s", normalized_query)
        items = self._fetch_from_api(normalized_query)
        self._cache[normalized_query] = items
        self._persist_cache()
        return self._parse_items(items)

    def _fetch_from_api(self, query: str) -> list[dict]:
        try:
            resp = requests.get(
                self.api_url,
                headers={"X-Api-Key": self.api_key},
                params={"query": query},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                logger.warning("Unexpected API payload for %r: %r", query, data)
                return []
            return data
        except requests.RequestException as e:
            logger.error("API error for %r: %s", query, e)
            return []
        except ValueError as e:
            logger.error("Invalid JSON for %r: %s", query, e)
            return []

    def _parse_items(self, items: list[dict]) -> list[NutritionFact]:
        return [
            NutritionFact(
                food_name=str(item.get("name", "")),
                serving_size_g=_safe_float(item.get("serving_size_g")),
                sodium_mg=_safe_float(item.get("sodium_mg")),
                potassium_mg=_safe_float(item.get("potassium_mg")),
                carbohydrates_total_g=_safe_float(item.get("carbohydrates_total_g")),
                fiber_g=_safe_float(item.get("fiber_g")),
                sugar_g=_safe_float(item.get("sugar_g")),
                fat_total_g=_safe_float(item.get("fat_total_g")),
                fat_saturated_g=_safe_float(item.get("fat_saturated_g")),
                cholesterol_mg=_safe_float(item.get("cholesterol_mg")),
            )
            for item in items
            if isinstance(item, dict)
        ]

    def _load_cache(self) -> dict[str, list[dict]]:
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("Cache file malformed, starting empty.")
                return {}
            return data
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not load cache (%s); starting empty.", e)
            return {}

    def _persist_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, sort_keys=True)
        except OSError as e:
            logger.error("Failed to persist cache: %s", e)

    @property
    def cache_size(self) -> int:
        return len(self._cache)
