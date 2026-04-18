"""HTTP client for the api-ninjas nutrition endpoint with a persistent cache.

The cache is keyed on the already-normalized query string and stores the
raw API response (so re-parsing into new fields later doesn't require
re-fetching). Empty / failed responses are cached too, so unparseable
inputs don't keep burning quota.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from .models import MealItem

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 15

# Numeric fields we keep from the API response. Anything else (including
# paywalled fields like `calories` / `protein_g` that come back as strings
# on the free plan) is dropped before caching.
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
    """Return a float if `val` is numeric, else None.

    Paywalled fields come back as strings like
    "Only available for premium subscribers." — those resolve to None
    so they're excluded rather than coerced to 0.0.
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
    """Keep only `name` and known numeric fields from a raw API item."""
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
    """Cache-first wrapper around the nutrition API."""

    def __init__(self, api_key: str, api_url: str, cache_path: Path):
        self.api_key = api_key
        self.api_url = api_url
        self.cache_path = Path(cache_path)
        self._cache: dict[str, list[dict]] = self._load_cache()

    def get_nutrition(self, normalized_query: str) -> list[MealItem]:
        """Return parsed nutrition facts for a query, hitting the cache first."""
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

    def _parse_items(self, items: list[dict]) -> list[MealItem]:
        meal_items = []
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
            meal_items.append(MealItem(**kwargs))
        return meal_items

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

        # Re-clean on load so caches written by older versions self-heal.
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
