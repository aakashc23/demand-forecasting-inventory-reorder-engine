# SQL layer

An analytical layer on top of the Python outputs. The SQL only joins and aggregates. Forecasting and the
safety-stock / reorder-point math are **not** re-implemented here.

| file | what it does |
|---|---|
| `01_schema.sql` | drops and creates 5 tables (1 dimension, 4 facts) |
| `02_views.sql` | 3 views: `v_sales_history`, `v_forecast_results`, `v_reorder_recommendations` |
| `03_analysis.sql` | 10 named analyses (`-- name: <snake_case>` + a business question comment) |

The SQL is portable: standard types, CTEs, window functions, `CASE`, `SQRT`. It runs unchanged on SQLite and PostgreSQL/Supabase.

## Run on SQLite (no server needed)

```
.venv\Scripts\python -m src.sql_layer
```

This deletes and rebuilds `data/processed/reorder_engine.db` (git-ignored), creates the tables from `01_schema.sql`,
loads them with pandas, creates the views, runs every analysis into `outputs/sql_results/<name>.csv`, and reconciles
the SQL against the Python outputs (asserts, 1e-6 relative tolerance, exact for counts). The reconciliation table is
written to `reports/sql_reconciliation.md`. The run also writes table-shaped CSVs to `data/processed/sql_load/`.

Test: `.venv\Scripts\python -m pytest -q tests/test_sql_layer.py`

## Load into PostgreSQL / Supabase

The runner exports one CSV per table to `data/processed/sql_load/` (flags as 0/1, ISO dates, `year_month` and `weekday`
derived, `fold` empty for future rows). Load those, not the raw pipeline CSVs, because the column sets match the tables.

```
psql "$DATABASE_URL" -f sql/01_schema.sql

\copy dim_sku_location   FROM 'data/processed/sql_load/dim_sku_location.csv'   WITH (FORMAT csv, HEADER true)
\copy fact_sales_daily   FROM 'data/processed/sql_load/fact_sales_daily.csv'   WITH (FORMAT csv, HEADER true)
\copy fact_backtest      FROM 'data/processed/sql_load/fact_backtest.csv'      WITH (FORMAT csv, HEADER true)
\copy fact_forecast      FROM 'data/processed/sql_load/fact_forecast.csv'      WITH (FORMAT csv, HEADER true)
\copy fact_reorder       FROM 'data/processed/sql_load/fact_reorder.csv'       WITH (FORMAT csv, HEADER true)

psql "$DATABASE_URL" -f sql/02_views.sql
psql "$DATABASE_URL" -f sql/03_analysis.sql
```

Run the `\copy` lines inside `psql` (each must be on one line). In `fact_forecast.csv` empty fields load as NULL
(`actual_demand`, `fold` for future rows). `03_analysis.sql` holds 10 queries, so run them one at a time in the
SQL editor if you want to see each result.

## Where each table comes from

| table | source | notes |
|---|---|---|
| `dim_sku_location` | `data/processed/sales_clean.csv` + `outputs/reorder_list.csv` | one row per series; `latest_price` = sell price on the last day; `lead_time` from the reorder list (config assumption) |
| `fact_sales_daily` | `data/processed/sales_clean.csv` | `year_month` and `weekday` stored as columns (no date functions in SQL); flags cast to 0/1 |
| `fact_backtest` | `outputs/backtest_forecasts.csv` | all 5 models, all 3 folds; error columns dropped (SQL recomputes `forecast - actual`) |
| `fact_forecast` | `outputs/forecasts.csv` | selected model only: backtest rows with actuals plus the 28-day future (`actual_demand` and `fold` NULL) |
| `fact_reorder` | `outputs/reorder_list.csv` | every column, one row per SKU-location |

## What the views add

- `v_sales_history`: daily sales joined to the SKU/location/state dimension.
- `v_forecast_results`: forecast rows plus `error` (forecast - actual, positive = over-forecast) and `abs_error`, NULL where there is no actual.
- `v_reorder_recommendations`: the reorder list plus `priority_rank` (`ROW_NUMBER` by risk order HIGH, MEDIUM, OVERSTOCK, OK, then
  `days_of_cover`, then `series_id` as a tie-break) and `inventory_gap = reorder_point - inventory_position`.

## Why safety stock / reorder point stay in Python

`src/inventory.py` is the single source of truth for lead-time demand, safety stock, reorder point, order-up-to and order
quantity. If the same formulas were re-written in SQL, the two copies could drift apart and the dashboard and the database could
disagree. SQL reads `fact_reorder` as given and only ranks, filters and aggregates it. The same applies to the forecasts:
SQL computes accuracy metrics (MAE, RMSE, WAPE, Bias) from the stored forecasts and checks that they equal `outputs/model_comparison.csv`.

## Notes

- Numeric columns use `DOUBLE PRECISION` (SQLite maps it to REAL; PostgreSQL keeps full 8-byte precision, whereas `REAL` there is 4 bytes).
- Ratios multiply by `1.0` and use `NULLIF` so integer division and divide-by-zero cannot bite on either engine.
- If your SQLite build lacks `SQRT` (needs `SQLITE_ENABLE_MATH_FUNCTIONS`), the runner registers it; the SQL is unchanged.
