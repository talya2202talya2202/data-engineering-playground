# Nutrition Pipeline

A small ETL that turns free-text meal logs into per-user daily nutrition
summaries with alerts for sodium and potassium intake. This is the
**Part 1** implementation of the assignment. The forward-looking
production architecture is described separately in
[`ETL_DESIGN.md`](./ETL_DESIGN.md).

---

## How to run it

```bash
# from the repo root
cp nutrition_pipeline/.env.example nutrition_pipeline/.env
# fill in your api-ninjas key in nutrition_pipeline/.env

cd nutrition_pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py
# -> writes outputs/daily_summaries.csv
# -> prints an alert report to stdout
```

Inputs:
- `data/meals_data_raw.csv` — raw meal log (Person, Meal, Date)
- `cache/nutrition_cache.json` — persistent cache of API responses (auto-created)

Outputs:
- `outputs/daily_summaries.csv` — one row per (person, date) with totals + alert flags
- stdout — human-readable alert report grouped by person

---

## Project structure

```
nutrition_pipeline/
├── README.md              # this file (Part 1)
├── ETL_DESIGN.md          # Part 2 — production architecture
├── main.py                # entry point
├── config.py              # paths + thresholds + env loading
├── data/                  # input CSV
├── cache/                 # API-response cache (gitignored)
├── outputs/               # generated daily summaries (gitignored)
└── src/
    ├── models.py          # dataclasses (RawMeal, MealItem, EnrichedMeal, DailySummary)
    ├── meal_parser.py     # Step 2: deterministic text normalization
    ├── nutrition_client.py# Step 3: HTTP client + persistent cache
    ├── pipeline.py        # orchestration of all steps + I/O
    └── alerts.py          # Steps 4–5: alert flagging + report
```

---

## How the pipeline is structured

The implementation is intentionally split into small, single-purpose
functions that can be use if the system will extend.
That way the same building blocks can be lifted directly into the
production design — wrapped in an Airflow task or a Kafka consumer loop
— without rewriting their logic.

| Step | Function | What it does |
|---|---|---|
| 1. Ingest | `pipeline.load_csv` | Reads the raw CSV into typed `RawMeal` objects. |
| 2. Parse + clean | `pipeline.clean_meals` (uses `meal_parser.normalize_meal_text`) | Stamps `normalized_text` on every meal. The normalized string is the cache key for Step 3 and is computed exactly once, upstream. |
| 3. Enrich via API | `pipeline.enrich_meals` (uses `nutrition_client.NutritionClient`) | Cache-first lookup against `nutrition_cache.json`; on miss, calls the api-ninjas nutrition endpoint and writes the response back to the cache. Produces `MealItem` rows per food. |
| 4. Aggregate + flag | `pipeline.aggregate_daily` + `alerts.check_alerts` | Sums every nutrient by `(person, date)` into `DailySummary`, then sets `sodium_alert` / `potassium_alert` based on configured thresholds. |
| 5. Emit alerts | `alerts.print_alert_report` + `pipeline.export_csv` | Writes the daily summaries CSV and prints a grouped alert report. (In production this becomes the `analytics.fct_alerts` dispatcher described in `ETL_DESIGN.md`.) |

`pipeline.run()` chains them end-to-end. Each step is a pure function of
its inputs, so any one of them is independently testable, swappable, or
re-runnable.

---

## Built with the production design in mind

The prototype is shaped to make the Part 2 design cheap to adopt: **function
boundaries map 1-to-1 to the named ETL steps** so each one can be lifted into
a streaming consumer or Airflow task by wrapping, not rewriting. **Dataclass
names mirror the production tables** (`RawMeal → meals`, `MealItem →
meal_items`, `DailySummary → analytics.fct_daily_nutrition`) so the warehouse
schema lifts straight from the code. The pipeline is **idempotent on natural
keys** (`person`, `date`) — the same property the production `MERGE` writes
rely on.

---

## Key decisions

### Deterministic ("naive") normalization instead of an LLM/AI parser

`meal_parser.normalize_meal_text` is a regex-based stripper of leading verbs
and trailing meal-context phrases — intentionally simple, reproducible, and
free per call. The trade-off vs an LLM parser is **cache hit rate**: an LLM
would canonicalize more aggressively (fewer nutrition-API calls) but adds
its own per-call cost, so the right choice in production depends on which
API is more expensive. Without real cost numbers to compare, the
deterministic option is the safer default — fully reproducible and free
to run. Swapping it for a smarter parser is a one-file change in
`meal_parser.py` — no caller touches the parser directly.

### Persist the raw API response, not the parsed model

`NutritionClient` writes the raw JSON-shaped response to the cache, not
the parsed `MealItem` objects. If we add or rename fields later, we
re-parse from the existing cache instead of paying the API again.

### Negative results are cached

Unparseable meals like "water throughout the day" return an empty list
from the API. We cache that empty list too, so the next run doesn't
keep retrying and burning quota.

### Plain dataclasses, no Pydantic

Per the assignment's "minimal dependencies" constraint. Dataclasses
give us typed shapes that map cleanly to the warehouse tables in Part 2
without pulling in another library.
