-- 01_schema.sql : tables for the reorder-engine analytical layer.
-- Portable SQL: runs unchanged on PostgreSQL / Supabase and SQLite.
-- Dates are ISO text (YYYY-MM-DD); flags are 0/1 integers. All numbers come from the Python pipeline outputs.
-- DOUBLE PRECISION is used instead of REAL so PostgreSQL keeps full 8-byte floats (SQLite treats it as REAL).

-- Views first, because PostgreSQL will not drop a table that a view depends on.
DROP VIEW IF EXISTS v_reorder_recommendations;
DROP VIEW IF EXISTS v_forecast_results;
DROP VIEW IF EXISTS v_sales_history;

DROP TABLE IF EXISTS fact_reorder;
DROP TABLE IF EXISTS fact_forecast;
DROP TABLE IF EXISTS fact_backtest;
DROP TABLE IF EXISTS fact_sales_daily;
DROP TABLE IF EXISTS dim_sku_location;

-- One row per SKU x location series (123 rows).
CREATE TABLE dim_sku_location (
    series_id    TEXT PRIMARY KEY,
    sku          TEXT NOT NULL,
    location     TEXT NOT NULL,
    state        TEXT NOT NULL,
    lead_time    INTEGER NOT NULL,            -- days, assumption from config.py (via reorder_list.csv)
    latest_price DOUBLE PRECISION NOT NULL    -- sell_price on the last observed day
);

-- Cleaned daily sales (source: data/processed/sales_clean.csv). year_month / weekday derived in Python.
CREATE TABLE fact_sales_daily (
    date            TEXT NOT NULL,
    series_id       TEXT NOT NULL,
    year_month      TEXT NOT NULL,            -- 'YYYY-MM'
    weekday         TEXT NOT NULL,
    units           INTEGER NOT NULL,
    revenue         DOUBLE PRECISION NOT NULL,
    is_imputed      INTEGER NOT NULL,
    likely_stockout INTEGER NOT NULL,
    is_outlier      INTEGER NOT NULL,
    PRIMARY KEY (date, series_id)
);

-- Rolling-origin backtest forecasts for ALL models (source: outputs/backtest_forecasts.csv).
CREATE TABLE fact_backtest (
    date            TEXT NOT NULL,
    fold            INTEGER NOT NULL,
    series_id       TEXT NOT NULL,
    model           TEXT NOT NULL,
    actual_demand   DOUBLE PRECISION NOT NULL,
    forecast_demand DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (date, series_id, model)
);

-- Selected-model forecasts: backtest rows (with actuals) and the 28-day future (source: outputs/forecasts.csv).
CREATE TABLE fact_forecast (
    date            TEXT NOT NULL,
    series_id       TEXT NOT NULL,
    actual_demand   DOUBLE PRECISION,         -- NULL for future rows
    forecast_demand DOUBLE PRECISION NOT NULL,
    model_used      TEXT NOT NULL,
    forecast_type   TEXT NOT NULL,            -- 'backtest' or 'future'
    fold            INTEGER,                  -- NULL for future rows
    PRIMARY KEY (date, series_id, forecast_type)
);

-- Today's reorder list, every column as produced by src/inventory.py (source: outputs/reorder_list.csv).
CREATE TABLE fact_reorder (
    date                       TEXT NOT NULL,
    sku                        TEXT NOT NULL,
    location                   TEXT NOT NULL,
    series_id                  TEXT PRIMARY KEY,
    current_inventory          INTEGER NOT NULL,
    inventory_position         INTEGER NOT NULL,
    forecast_demand            DOUBLE PRECISION NOT NULL,   -- lead-time demand
    forecast_daily_avg         DOUBLE PRECISION NOT NULL,
    lead_time                  INTEGER NOT NULL,
    demand_std                 DOUBLE PRECISION NOT NULL,
    service_level              DOUBLE PRECISION NOT NULL,
    z_value                    DOUBLE PRECISION NOT NULL,
    safety_stock               DOUBLE PRECISION NOT NULL,
    reorder_point              DOUBLE PRECISION NOT NULL,
    order_up_to                DOUBLE PRECISION NOT NULL,
    recommended_order_quantity INTEGER NOT NULL,
    order_value                DOUBLE PRECISION NOT NULL,
    days_of_cover              DOUBLE PRECISION NOT NULL,
    stockout_risk              TEXT NOT NULL,               -- HIGH / MEDIUM / OVERSTOCK / OK
    reorder_decision           TEXT NOT NULL                -- REORDER / NO ACTION
);
