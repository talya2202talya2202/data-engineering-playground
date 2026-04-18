"""Entry point for the xzcoolio_nutrition pipeline.

Usage:
    python main.py

Expects data/meals_data_raw.csv to exist. Writes outputs/daily_summaries.csv
and persists an API cache under cache/nutrition_cache.json.
"""

import logging

import config
from src import pipeline


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    _setup_logging()
    pipeline.run()
    print(f"\nDone. Output written to {config.OUTPUT_PATH}")


if __name__ == "__main__":
    main()
