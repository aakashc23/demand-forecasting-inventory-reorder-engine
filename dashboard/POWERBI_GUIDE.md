# Power BI build guide

Builds a 3-page report from the CSVs in `outputs/powerbi/` (made by `python -m src.export_powerbi`).
The Streamlit app (`app.py`) mirrors the same three pages. Expected KPI values: `reports/dashboard_reconciliation.md`.

## 1. Get Data

Home > Get Data > Text/CSV, one query per file (Load; no transformations needed):

| File | Role |
|---|---|
| `dim_sku_location.csv` | dimension: one row per SKU-location (123) |
| `dim_date.csv` | dimension: one row per day, 2014-05-22 to 2016-06-19 |
| `fact_sales_daily.csv` | fact: daily units and revenue per series |
| `fact_forecast.csv` | fact: selected model, 3 backtest folds + 28-day future |
| `fact_backtest_all_models.csv` | fact: backtest rows for all 5 models (model comparison drill-down) |
| `model_comparison.csv` | standalone: MAE / RMSE / WAPE per model |
| `reorder_list.csv` | fact: today's reorder decision per series (run date 2016-05-23) |
| `policy_simulation.csv` | standalone: fill rate of proposed vs naive policy |

Then create an empty table `_Measures` (Enter Data) to hold the measures from `dashboard/measures.dax`.

## 2. Data types

Set in Power Query (Transform data) or Column tools.

| Table | Column(s) | Type |
|---|---|---|
| dim_date, fact_sales_daily, fact_forecast, fact_backtest_all_models, reorder_list | `date` | Date |
| dim_date | `week_start` | Date |
| dim_date | `year`, `month`, `weekday_num`, `is_event`, `snap_ca`, `snap_tx`, `snap_wi` | Whole number |
| dim_sku_location | `lead_time` | Whole number |
| dim_sku_location | `latest_price` | Fixed decimal (currency) |
| fact_sales_daily | `units`, `likely_stockout`, `is_outlier` | Whole number |
| fact_sales_daily | `revenue` | Fixed decimal (currency) |
| fact_forecast, fact_backtest_all_models | `actual_demand`, `forecast_demand`, `error`, `abs_error` | Decimal number |
| fact_forecast, fact_backtest_all_models | `fold` | Whole number (blank on future rows) |
| reorder_list | `current_inventory`, `inventory_position`, `lead_time`, `recommended_order_quantity` | Whole number |
| reorder_list | `forecast_demand`, `forecast_daily_avg`, `demand_std`, `safety_stock`, `reorder_point`, `order_up_to`, `days_of_cover` | Decimal number |
| reorder_list | `order_value` | Fixed decimal (currency) |
| model_comparison, policy_simulation | metric columns | Decimal number (WAPE, Bias, fill_rate formatted as %) |
| all tables | ids, names, flags such as `stockout_risk` | Text |

Mark `dim_date` as a date table (Table tools > Mark as date table > `date`). Sort `dim_date[weekday]` by `weekday_num`.
Add the calculated column on `reorder_list` described at the bottom of `measures.dax` (`Risk Rank`) and sort `stockout_risk` by it.

## 3. Relationships (Model view)

A star: dimensions filter facts, **single direction** (dimension to fact), many-to-one.

| From (one side) | To (many side) |
|---|---|
| `dim_sku_location[series_id]` | `fact_sales_daily[series_id]` |
| `dim_sku_location[series_id]` | `fact_forecast[series_id]` |
| `dim_sku_location[series_id]` | `fact_backtest_all_models[series_id]` |
| `dim_sku_location[series_id]` | `reorder_list[series_id]` |
| `dim_date[date]` | `fact_sales_daily[date]` |
| `dim_date[date]` | `fact_forecast[date]` |
| `dim_date[date]` | `fact_backtest_all_models[date]` |

`reorder_list[date]` is a single run date, so it is not related to `dim_date`. `model_comparison` and `policy_simulation` have no relationships.
Always use `dim_sku_location[location]` and `[sku]` for slicers and axes so every fact is filtered the same way.

## 4. Measures

Paste `dashboard/measures.dax` into `_Measures` (New measure, one at a time). Measures: Total Units, Total Revenue, Avg Daily Units,
Forecast Units, Actual Units (Backtest), MAE, RMSE, WAPE, Bias %, Selected Model, SKUs To Reorder, Recommended Units, Order Value,
High Risk SKUs, Fill Rate, Fill Rate (Naive), Risk Color.

Formats: units as whole numbers with a thousands separator; revenue and order value as currency; WAPE, Bias % and Fill Rate as % (1 decimal); MAE and RMSE with 3 decimals.
`model_comparison` also has columns named MAE, RMSE and WAPE. In the model comparison table use those columns; everywhere else use the measures.

## 5. Report pages

Use a light theme and one accent colour (blue `#2563EB`). Give every visual a title that states the business question. Page size 16:9.

### Page 1: Demand Overview
Slicers: `dim_sku_location[location]` (list, multi-select) and, optionally, `dim_date[year]` (tile).

| # | Visual | Fields | Filters | Question it answers |
|---|---|---|---|---|
| 1 | Card x3 | `[Total Units]`, `[Total Revenue]`, `[Avg Daily Units]` | none | How much do we sell? |
| 2 | Card | Min and Max of `dim_date[date]` for days with sales (or a text box from the reconciliation file) | none | What period does the data cover? |
| 3 | Line chart (monthly trend) | X: `dim_date[year_month]`; Y: `[Total Units]` | visual filter: `[Total Units]` is not blank (hides empty 2016-06) | Is demand growing, flat or seasonal? The first and last months are partial. |
| 4 | Clustered bar (top 10 SKUs) | Y: `dim_sku_location[sku]`; X: `[Total Units]` | Top N filter: top 10 by `[Total Units]`; sort descending | Which SKUs drive volume? |
| 5 | Column chart (by location) | X: `dim_sku_location[location]`; Y: `[Total Units]` | none | Which store sells the most? |
| 6 | Column chart (weekday seasonality) | X: `dim_date[weekday]` (sorted by `weekday_num`); Y: `[Avg Daily Units]` | visual filter: `[Total Units]` is not blank | Which weekdays are busiest, so what should we stock for? |

### Page 2: Forecast Performance
Slicers: `dim_sku_location[location]` and `dim_sku_location[sku]` (dropdown).

| # | Visual | Fields | Filters | Question it answers |
|---|---|---|---|---|
| 1 | Card x4 | `[Selected Model]`, `[MAE]`, `[RMSE]`, `[WAPE]` | none | How good is the chosen model? |
| 2 | Line chart (actual vs forecast) | X: `dim_date[date]`; Y: `[Actual Units (Backtest)]`, `[Forecast Units]` | page slicers pick one SKU and one location; visual filter: `dim_date[date]` on or after 2016-01-01 | Does the forecast follow actual sales, and what comes next? Backtest ends 2016-05-22; later days are the future forecast. |
| 3 | Table (model comparison) | `model_comparison[model]`, `[MAE]`, `[RMSE]`, `[WAPE]`, `[Bias]`, `[MASE]`, `[wins]`, `[selected]` | none (no relationships, so the slicers do not apply); conditional format: background where `selected` = TRUE | Which model is most accurate, and which did we select? Rule: the simplest model within 1 percentage point of the best WAPE. |
| 4 | Clustered bar (error by location) | X: `dim_sku_location[location]`; Y: `[WAPE]` | none | Where is the forecast weakest? |
| 5 | Table (SKU/location WAPE) | `dim_sku_location[sku]`, `dim_sku_location[location]`, `[WAPE]`, `[MAE]`, `[RMSE]`, `[Bias %]` | visual filter: `[WAPE]` is not blank; sort by `[WAPE]` descending | Which series are hardest to forecast? |

### Page 3: Inventory Reorder Engine (the most important page)
Title: **Where do I need to reorder today, and how much?**

Slicers: `dim_sku_location[location]` (buttons) and `reorder_list[stockout_risk]` (buttons, ordered by Risk Rank).

**Text box at the top (required): "Current inventory is SYNTHETIC (M5 has no inventory data). Lead times, service level and case pack are assumptions."**

| # | Visual | Fields | Filters | Question it answers |
|---|---|---|---|---|
| 1 | Card | `[SKUs To Reorder]` | none | How many SKU-locations need an order today? |
| 2 | Card | `[Recommended Units]` | none | How many units in total? |
| 3 | Card | `[Order Value]` | none | What is the cash outlay? |
| 4 | Card | `[High Risk SKUs]` | none | How many will stock out before an order can arrive? |
| 5 | Table (reorder table) | `reorder_list[sku]`, `[location]`, `[current_inventory]`, `[forecast_demand]`, `[safety_stock]`, `[reorder_point]`, `[recommended_order_quantity]`, `[stockout_risk]` | visual filter: `recommended_order_quantity` > 0; sort by `stockout_risk` (Risk Rank) ascending, then by `days_of_cover` ascending | Exactly what do I order today, most urgent first? |
| 6 | Column chart (order value by location) | X: `dim_sku_location[location]`; Y: `[Order Value]` | none | Where is the spend concentrated? |
| 7 | Card x2 (optional) | `[Fill Rate]`, `[Fill Rate (Naive)]` | none | Does the policy beat a naive rule in the last-28-day replay? |

Conditional formatting on visual 5, column `stockout_risk`: Cell elements > Background color > Format style "Field value" > `[Risk Color]`
(or Rules: HIGH `#FECACA`, MEDIUM `#FED7AA`, OVERSTOCK `#BFDBFE`, OK `#BBF7D0`).
`forecast_demand` in this table is demand over the lead time. Cards 1 to 4 respond to both slicers.

## 6. Field dictionary

Only the columns Power BI uses.

**dim_sku_location**

| Column | Type | Meaning |
|---|---|---|
| series_id | text | key, `<sku>__<location>` |
| sku | text | M5 item id (FOODS_3 department) |
| location | text | store: CA_1, TX_1, WI_1 |
| state | text | state of the store |
| lead_time | whole | supplier lead time in days (ASSUMPTION per store) |
| latest_price | currency | last observed sell price |

**dim_date**

| Column | Type | Meaning |
|---|---|---|
| date | date | key (history plus the 28 forecast days) |
| year, month, year_month | whole / text | calendar parts |
| week_start | date | Monday of the week |
| weekday, weekday_num | text / whole | day name; Monday = 1 |
| is_event, event_name | whole / text | holiday or event flag and name (observed days only) |
| snap_ca, snap_tx, snap_wi | whole | SNAP benefit day flag per state (blank for future days) |

**fact_sales_daily**

| Column | Type | Meaning |
|---|---|---|
| date, series_id | date, text | keys |
| units | whole | units sold (Christmas imputed from the prior week) |
| revenue | currency | units x sell price |
| likely_stockout | whole | 1 = part of a zero-sales run of 7+ days (sales are not true demand) |
| is_outlier | whole | 1 = day above Q3 + 3 IQR within its series (flagged, not removed) |

**fact_forecast** (selected model) and **fact_backtest_all_models**

| Column | Type | Meaning |
|---|---|---|
| date, series_id | date, text | keys |
| fold | whole | backtest fold 1 to 3 (blank on future rows) |
| forecast_type | text | `backtest` or `future` (fact_forecast only) |
| model_used / model | text | forecasting model |
| actual_demand | decimal | actual units (blank on future rows) |
| forecast_demand | decimal | forecast units |
| error | decimal | forecast minus actual (positive = over-forecast) |
| abs_error | decimal | absolute value of error |

**model_comparison**

| Column | Type | Meaning |
|---|---|---|
| model | text | one of 5 models |
| MAE, RMSE | decimal | units per SKU-day |
| WAPE | % | sum abs error / sum actual |
| Bias | % | sum error / sum actual |
| MASE | decimal | MAE scaled by the in-sample seasonal-naive MAE |
| mape_nonzero | % | MAPE on non-zero days (reference only, not shown) |
| wins | whole | series where this model has the lowest WAPE |
| selected | boolean | model chosen by the parsimony rule |

**reorder_list**

| Column | Type | Meaning |
|---|---|---|
| date | date | run date (2016-05-23) |
| sku, location, series_id | text | identifiers |
| current_inventory | whole | on-hand units (SYNTHETIC) |
| inventory_position | whole | on-hand + open orders (open orders assumed 0) |
| forecast_demand | decimal | forecast units over the lead time |
| forecast_daily_avg | decimal | mean forecast per day, next 28 days |
| lead_time | whole | days (assumption) |
| demand_std | decimal | sigma: backtest RMSE of the series |
| service_level, z_value | decimal | 95% and its normal quantile |
| safety_stock | decimal | Z x sigma x sqrt(lead time) |
| reorder_point | decimal | lead-time demand + safety stock |
| order_up_to | decimal | reorder point + 7 days of forecast |
| recommended_order_quantity | whole | units to order today, in whole cases of 6 (0 = no order) |
| order_value | currency | quantity x latest price |
| days_of_cover | decimal | on-hand / mean daily forecast |
| stockout_risk | text | HIGH / MEDIUM / OVERSTOCK / OK |
| reorder_decision | text | REORDER or NO ACTION |

**policy_simulation**: `policy` (proposed, naive_ma28), `location` (ALL or a store) and `fill_rate` (decimal, shown as %) are used by the Fill Rate measures. Other columns are not used in visuals.

## 7. Reconciliation checklist

Open `reports/dashboard_reconciliation.md` and confirm each value with no slicer applied:

- [ ] Page 1: Total Units, Total Revenue and date range
- [ ] Page 2: selected model and its MAE, RMSE, WAPE
- [ ] Page 3: SKUs To Reorder, Recommended Units, Order Value, High Risk SKUs
- [ ] Page 3: units and order value for each location (click each location in the slicer)
- [ ] Page 3 shows the "Current inventory is SYNTHETIC" note
- [ ] The Streamlit app (`streamlit run app.py`) shows the same numbers

If a number differs, check data types (revenue as decimal), relationships (single direction, many-to-one) and that no slicer or page filter is active.
