"""Alert rules and human-readable reporting.

Alert logic is isolated from aggregation so new rules (e.g. added-sugar cap,
saturated-fat cap, per-user personalized targets) can be added without
touching the pipeline. In the future `check_alerts` would take a per-user
`NutritionTarget` object instead of the global constants — the function
signature is already set up for that evolution.
"""

from __future__ import annotations

from collections import defaultdict

from config import DAILY_POTASSIUM_TARGET_MG, DAILY_SODIUM_LIMIT_MG

from .models import DailySummary


def check_alerts(summary: DailySummary) -> DailySummary:
    """Mutate & return the summary with alert flags set."""
    summary.sodium_alert = summary.total_sodium_mg > DAILY_SODIUM_LIMIT_MG
    summary.potassium_alert = summary.total_potassium_mg < DAILY_POTASSIUM_TARGET_MG
    return summary


def print_alert_report(summaries: list[DailySummary]) -> None:
    """Print a grouped-by-person report of days with at least one alert."""
    flagged = [s for s in summaries if s.sodium_alert or s.potassium_alert]

    print("\n=== NUTRITION ALERTS ===\n")

    if not flagged:
        print("No alerts — everyone hit their targets. \n")
        return

    by_person: dict[str, list[DailySummary]] = defaultdict(list)
    for s in flagged:
        by_person[s.person].append(s)

    def _person_sort_key(name: str) -> tuple[int, str]:
        digits = "".join(ch for ch in name if ch.isdigit())
        return (int(digits) if digits else 10**9, name)

    for person in sorted(by_person.keys(), key=_person_sort_key):
        print(f"{person}:")
        for s in sorted(by_person[person], key=lambda x: x.date):
            sodium_part = (
                f"HIGH SODIUM ({s.total_sodium_mg:.1f} mg)"
                if s.sodium_alert
                else "sodium OK"
            )
            potassium_part = (
                f"LOW POTASSIUM ({s.total_potassium_mg:.1f} mg)"
                if s.potassium_alert
                else "potassium OK"
            )
            print(f"  {s.date.isoformat()} | {sodium_part} | {potassium_part}")
        print()
