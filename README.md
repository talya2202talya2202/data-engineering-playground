# XZCoolio Nutrition — Data Engineering Assignment

Two deliverables sit at the root of this repo:


| Part  | Deliverable                                    | What it is                                                                                                                                                                                                                                                     |
| ----- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1** | `[nutrition_pipeline/](./nutrition_pipeline/)` | Runnable Python ETL that reads the meal-log CSV, enriches each meal via the nutrition API (with a persistent cache), and produces per-user daily summaries plus sodium/potassium alerts. See `[nutrition_pipeline/README.md](./nutrition_pipeline/README.md)`. |
| **2** | `[ETL_DESIGN.md](./ETL_DESIGN.md)`             | Production ETL design — tables, steps, alerting, reporting, monitoring, and the key decisions behind them.                                                                                                                                                     |


---

Other content in this repo (unrelated prior exercise):

- `[sql_hit_list/](./sql_hit_list/)` — SQL solution for a separate "hit list" exercise.

