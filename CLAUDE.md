# CLAUDE.md — Demand Forecasting & Inventory Reorder Engine

This is a small, resume-level analytics project. The spec below is the design contract.
Keep the code small and readable. When code and this file disagree, fix one of them so they agree.

## The question the project answers
**"Which SKU/location should we reorder today, and how much?"**
The main deliverable is `outputs/reorder_list.csv` (the daily reorder list), not a forecast chart.

## Hard rules
- **Never fabricate metrics.** Every number in the README, figures, or dashboard must come from running the code.
  Get README numbers from `outputs/*.csv`. Don't type them from memory.
- **Never split time series at random.** Use rolling-origin (expanding-window) backtesting only.
- **Keep FORECASTING and INVENTORY DECISION separate.** `src/models.py`, `src/backtest.py` and `src/forecast.py` never compute
  inventory quantities. `src/inventory.py` takes forecasts and errors as input and never fits models.
- No ML/DL models (no XGBoost, LightGBM, LSTM, transformers). No APIs, cloud infra, auth, or streaming.
- Scripts and modules rather than notebooks. Everything runs from `python run_pipeline.py`.
- Fixed random seeds (`SEED = 42`) wherever randomness is used (only for the synthetic inventory snapshot).
- Put every assumption in `src/config.py` and document it in the README "Assumptions" table.

## Stack
Python 3.12, a venv in `.venv/`, and dependencies in `requirements.txt` (pandas, numpy, statsmodels, matplotlib, pytest).
SQL: Postgres-dialect files in `sql/` (the database is optional; the pipeline doesn't depend on it).
Dashboard: Power BI, built from the CSVs in `outputs/powerbi/`. The build spec is in `dashboard/POWERBI_GUIDE.md`.

Run commands (Windows):
```
.venv\Scripts\python run_pipeline.py      # full pipeline
.venv\Scripts\python -m pytest -q         # tests
```

## Dataset: M5 (Walmart), representative subset
- Source: the M5 competition data (sales_train_evaluation.csv, calendar.csv, sell_prices.csv), downloaded from the public
  Nixtla mirror `https://github.com/Nixtla/m5-forecasts/raw/main/datasets/m5.zip` (~50 MB, no Kaggle auth needed).
  Raw files go in `data/raw/` and are git-ignored.
- Why M5: it has real SKU × store daily data plus calendar and prices. Rossmann is store-level only (no SKU).
  Favorita is ~125M rows, which is overkill here.
- **Subset (documented sampling logic):**
  - Stores: `CA_1`, `TX_1`, `WI_1` (one store per state, so the three locations differ).
  - Department: `FOODS_3` (the highest-volume, fast-moving category, which gives a sensible forecast/inventory setting).
  - Eligibility (continuously stocked fast movers), with both rules applied in **every** one of the 3 stores:
    (a) zero-sales share ≤ 20% during the 365 days ending at the first backtest origin (2016-02-28). Only 28 items passed at 10%.
    (b) at least one sale in the first 28 days of the history window, so the item was already listed. This excludes pre-launch zeros.
    These rules remove items that were unlisted or out of stock for long stretches. Intermittent or slow movers need other
    methods (e.g. Croston) and are out of scope.
  - Items: **up to 50 eligible items by total units across the 3 stores**, ranked **only on data up to the first
    backtest origin** (no look-ahead). If fewer qualify, all eligible items are used; don't loosen the rules to reach 50.
    The same items appear in all 3 stores, so series = items × 3. `data_prep` prints the exact count.
  - History window: **2014-05-22 → 2016-05-22**, which is 732 days inclusive (2016 is a leap year). d_1941 is the last day of M5.
  - Note: the Nixtla `calendar.csv` has no `d` column, so `d_N` is derived from row position (row 1 = d_1 = 2011-01-29).
- **Cleaning:**
  - Melt wide to long, one row per `date, item_id, store_id, units`, and join the calendar and sell_price.
  - Christmas (Dec 25): the stores are closed and sales are ~0. Impute with the value from the same weekday one week earlier, and flag it.
  - Zero-sales runs of ≥7 days on these top sellers are *likely stockouts* (censored demand). Flag them and report
    them. Don't impute them (this is a documented limitation: sales ≠ true demand).
  - Output: `data/processed/sales_clean.csv`.

## Forecasting (daily, horizon H = 28 days)
Model hierarchy, simplest first. All models are pure functions `f(train_series, horizon) -> np.ndarray`, clipped at 0:
1. `naive`: last observed value.
2. `seasonal_naive`: the same weekday last week (lag 7). This is the seasonal baseline.
3. `moving_average`: mean of the last 28 days.
4. `seasonal_ma`: a decomposition baseline. Level = mean of the last 28 days; multiply by day-of-week seasonal indices
   estimated on the last 364 days (ratio to the weekly mean). This is a classical-decomposition-style forecast.
5. `holt_winters`: `statsmodels` `ExponentialSmoothing(trend="add", damped_trend=True, seasonal="add",
   seasonal_periods=7)`, fit on the last 364 days. If a fit fails, fall back to `seasonal_ma` and log the count.

**Validation:** rolling-origin backtest with 3 folds, each forecasting 28 days:
| fold | train end (origin) | test window |
|---|---|---|
| 1 | 2016-02-28 | 2016-02-29 → 2016-03-27 |
| 2 | 2016-03-27 | 2016-03-28 → 2016-04-24 |
| 3 | 2016-04-24 | 2016-04-25 → 2016-05-22 |

**Metrics** (per model, per fold, and overall): MAE, RMSE, **WAPE** = Σ|e| / Σ actual (the headline percentage metric),
Bias = Σe / Σ actual, and MASE (scaled by the in-sample seasonal-naive MAE). **MAPE is not used as a headline metric** because
daily SKU sales contain zeros, so MAPE is undefined or explodes. The README says this.

**Model selection (parsimony rule):** a single global model, the **simplest** model (complexity order naive < seasonal_naive <
moving_average < seasonal_ma < holt_winters) whose overall WAPE is within `SELECTION_TOLERANCE_PP = 1.0` percentage point of the
best. Report how often each model wins per series, but don't select per series (it overfits and is harder to explain).

**Final forecast:** refit the chosen model on all history up to the as-of date **2016-05-22**, forecast 2016-05-23 → +28 days
→ `outputs/forecast_next_28d.csv`.

## Inventory decision (`src/inventory.py`)
Assumptions (all in `config.py`):
- **Service level** 95% (cycle service level) → Z = 1.645 (`scipy.stats.norm.ppf`).
- **Lead time** is set per store (illustrative supplier/DC distances): CA_1 = 5 days, TX_1 = 7 days, WI_1 = 10 days.
- **Review period:** daily. The reorder list runs on the morning of `RUN_DATE` = 2016-05-23, and an order placed that morning arrives
  L days later. Order cycle target T = 7 days of cover beyond lead time.
- **Case pack** = 6 units (illustrative, since M5 has no pack sizes). Order quantities are rounded up to whole cases.
- **σ_demand** = RMSE of the chosen model's daily forecast errors for that series across the backtest folds. This is forecast-error
  variability, not raw demand variability, because safety stock should cover what the forecast cannot predict. RMSE
  (not std) is used so any bias is also covered. Assumes day-to-day errors are independent (a limitation).
- **Current inventory:** M5 has **no inventory data**, so the on-hand snapshot is **synthetic**:
  `on_hand = round(U(0, 45) days × mean daily forecast)` with seed 42, spanning understock to overstock. Open orders are assumed to be 0, so inventory position
  equals on-hand. This is stated plainly in the README and the dashboard.

Formulas:
- `lead_time_demand` = Σ forecast over the next L days
- `safety_stock` = Z × σ_demand × √L
- `reorder_point` = lead_time_demand + safety_stock
- `order_up_to` = reorder_point + Σ forecast over the T days after the lead time
- `recommended_order_quantity` = ceil((order_up_to − IP) / case_pack) × case_pack if IP ≤ reorder_point, else 0 (never negative)
- `days_of_cover` = on_hand / mean daily forecast
- `order_value` = qty × latest sell_price

Risk flags (by priority):
- `HIGH`: on_hand < lead_time_demand (stocks out before replenishment, even if ordered today)
- `MEDIUM`: on_hand ≤ reorder_point (reorder now)
- `OVERSTOCK`: days_of_cover > 30
- `OK`: otherwise

**Reorder list** `outputs/reorder_list.csv`, one row per SKU-location, sorted by risk then days_of_cover. Columns:
`date, sku, location, series_id, current_inventory, inventory_position, forecast_demand (= lead-time demand), forecast_daily_avg,
lead_time, demand_std, service_level, z_value, safety_stock, reorder_point, order_up_to, recommended_order_quantity, order_value,
days_of_cover, stockout_risk, reorder_decision`. `outputs/reorder_list_today.csv` keeps only the rows with qty > 0.

**Policy simulation** (`src/simulate.py`, small): replay fold 3 (the last 28 days) day by day using actual sales as demand
(lost sales when stock runs short). Use only information available at the fold-3 origin: the fold-3 forecasts, with σ taken from folds 1–2
only. Compare the proposed policy against a naive rule (order-up-to = 28-day MA × (L+T), no safety stock).
Report fill rate, stockout days, and average on-hand units and $ value → `outputs/policy_simulation.csv`.

## Layout
```
run_pipeline.py            # runs every step in order
src/config.py              # paths, dates, subset, assumptions
src/data_prep.py           # download, subset, clean
src/models.py              # 5 forecasting models (pure functions)
src/backtest.py            # rolling-origin evaluation + metrics
src/forecast.py            # final refit + 28-day forecast
src/inventory.py           # SS / ROP / order qty / flags → reorder list
src/simulate.py            # policy replay on fold 3
src/export_powerbi.py      # tidy tables for Power BI
src/plots.py               # README figures → reports/figures/
sql/                       # Postgres DDL + business queries over the outputs
dashboard/                 # Power BI build guide + DAX measures
tests/                     # unit tests for metrics + inventory math
```

## Style
Plain functions, type hints, short docstrings, no classes unless they help. Use pandas vectorization over loops where
it stays readable. Loops over 150 series are fine. Print a short progress/summary line for each pipeline step.
