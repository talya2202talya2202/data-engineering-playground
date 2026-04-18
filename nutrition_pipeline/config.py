"""Configuration: paths, thresholds, and API credentials.

Secrets are read from `.env` (gitignored) or the environment.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ["XZCOOLIO_API_KEY"]
API_URL = "https://api.api-ninjas.com/v1/nutrition"

DAILY_SODIUM_LIMIT_MG = 2300
DAILY_POTASSIUM_TARGET_MG = 3500

CSV_PATH = PROJECT_ROOT / "data" / "meals_data_raw.csv"
CACHE_PATH = PROJECT_ROOT / "cache" / "nutrition_cache.json"
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "daily_summaries.csv"
