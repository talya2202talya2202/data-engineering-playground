# ETL Design — Nutrition Tracking Product

## What this product can become

The product can evolve in two directions:

- **Direction A — real-time** (B2C app, clinical monitoring): users need immediate feedback ("you've already hit 90% of your sodium budget today"). This forces a streaming-first architecture.
- **Direction B — batch only** (corporate wellness reporting, research datasets): overnight rollups would be enough.

In either direction the system must support **scale** (millions of users), **expensive rate-limited enrichment** against the nutrition API, **per-user personalization**, and a single source of truth that feeds analytics, alerts, and ML.

**This design implements Direction A — real-time.**

---

## System flow

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

---

## Central tables

All tables live in S3 + Iceberg, partitioned by date.

| Table | Layer | Key | Serves |
|---|---|---|---|
| `meal_events` | raw | `event_id` | Source of truth. Append-only, immutable. Every event exactly as received. |
| `meals` | staging | `meal_id` | One row per meal after parse + dedupe + timezone fix + normalization. |
| `nutrition_cache` | staging | `normalized_text` | API-cost lever. Holds `api_response_json`, `hit_count`, `last_refreshed_at`. |
| `meal_items` | staging | `meal_item_id` (FK `meal_id`) | One row per food returned by the API. Granular nutrient store. |
| `users_dim` | staging | `user_id` | User profile (timezone, demographics, conditions). |
| `targets` | staging | `(user_id, valid_from)` | **SCD2** — per-user nutritional targets that change over time (see below). |
| `dq_issues` | staging | `issue_id` | Rows rejected at any step with reason code. Debugging. |
| `analytics.fct_daily_nutrition` | analytics | `(user_id, date)` | Summed nutrients, alert flags, extensible `alerts_json`, `is_final`. **Reporting + alerting source.** |
| `analytics.fct_alerts` | analytics | `alert_id` | Alerts fired (`channel`, `delivered_at`, `user_ack_at`). **Alerting + alert-precision analytics.** |
| `analytics.fct_api_usage` | analytics | `request_id` | One row per API call (cache hit, latency, status). **Monitoring + cost control.** |

### Handling dynamic targets

Targets aren't constants — a user with hypertension gets a stricter sodium limit; a marathon runner gets a different one; a clinician may update a patient's targets monthly. Handled with a separate **`targets`** table using **SCD2**:

```
user_id | valid_from | valid_to   | is_current | sodium_limit_mg | potassium_target_mg
42      | 2024-01-01 | 2024-06-15 | false      | 2300            | 3500
42      | 2024-06-15 | NULL       | true       | 1800            | 4000
```

When aggregating in Step 4, we join each meal to the `targets` row valid on that meal's date — so historical days are evaluated against the targets the user actually had **at the time**, not today's targets. Same SQL serves every user.

---

## How the process runs

Each step is a function the streaming consumer calls per event-batch (and that Airflow can re-run on a window for backfills).

**1. Ingest.** Client posts a meal to an Ingestion API → published to Kafka → consumer writes the raw JSON to `meal_events` in S3.

**2. Parse + clean.** Validate schema, type-coerce, dedupe on `event_id`, derive `meal_date` in user's timezone, run `normalize_meal_text()`. Output → `meals` (with `normalized_text` populated). Bad rows → `dq_issues`.

**3. Enrich via API.** For each meal, look up `normalized_text` in `nutrition_cache`:
- **Cache hit** → take `api_response_json` from there. Increment `hit_count`.
- **Cache miss** → call the nutrition API, store the response in `nutrition_cache` with `first_seen_at` / `last_refreshed_at`.

Either way, parse the response into `meal_items` (one row per food). Every call is logged to `fct_api_usage` for monitoring.

**4. Aggregate + flag.** `GROUP BY (user_id, meal_date)` over `meal_items`, joined to `users_dim` and the SCD2 `targets` row valid on that date. Compute summed nutrients and per-target alert flags. Write to `fct_daily_nutrition` with an idempotent `MERGE` on `(user_id, date)` so late-arriving meals update the row in place.

**5. Emit alerts.** A CDC consumer watches `fct_daily_nutrition`. When an alert flag flips (e.g. `sodium_alert: false → true`), it dedupes against existing `(user_id, date, alert_type)` rows in `fct_alerts`, then dispatches via push / email / SMS. The dispatch outcome is written back to `fct_alerts`.

**6. End-of-day, rollups, DQ, monitoring** (Airflow batch DAGs):
- **End-of-day close** — once a user's local midnight passes, flip `is_final = true` on yesterday's row and emit any final-day alerts.
- **Rollups** — daily DAG builds weekly/monthly aggregates from `fct_daily_nutrition` for trend dashboards.
- **Data quality** — dbt + Great Expectations tests after every run: row counts, null rates, freshness SLAs, schema drift. Failures page the on-call.
- **Cost monitoring** — daily report from `fct_api_usage` with a circuit breaker that pauses the enrichment workers if cost-per-hour exceeds budget.

---

## Alerts, reporting, monitoring — how each is addressed

- **Alerts** — flags computed in Step 4 → CDC stream → Step 5 dispatcher writes to `fct_alerts`. Per-user thresholds (not global) come from `targets` SCD2. `alerts_json` allows new rules without schema changes.
- **Reporting** — dashboards read `fct_daily_nutrition` for daily views and rollup tables for trends. Aggregate-only — no PII in this layer.
- **Monitoring** — `fct_api_usage` powers cost + cache-hit dashboards; `dq_issues` powers data-quality dashboards; freshness SLAs on every table; on-call paging on breach.

---

## Scaling to millions of users

- **Partition + cluster on `user_id`** in the analytics layer; add `org_id` for B2B row-level security.
- **Streaming layer scales horizontally** — add Kafka partitions and Spark/Flink workers; cache + idempotent merges keep correctness regardless of parallelism.
- **The cache is the dominant cost lever** — without it, API calls scale linearly with meals. With it, they scale with *unique normalized phrases*, which grows logarithmically.
- **PII isolation** — raw text only in raw + staging (access-restricted); analytics holds aggregates only. GDPR delete-by-user via soft-delete on the partition key.
- **Schema evolution** — Iceberg + Kafka schema registry; `schema_version` stamped on every event so old/new parsers can run side-by-side during migrations.

---

## Key decisions

1. **Streaming-first** because we need real-time alerts. Batch (Airflow) layered on top for reconciliation, finalization, rollups, DQ — both layers read/write the same Iceberg tables, so they degrade gracefully if either is down.
2. **Cache is a table, not a file.** `nutrition_cache` is shared across all streaming workers and is the same cache the batch layer uses. One source of truth, one cost story.
3. **Targets are SCD2.** Personalization without losing history.
4. **Extensible alerting.** Common rules get dedicated columns; new rules go into `alerts_json` so the schema doesn't churn every time the product team invents a metric.
5. **Idempotency everywhere.** Natural keys (`event_id`, `meal_id`, `(user_id, date)`) + MERGE writes mean any step can be safely re-run on any window.
