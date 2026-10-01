-- 03_analysis.sql : named business analyses. The runner (src/sql_layer.py) splits on the "-- name:" lines,
-- runs each statement and saves outputs/sql_results/<name>.csv. Portable (PostgreSQL + SQLite).
-- Aggregations only: forecasting and the safety-stock / reorder-point math stay in Python.

-- name: demand_by_sku
-- Q: Which SKUs drive the most demand and revenue across all three stores?
SELECT sku,
       SUM(units)                               AS total_units,
       SUM(units) * 1.0 / COUNT(DISTINCT date)  AS avg_daily_units,
       SUM(revenue)                             AS revenue,
       RANK() OVER (ORDER BY SUM(units) DESC)   AS demand_rank
FROM v_sales_history
GROUP BY sku
ORDER BY demand_rank, sku;

-- name: demand_by_location
-- Q: How is demand and revenue split across the three store locations?
SELECT location,
       state,
       COUNT(DISTINCT sku)                                   AS n_skus,
       SUM(units)                                            AS total_units,
       SUM(units) * 1.0 / COUNT(DISTINCT date)               AS avg_daily_units,
       SUM(revenue)                                          AS revenue,
       SUM(units) * 1.0 / SUM(SUM(units)) OVER ()            AS share_of_units
FROM v_sales_history
GROUP BY location, state
ORDER BY total_units DESC;

-- name: monthly_demand_trend
-- Q: How is total demand trending month to month (first and last months are partial, so compare avg daily units)?
WITH m AS (
    SELECT year_month,
           SUM(units)                               AS total_units,
           SUM(revenue)                             AS revenue,
           COUNT(DISTINCT date)                     AS days_in_data,
           SUM(units) * 1.0 / COUNT(DISTINCT date)  AS avg_daily_units
    FROM v_sales_history
    GROUP BY year_month
)
SELECT year_month,
       total_units,
       revenue,
       days_in_data,
       avg_daily_units,
       avg_daily_units / LAG(avg_daily_units) OVER (ORDER BY year_month) - 1 AS mom_change_avg_daily
FROM m
ORDER BY year_month;

-- name: forecast_accuracy_by_model
-- Q: Which forecasting model is most accurate over the rolling-origin backtest (pooled over all folds and series)?
WITH e AS (
    SELECT model,
           actual_demand                       AS actual,
           forecast_demand - actual_demand     AS err
    FROM fact_backtest
)
SELECT model,
       COUNT(*)                                                              AS n_obs,
       AVG(ABS(err))                                                         AS mae,
       SQRT(AVG(err * err))                                                  AS rmse,
       SUM(ABS(err)) * 1.0 / NULLIF(SUM(actual), 0)                          AS wape,
       SUM(err) * 1.0 / NULLIF(SUM(actual), 0)                               AS bias,
       CASE WHEN model IN (SELECT model_used FROM fact_forecast) THEN 1 ELSE 0 END AS is_selected
FROM e
GROUP BY model
ORDER BY wape;

-- name: forecast_accuracy_by_location
-- Q: Does the selected model forecast some store locations worse than others?
WITH sel AS (
    SELECT DISTINCT model_used AS model FROM fact_forecast WHERE forecast_type = 'backtest'
),
e AS (
    SELECT d.location,
           sel.model,
           b.actual_demand                     AS actual,
           b.forecast_demand - b.actual_demand AS err
    FROM fact_backtest b
    JOIN sel ON sel.model = b.model
    JOIN dim_sku_location d ON d.series_id = b.series_id
)
SELECT location,
       model,
       COUNT(*)                                       AS n_obs,
       AVG(ABS(err))                                  AS mae,
       SQRT(AVG(err * err))                           AS rmse,
       SUM(ABS(err)) * 1.0 / NULLIF(SUM(actual), 0)   AS wape,
       SUM(err) * 1.0 / NULLIF(SUM(actual), 0)        AS bias
FROM e
GROUP BY location, model
ORDER BY wape;

-- name: stockout_risk_skus
-- Q: Which SKU/locations are at HIGH or MEDIUM stockout risk, most urgent first?
SELECT priority_rank,
       sku,
       location,
       stockout_risk,
       current_inventory,
       forecast_demand AS lead_time_demand,
       reorder_point,
       inventory_gap,
       lead_time,
       days_of_cover,
       recommended_order_quantity,
       order_value
FROM v_reorder_recommendations
WHERE stockout_risk IN ('HIGH', 'MEDIUM')
ORDER BY priority_rank;

-- name: reorder_quantities_today
-- Q: What exactly should we order today, in priority order?
SELECT priority_rank,
       sku,
       location,
       stockout_risk,
       current_inventory,
       reorder_point,
       order_up_to,
       recommended_order_quantity,
       order_value,
       days_of_cover
FROM v_reorder_recommendations
WHERE recommended_order_quantity > 0
ORDER BY priority_rank;

-- name: top_inventory_requirements
-- Q: Which 10 orders tie up the most money today?
SELECT sku,
       location,
       stockout_risk,
       recommended_order_quantity,
       order_value,
       priority_rank
FROM v_reorder_recommendations
ORDER BY order_value DESC, series_id
LIMIT 10;

-- name: reorder_summary_by_location
-- Q: How much do we need to order per location, and how many of those lines are high risk?
SELECT location,
       COUNT(*)                                                         AS series,
       SUM(CASE WHEN recommended_order_quantity > 0 THEN 1 ELSE 0 END)  AS to_reorder,
       SUM(recommended_order_quantity)                                  AS units,
       SUM(order_value)                                                 AS order_value,
       SUM(CASE WHEN stockout_risk = 'HIGH' THEN 1 ELSE 0 END)          AS high_risk
FROM v_reorder_recommendations
GROUP BY location
ORDER BY location;

-- name: sku_location_performance
-- Q: For each SKU/location, how big is demand, how accurate is the forecast, and how risky is the stock position?
WITH sel AS (
    SELECT DISTINCT model_used AS model FROM fact_forecast WHERE forecast_type = 'backtest'
),
u AS (
    SELECT series_id, SUM(units) AS total_units
    FROM fact_sales_daily
    GROUP BY series_id
),
w AS (
    SELECT b.series_id,
           SUM(ABS(b.forecast_demand - b.actual_demand)) * 1.0 / NULLIF(SUM(b.actual_demand), 0) AS selected_model_wape
    FROM fact_backtest b
    JOIN sel ON sel.model = b.model
    GROUP BY b.series_id
)
SELECT d.series_id,
       d.sku,
       d.location,
       u.total_units,
       w.selected_model_wape,
       r.stockout_risk AS risk_flag,
       r.days_of_cover
FROM dim_sku_location d
JOIN u ON u.series_id = d.series_id
LEFT JOIN w ON w.series_id = d.series_id
JOIN fact_reorder r ON r.series_id = d.series_id
ORDER BY u.total_units DESC, d.series_id;
