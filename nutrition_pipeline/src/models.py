"""Domain dataclasses used by the pipeline.

Plain dataclasses (no Pydantic) to keep dependencies minimal per the
assignment. Numeric defaults of 0.0 make summing safe when a field is
missing from the API response.
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawMeal:
    """One row of user input plus its normalized form."""

    person: str
    raw_text: str
    date: date
    normalized_text: str = ""


@dataclass
class MealItem:
    """A single food item returned by the nutrition API."""

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
    """A RawMeal joined with its parsed API response (in-memory only)."""

    raw: RawMeal
    meal_items: list[MealItem] = field(default_factory=list)


@dataclass
class DailySummary:
    """Per-(person, date) nutrient totals with alert flags."""

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
