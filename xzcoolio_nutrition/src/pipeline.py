"""End-to-end orchestration: CSV → API enrichment → aggregation → alerts.

Each step is its own pure(-ish) function so it can be unit tested or swapped
for an Airflow/Dagster task in the productionized pipeline (see the ETL
design doc). `run()` is the only entry point callers should need.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import config

from .alerts import check_alerts, print_alert_report
from .meal_parser import normalize_meal_text
from .models import DailySummary, EnrichedMeal, NutritionFact, RawMeal
from .nutrition_client import NutritionClient

logger = logging.getLogger(__name__)


def load_csv(csv_path: Path) -> list[RawMeal]:
    meals: list[RawMeal] = []
    with Path(csv_path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            person = (row.get("Person") or "").strip()
            raw_text = (row.get("Meal") or "").strip()
            date_str = (row.get("Date") or "").strip()
            if not person or not raw_text or not date_str:
                logger.debug("Skipping malformed row: %r", row)
                continue
            try:
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("Bad date %r — skipping row", date_str)
                continue
            meals.append(RawMeal(person=person, raw_text=raw_text, date=parsed_date))

    logger.info("Loaded %d raw meals from %s", len(meals), csv_path)
    return meals


def enrich_meals(raw_meals: list[RawMeal], client: NutritionClient) -> list[EnrichedMeal]:
    enriched: list[EnrichedMeal] = []
    for rm in raw_meals:
        normalized = normalize_meal_text(rm.raw_text)
        facts = client.get_nutrition(normalized) if normalized else []
        enriched.append(
            EnrichedMeal(raw=rm, normalized_query=normalized, nutrition=facts)
        )
    logger.info(
        "Enriched %d meals (cache contains %d unique queries)",
        len(enriched),
        client.cache_size,
    )
    return enriched


def aggregate_daily(enriched_meals: list[EnrichedMeal]) -> list[DailySummary]:
    buckets: dict[tuple[str, date], list[EnrichedMeal]] = defaultdict(list)
    for em in enriched_meals:
        buckets[(em.raw.person, em.raw.date)].append(em)

    summaries: list[DailySummary] = []
    for (person, day), meals in buckets.items():
        summary = DailySummary(person=person, date=day, meal_count=len(meals))
        for em in meals:
            for fact in em.nutrition:
                summary.total_sodium_mg += fact.sodium_mg
                summary.total_potassium_mg += fact.potassium_mg
                summary.total_carbohydrates_total_g += fact.carbohydrates_total_g
                summary.total_fiber_g += fact.fiber_g
                summary.total_sugar_g += fact.sugar_g
                summary.total_fat_total_g += fact.fat_total_g
                summary.total_fat_saturated_g += fact.fat_saturated_g
                summary.total_cholesterol_mg += fact.cholesterol_mg
        summaries.append(summary)

    logger.info("Aggregated into %d daily summaries", len(summaries))
    return summaries


def export_csv(summaries: list[DailySummary], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _person_sort_key(name: str) -> tuple[int, str]:
        digits = "".join(ch for ch in name if ch.isdigit())
        return (int(digits) if digits else 10**9, name)

    rows_sorted = sorted(summaries, key=lambda s: (_person_sort_key(s.person), s.date))

    fieldnames = [
        "person",
        "date",
        "meal_count",
        "total_sodium_mg",
        "total_potassium_mg",
        "total_carbohydrates_total_g",
        "total_fiber_g",
        "total_sugar_g",
        "total_fat_total_g",
        "total_fat_saturated_g",
        "total_cholesterol_mg",
        "sodium_alert",
        "potassium_alert",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in rows_sorted:
            writer.writerow(
                {
                    "person": s.person,
                    "date": s.date.isoformat(),
                    "meal_count": s.meal_count,
                    "total_sodium_mg": round(s.total_sodium_mg, 2),
                    "total_potassium_mg": round(s.total_potassium_mg, 2),
                    "total_carbohydrates_total_g": round(s.total_carbohydrates_total_g, 2),
                    "total_fiber_g": round(s.total_fiber_g, 2),
                    "total_sugar_g": round(s.total_sugar_g, 2),
                    "total_fat_total_g": round(s.total_fat_total_g, 2),
                    "total_fat_saturated_g": round(s.total_fat_saturated_g, 2),
                    "total_cholesterol_mg": round(s.total_cholesterol_mg, 2),
                    "sodium_alert": s.sodium_alert,
                    "potassium_alert": s.potassium_alert,
                }
            )

    logger.info("Wrote %d summary rows to %s", len(rows_sorted), output_path)


def run() -> None:
    """Execute the full pipeline end-to-end."""
    client = NutritionClient(
        api_key=config.API_KEY,
        api_url=config.API_URL,
        cache_path=config.CACHE_PATH,
    )

    raw_meals = load_csv(config.CSV_PATH)
    enriched = enrich_meals(raw_meals, client)
    summaries = aggregate_daily(enriched)
    summaries = [check_alerts(s) for s in summaries]
    export_csv(summaries, config.OUTPUT_PATH)
    print_alert_report(summaries)


__all__ = [
    "aggregate_daily",
    "enrich_meals",
    "export_csv",
    "load_csv",
    "run",
    "DailySummary",
    "EnrichedMeal",
    "NutritionFact",
    "RawMeal",
]
