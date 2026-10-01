-- 02_views.sql : three clean analytical views over the fact/dimension tables. Portable (PostgreSQL + SQLite).

DROP VIEW IF EXISTS v_reorder_recommendations;
DROP VIEW IF EXISTS v_forecast_results;
DROP VIEW IF EXISTS v_sales_history;

-- Daily sales joined to the SKU/location dimension (year_month and weekday are stored columns).
CREATE VIEW v_sales_history AS
SELECT f.date,
       f.year_month,
       f.weekday,
       f.series_id,
       d.sku,
       d.location,
       d.state,
       f.units,
       f.revenue,
       f.is_imputed,
       f.likely_stockout,
       f.is_outlier
FROM fact_sales_daily f
JOIN dim_sku_location d ON d.series_id = f.series_id;

-- Selected-model forecasts with error = forecast - actual (positive = over-forecast); NULL where there is no actual (future rows).
CREATE VIEW v_forecast_results AS
SELECT f.date,
       f.series_id,
       d.sku,
       d.location,
       f.forecast_type,
       f.fold,
       f.model_used,
       f.actual_demand,
       f.forecast_demand,
       CASE WHEN f.actual_demand IS NOT NULL THEN f.forecast_demand - f.actual_demand END      AS error,
       CASE WHEN f.actual_demand IS NOT NULL THEN ABS(f.forecast_demand - f.actual_demand) END AS abs_error
FROM fact_forecast f
JOIN dim_sku_location d ON d.series_id = f.series_id;

-- The reorder list plus a priority rank (risk order, then fewest days of cover) and the gap to the reorder point.
-- inventory_gap > 0 means the inventory position is below the reorder point.
CREATE VIEW v_reorder_recommendations AS
SELECT r.*,
       ROW_NUMBER() OVER (
           ORDER BY CASE r.stockout_risk
                        WHEN 'HIGH'      THEN 1
                        WHEN 'MEDIUM'    THEN 2
                        WHEN 'OVERSTOCK' THEN 3
                        ELSE 4
                    END,
                    r.days_of_cover,
                    r.series_id
       ) AS priority_rank,
       r.reorder_point - r.inventory_position AS inventory_gap
FROM fact_reorder r;
