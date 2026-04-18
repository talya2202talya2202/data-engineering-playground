"""End-to-end orchestration: CSV → clean → enrich → aggregate → alerts.

Each step is its own pure(-ish) function so it can be unit tested or swapped
for an Airflow/Dagster task — or wrapped in a streaming consumer loop — in
the productionized pipeline. The function boundaries deliberately mirror
the named steps in ETL_DESIGN.md:

    Step 1  Ingest             -> load_csv          (writes meal_events)
    Step 2  Parse + clean      -> clean_meals       (writes meals)
    Step 3  Enrich via API     -> enrich_meals      (writes meal_items,
                                                     uses nutrition_cache)
    Step 4  Aggregate + flag   -> aggregate_daily + check_alerts
                                                    (writes
                                                     analytics.fct_daily_nutrition)
    Step 5  Emit alerts        -> print_alert_report
                                                    (analytics.fct_alerts in prod)

`run()` is the only entry point callers should need.
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
from .models import DailySummary, EnrichedMeal, MealItem, RawMeal
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


def clean_meals(raw_meals: list[RawMeal]) -> list[RawMeal]:
    """Step 2 (Parse + clean): stamp `normalized_text` on every meal.

    In the productionized ETL this is the job that writes the `meals`
    table — doing it here (rather than inside `enrich_meals`) means the
    normalized string, which is also the `nutrition_cache` key, is
    computed exactly once upstream and becomes a first-class column every
    later step can read from.
    """
    for rm in raw_meals:
        rm.normalized_text = normalize_meal_text(rm.raw_text)
    logger.info("Cleaned/normalized %d meals", len(raw_meals))
    return raw_meals


def enrich_meals(meals: list[RawMeal], client: NutritionClient) -> list[EnrichedMeal]:
    """Step 3 (Enrich via API): look up nutrition facts for each cleaned meal.

    Assumes `clean_meals` has already run, i.e. `meal.normalized_text` is
    set. The client handles cache-first lookup against `nutrition_cache`
    so this loop is cheap when queries repeat.
    """
    enriched: list[EnrichedMeal] = []
    for rm in meals:
        items = client.get_nutrition(rm.normalized_text) if rm.normalized_text else []
        enriched.append(EnrichedMeal(raw=rm, meal_items=items))
    logger.info(
        "Enriched %d meals (cache contains %d unique queries)",
        len(enriched),
        client.cache_size,
    )
    return enriched


def aggregate_daily(enriched_meals: list[EnrichedMeal]) -> list[DailySummary]:
    """Step 4 (Aggregate + flag — aggregate part).

    Buckets enriched meals by (person, date) and sums every nutrient
    column. Maps to the `GROUP BY (user_id, meal_date)` that builds
    `analytics.fct_daily_nutrition` in production. The "+ flag" half of
    Step 4 lives in `alerts.check_alerts`, which sets the alert columns
    on each summary.
    """
    buckets: dict[tuple[str, date], list[EnrichedMeal]] = defaultdict(list)
    for em in enriched_meals:
        buckets[(em.raw.person, em.raw.date)].append(em)

    summaries: list[DailySummary] = []
    for (person, day), meals in buckets.items():
        summary = DailySummary(person=person, date=day, meal_count=len(meals))
        for em in meals:
            for item in em.meal_items:
                summary.total_sodium_mg += item.sodium_mg
                summary.total_potassium_mg += item.potassium_mg
                summary.total_carbohydrates_total_g += item.carbohydrates_total_g
                summary.total_fiber_g += item.fiber_g
                summary.total_sugar_g += item.sugar_g
                summary.total_fat_total_g += item.fat_total_g
                summary.total_fat_saturated_g += item.fat_saturated_g
                summary.total_cholesterol_mg += item.cholesterol_mg
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
    cleaned = clean_meals(raw_meals)
    enriched = enrich_meals(cleaned, client)
    summaries = aggregate_daily(enriched)
    summaries = [check_alerts(s) for s in summaries]
    export_csv(summaries, config.OUTPUT_PATH)
    print_alert_report(summaries)


__all__ = [
    "aggregate_daily",
    "clean_meals",
    "enrich_meals",
    "export_csv",
    "load_csv",
    "run",
    "DailySummary",
    "EnrichedMeal",
    "MealItem",
    "RawMeal",
]
