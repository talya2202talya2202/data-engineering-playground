# Nutrition Pipeline

A small ETL that turns free-text meal logs into per-user daily nutrition
summaries with sodium and potassium alerts.

This is the **Part 1** implementation of the assignment. The forward-looking
production architecture is described in [`ETL_DESIGN.md`](./ETL_DESIGN.md).

---

## Quick start

```bash
cp nutrition_pipeline/.env.example nutrition_pipeline/.env
# add your api-ninjas key in nutrition_pipeline/.env

cd nutrition_pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

Outputs:
- `outputs/daily_summaries.csv` — one row per (person, date) with nutrient totals and alert flags.
- stdout — a per-person alert report for days that breached a threshold.

---

## Project layout

```
nutrition_pipeline/
├── main.py                 # entry point
├── config.py               # paths, thresholds, env loading
├── data/                   # input CSV
├── cache/                  # API-response cache (gitignored)
├── outputs/                # generated daily summaries (gitignored)
└── src/
    ├── models.py           # RawMeal, MealItem, EnrichedMeal, DailySummary
    ├── meal_parser.py      # free-text → normalized query string
    ├── nutrition_client.py # cache-first HTTP client
    ├── pipeline.py         # step orchestration + CSV I/O
    └── alerts.py           # alert flagging + report
```

---

## Pipeline steps

| Step | Function | What it does |
|---|---|---|
| 1. Ingest | `pipeline.load_csv` | Read the CSV into `RawMeal` records, skip malformed rows. |
| 2. Parse + clean | `pipeline.clean_meals` (uses `meal_parser.normalize_meal_text`) | Stamp `normalized_text` on every meal. The normalized string is the cache key for Step 3. |
| 3. Enrich | `pipeline.enrich_meals` (uses `NutritionClient`) | Cache-first lookup; on miss, call the API and persist the response. Produces one `MealItem` per food item returned. |
| 4. Aggregate + flag | `pipeline.aggregate_daily` + `alerts.check_alerts` | Sum every nutrient by `(person, date)` and set `sodium_alert` / `potassium_alert` against the configured thresholds. |
| 5. Emit | `pipeline.export_csv` + `alerts.print_alert_report` | Write the daily summary CSV and print a grouped alert report. |

`pipeline.run()` chains them. Each step is a pure function of its inputs,
so any one of them is independently testable, swappable, or re-runnable.

---

## Design decisions

### Deterministic normalization instead of an NLP/LLM parser
`meal_parser.normalize_meal_text` lowercases the input, strips leading
verbs (`"Had a..."`, `"Ate..."`, `"Drank..."`) and trailing meal-context
phrases (`"for lunch"`, `"in the morning"`, `"throughout the day"`),
and removes punctuation — so semantically equivalent inputs collapse to
the same query. It's reproducible, free per call, and produces a stable
cache key. An LLM parser would canonicalize more
aggressively (higher cache hit rate, fewer nutrition-API calls) but
introduces its own per-call cost — the right trade-off depends on which
API is more expensive in production. The module is structured so it can
be swapped without touching callers.

### Treating the API as a metered resource
The assignment notes the API isn't free, so the client is cache-first.
`NutritionClient` keeps a persistent JSON cache keyed on the normalized
query string, so two phrasings of the same meal share one call and
re-runs of the pipeline issue zero calls for queries already seen. The
cache stores the **raw** JSON response (not the parsed `MealItem`
objects) so adding or renaming fields later doesn't require re-fetching.
Negative results (empty / failed responses) are cached too, so
unparseable inputs like *"water throughout the day"* don't keep burning
quota.

### Graceful handling of paywalled / missing fields
The free plan returns paywalled fields as strings
(`"Only available for premium subscribers."`).
`_clean_item` keeps only known numeric fields and drops everything else
before caching, so summing downstream is always safe.

### Plain dataclasses, no Pydantic
Per the assignment's "minimal dependencies" constraint. Dataclasses give
typed shapes without an extra runtime dependency.

### Function boundaries match the production design
The five pipeline functions map 1-to-1 to the named ETL steps in
[`ETL_DESIGN.md`](./ETL_DESIGN.md), and the dataclass names mirror the
intended warehouse tables (`RawMeal → meals`, `MealItem → meal_items`,
`DailySummary → fct_daily_nutrition`). The prototype can be lifted into
an Airflow task or a Kafka consumer by wrapping the same functions —
not rewriting them.

---

## Configuration

| Setting | Where | Default |
|---|---|---|
| `XZCOOLIO_API_KEY` | `.env` | required |
| `DAILY_SODIUM_LIMIT_MG` | `config.py` | 2300 |
| `DAILY_POTASSIUM_TARGET_MG` | `config.py` | 3500 |

In production these would come from the per-user `targets` SCD2 table
described in `ETL_DESIGN.md`; here they are global constants.
