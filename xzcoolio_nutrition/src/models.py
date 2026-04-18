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
    """One row of user input as it appears in the source CSV."""

    person: str
    raw_text: str
    date: date


@dataclass
class NutritionFact:
    """A single food item returned by the nutrition API.

    The API may return multiple items per query (e.g. "ham and cheese" → ham
    item + cheese item), so an EnrichedMeal holds a *list* of these.
    All numeric fields default to 0.0 so summing is always safe when a field
    is missing from the API response.
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
    """A RawMeal joined with its parsed API response."""

    raw: RawMeal
    normalized_query: str
    nutrition: list[NutritionFact] = field(default_factory=list)


@dataclass
class DailySummary:
    """Per-(person, date) nutrition roll-up with alert flags."""

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
