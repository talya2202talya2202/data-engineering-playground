# ETL Design — Nutrition Tracking Product

## Product vision

The product can evolve in two directions:

- **Real-time** (B2C app, clinical monitoring) — users need immediate feedback ("you've already hit 90% of your sodium budget today"). Requires a streaming-first architecture.
- **Batch only** (corporate wellness reporting, research datasets) — overnight rollups would be enough.

This design targets the real-time direction, with a batch layer on top for reconciliation. In either case the system must support **scale** (millions of users), **expensive rate-limited enrichment** against the nutrition API, **per-user personalization**, and a single source of truth that feeds analytics, alerts, and ML.

---

## Architecture

```
                    ┌─ Streaming pipeline (always on) ───────────────────────┐
ingestion sources ─►│ Kafka → meal_events → meals → meal_items →             │─► Alerts
   (app, web,       │                       (cache lookup +                  │   Dashboards
    voice, B2B)     │                        nutrition API)                  │
                    │                                                        │
                    │                  →  fct_daily_nutrition (live)         │
                    └────────────────────────────────────────────────────────┘
                              ▲
                              │ rebuilds + reconciles from meal_events
                    ┌─ Batch (Airflow) ──────────────────────────────────────┐
                    │ end-of-day close · rollups · DQ · cost · backfills     │
                    └────────────────────────────────────────────────────────┘
```

A streaming consumer drives the live pipeline; an Airflow batch layer runs scheduled jobs against the same Iceberg tables for end-of-day finalization, rollups, data quality, and backfills. Either layer can recover the system on its own.

---

## Tables

All tables live in S3 + Iceberg, partitioned by date.


| Table                           | Layer     | Key                           | Purpose                                                                                                 |
| ------------------------------- | --------- | ----------------------------- | ------------------------------------------------------------------------------------------------------- |
| `meal_events`                   | raw       | `event_id`                    | Append-only source of truth — every event exactly as received.                                          |
| `meals`                         | staging   | `meal_id`                     | One row per meal after parse, dedupe, timezone fix, normalization.                                      |
| `nutrition_cache`               | staging   | `normalized_text`             | API-cost lever. Stores `api_response_json`, `hit_count`, `last_refreshed_at`.                           |
| `meal_items`                    | staging   | `meal_item_id` (FK `meal_id`) | One row per food item returned by the API.                                                              |
| `users_dim`                     | staging   | `user_id`                     | User profile (timezone, demographics, conditions).                                                      |
| `targets`                       | staging   | `(user_id, valid_from)`       | **SCD2** — per-user nutritional targets that change over time.                                          |
| `dq_issues`                     | staging   | `issue_id`                    | Rows rejected at any step, with reason code.                                                            |
| `analytics.fct_daily_nutrition` | analytics | `(user_id, date)`             | Summed nutrients, alert flags, extensible `alerts_json`, `is_final`. **Reporting + alerting source.**   |
| `analytics.fct_alerts`          | analytics | `alert_id`                    | Alerts dispatched (`channel`, `delivered_at`, `user_ack_at`). **Alerting + alert-precision analytics.** |
| `analytics.fct_api_usage`       | analytics | `request_id`                  | One row per API call (cache hit, latency, status). **Monitoring + cost control.**                       |


### Per-user targets (SCD2)

Targets aren't constants: a user with hypertension gets a stricter sodium limit; a marathon runner gets a different one; a clinician may update a patient's targets monthly. They are tracked in their own table:

```
user_id | valid_from | valid_to   | is_current | sodium_limit_mg | potassium_target_mg
42      | 2024-01-01 | 2024-06-15 | false      | 2300            | 3500
42      | 2024-06-15 | NULL       | true       | 1800            | 4000
```

Aggregation joins each meal to the `targets` row valid on that meal's date, so historical days are evaluated against the targets the user actually had at the time. The same SQL serves every user.

---

## Pipeline steps

Each step is implemented as a function the streaming consumer calls per event-batch, and that Airflow can re-run on a window for backfills.

**1. Ingest.** Client posts a meal to an Ingestion API → published to Kafka → consumer writes the raw JSON to `meal_events`.

**2. Parse + clean.** Validate schema, type-coerce, dedupe on `event_id`, derive `meal_date` in the user's timezone, run `normalize_meal_text()`. Output → `meals` (with `normalized_text` populated). Bad rows → `dq_issues`.

**3. Enrich via API.** For each meal, look up `normalized_text` in `nutrition_cache`:

- **Cache hit** → reuse `api_response_json`; increment `hit_count`.
- **Cache miss** → call the nutrition API; store the response in `nutrition_cache` with `first_seen_at` / `last_refreshed_at`.

Either way, parse the response into `meal_items` (one row per food). Every call is logged to `fct_api_usage` for cost and latency monitoring.

**4. Aggregate + flag.** `GROUP BY (user_id, meal_date)` over `meal_items`, joined to `users_dim` and the `targets` row valid on that date. Compute summed nutrients and per-target alert flags. Write to `fct_daily_nutrition` with an idempotent `MERGE` on `(user_id, date)` so late-arriving meals update the row in place.

**5. Emit alerts.** A CDC consumer watches `fct_daily_nutrition`. When an alert flag flips (e.g. `sodium_alert: false → true`), it dedupes against existing `(user_id, date, alert_type)` rows in `fct_alerts`, dispatches via push / email / SMS, and writes the dispatch outcome back to `fct_alerts`.

### Batch layer (Airflow)

Scheduled jobs that read and write the same Iceberg tables:

- **End-of-day close** — once a user's local midnight passes, set `is_final = true` on yesterday's row and emit any final-day alerts.
- **Rollups** — daily DAG builds weekly and monthly aggregates from `fct_daily_nutrition` for trend dashboards.
- **Data quality** — dbt + Great Expectations tests after every run: row counts, null rates, freshness SLAs, schema drift. Failures page the on-call.
- **Cost monitoring** — daily report from `fct_api_usage` with a circuit breaker that pauses enrichment workers if cost-per-hour exceeds budget.
- **Backfills** — the same step functions, re-run over a historical window.

---

## How alerts, reporting, and monitoring are served


| Concern        | How it's addressed                                                                                                                                                                                        |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Alerts**     | Step 4 sets flags on `fct_daily_nutrition` → CDC stream → Step 5 dispatcher writes to `fct_alerts`. Per-user thresholds come from `targets` SCD2. New rules go into `alerts_json` without schema changes. |
| **Reporting**  | Dashboards read `fct_daily_nutrition` for daily views and the rollup tables for trends. Aggregate-only — no PII in this layer.                                                                            |
| **Monitoring** | `fct_api_usage` powers cost and cache-hit dashboards; `dq_issues` powers data-quality dashboards. Freshness SLAs on every table; on-call paging on breach.                                                |


---

## Key design decisions

1. **Streaming-first with a batch safety net.** Real-time alerts require streaming; the batch layer reconciles, finalizes, and runs DQ on the same Iceberg tables. Either layer can carry the system if the other is down.
2. **Cache as a shared table, not a file.** `nutrition_cache` is shared across all streaming workers and the batch layer — one source of truth for API cost. Without it, API calls scale linearly with meals; with it, they scale with the number of unique normalized phrases.
3. **Per-user targets via SCD2.** Personalization without losing history; historical days are evaluated against the targets that were valid at the time.
4. **Extensible alerting.** Common rules get dedicated columns on `fct_daily_nutrition`; new rules go into `alerts_json` so the schema does not change every time the product team adds a metric.
5. **Idempotency throughout.** Natural keys (`event_id`, `meal_id`, `(user_id, date)`) and `MERGE` writes mean any step can be safely re-run on any window — and the streaming layer scales horizontally (Kafka partitions, parallel Spark/Flink workers) without sacrificing correctness.
6. **PII isolation.** Raw user text lives only in raw and staging (access-restricted); analytics holds aggregates only. GDPR delete-by-user via soft-delete on the partition key.

