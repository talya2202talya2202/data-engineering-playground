"""Domain models for the nutrition pipeline.

Plain dataclasses are used instead of Pydantic to keep the dependency surface
minimal (assignment constraint) while still giving us typed, explicit shapes
that map cleanly to rows in the eventual warehouse tables described in the
ETL design (see README / ETL doc).
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawMeal:
    """One row of user input plus any cleaning-stage derived fields.

    Maps to a row of `stg.meals` in the productionized ETL (see the ETL
    design doc): `raw_text` is exactly what the user sent, and
    `normalized_text` is populated by the cleaning step (pipeline.clean_meals)
    so every downstream consumer — enrichment, aggregation, debugging —
    sees the same stable, canonical query string without re-deriving it.
    """

    person: str
    raw_text: str
    date: date
    normalized_text: str = ""


@dataclass
class NutritionFact:
    """A single food item returned by the nutrition API.

    Maps to a row of `stg.meal_items` in the productionized ETL. The API
    may return multiple items per query (e.g. "ham and cheese" → ham item
    + cheese item), so an EnrichedMeal holds a *list* of these. All numeric
    fields default to 0.0 so summing is always safe when a field is missing
    from the API response.
    """

    food_name: str = ""
    serving_size_g: float = 0.0
    sodium_mg: float = 0.0
    potassium_mg: float = 0.0
    carbohydrates_total_g: float = 0.0
    fiber_g: float = 0.0
    sugar_g: float = 0.0
    fat_total_g: float = 0.0
    fat_saturated_g: float = 0.0
    cholesterol_mg: float = 0.0


@dataclass
class EnrichedMeal:
    """A RawMeal joined with its parsed API response.

    In production this is a logical join of `stg.meals` and `stg.meal_items`,
    not a persisted table — it only exists as an in-memory step before
    daily aggregation. `raw.normalized_text` is the cache key that was
    used for enrichment; we don't duplicate it on this class.
    """

    raw: RawMeal
    nutrition: list[NutritionFact] = field(default_factory=list)


@dataclass
class DailySummary:
    """Per-(person, date) nutrition roll-up with alert flags.

    Maps to `mart.fct_daily_nutrition` in the productionized ETL — one row
    per (user, local_date) with nutrient totals and per-rule alert flags.
    """

    person: str
    date: date
    total_sodium_mg: float = 0.0
    total_potassium_mg: float = 0.0
    total_carbohydrates_total_g: float = 0.0
    total_fiber_g: float = 0.0
    total_sugar_g: float = 0.0
    total_fat_total_g: float = 0.0
    total_fat_saturated_g: float = 0.0
    total_cholesterol_mg: float = 0.0
    meal_count: int = 0
    sodium_alert: bool = False
    potassium_alert: bool = False
