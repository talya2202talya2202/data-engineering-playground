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

# Fields we care about. Anything else in the API response (or any of these
# whose value isn't actually a number — e.g. "Only available for premium
# subscribers.") is dropped before hitting the cache.
_NUMERIC_FIELDS = (
    "serving_size_g",
    "sodium_mg",
    "potassium_mg",
    "carbohydrates_total_g",
    "fiber_g",
    "sugar_g",
    "fat_total_g",
    "fat_saturated_g",
    "cholesterol_mg",
)


def _as_float(val: Any) -> float | None:
    """Return a float if `val` is actually numeric, else None.

    Paywalled fields come back as strings like
    "Only available for premium subscribers." — those are the main reason
    this returns None instead of coercing to 0.0.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except ValueError:
            return None
    return None


def _clean_item(item: dict) -> dict:
    """Strip non-numeric / paywalled fields from a raw API item.

    Keeps `name` and any numeric field from `_NUMERIC_FIELDS`. Everything
    else — including `calories` and `protein_g` on the free plan, any
    future premium-only field, and any field that randomly returns None —
    is dropped at write time.
    """
    cleaned: dict = {}
    name = item.get("name")
    if isinstance(name, str) and name:
        cleaned["name"] = name
    for field in _NUMERIC_FIELDS:
        parsed = _as_float(item.get(field))
        if parsed is not None:
            cleaned[field] = parsed
    return cleaned


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
        raw = self._fetch_from_api(normalized_query)
        cleaned = [_clean_item(item) for item in raw if isinstance(item, dict)]
        self._cache[normalized_query] = cleaned
        self._persist_cache()
        return self._parse_items(cleaned)

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
        # Items are already cleaned by _clean_item before caching, so every
        # numeric field present here is guaranteed to be a float. Missing
        # fields fall back to the dataclass defaults (0.0).
        facts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kwargs: dict[str, Any] = {}
            name = item.get("name")
            if isinstance(name, str):
                kwargs["food_name"] = name
            for field in _NUMERIC_FIELDS:
                if field in item:
                    kwargs[field] = item[field]
            facts.append(NutritionFact(**kwargs))
        return facts

    def _load_cache(self) -> dict[str, list[dict]]:
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("Cache file malformed, starting empty.")
                return {}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not load cache (%s); starting empty.", e)
            return {}

        # Re-apply the field filter so caches written by older versions
        # (with paywalled strings, unknown fields, etc.) self-heal on load.
        return {
            key: [_clean_item(item) for item in items if isinstance(item, dict)]
            for key, items in data.items()
            if isinstance(items, list)
        }

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
