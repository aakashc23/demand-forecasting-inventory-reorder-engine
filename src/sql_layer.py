"""SQL analytical layer: loads the pipeline outputs into SQLite, runs the portable SQL in sql/, reconciles with Python.

The SQL only aggregates. Forecasting and the safety-stock / reorder-point math stay in Python (single source of truth);
every SQL figure is checked against the Python outputs and the result is written to reports/sql_reconciliation.md.
"""
import math
import re
import sqlite3
from pathlib import Path

import pandas as pd

from src import config as C

SQL_DIR = C.ROOT / "sql"
DB_PATH = C.PROCESSED_DIR / "reorder_engine.db"
RESULTS_DIR = C.OUTPUT_DIR / "sql_results"
EXPORT_DIR = C.PROCESSED_DIR / "sql_load"          # table-shaped CSVs, ready for psql \copy
REPORT_PATH = C.ROOT / "reports" / "sql_reconciliation.md"
REL_TOL = 1e-6


def _connect(db_path: Path) -> sqlite3.Connection:
    """Fresh SQLite database (any old file is deleted). Registers SQRT if the bundled SQLite lacks it."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("SELECT SQRT(4)")
    except sqlite3.OperationalError:
        conn.create_function("SQRT", 1, math.sqrt)
    return conn


def build_tables() -> dict[str, pd.DataFrame]:
    """Table-shaped DataFrames (column order = schema). Only light reshaping; no business logic."""
    sales = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"])
    reorder = pd.read_csv(C.OUTPUT_DIR / "reorder_list.csv")
    last = sales.sort_values("date").groupby("series_id").tail(1).set_index("series_id")
    dim = (sales[["series_id", "item_id", "store_id", "state_id"]].drop_duplicates("series_id")
           .rename(columns={"item_id": "sku", "store_id": "location", "state_id": "state"})
           .merge(reorder[["series_id", "lead_time"]], on="series_id", how="left"))
    dim["latest_price"] = dim["series_id"].map(last["sell_price"])
    dim = dim.sort_values("series_id").reset_index(drop=True)

    fact_sales = pd.DataFrame({
        "date": sales["date"].dt.strftime("%Y-%m-%d"), "series_id": sales["series_id"],
        "year_month": sales["date"].dt.strftime("%Y-%m"), "weekday": sales["weekday"],
        "units": sales["units"], "revenue": sales["revenue"],
        "is_imputed": sales["is_imputed"].astype(int), "likely_stockout": sales["likely_stockout"].astype(int),
        "is_outlier": sales["is_outlier"].astype(int)})

    bt = pd.read_csv(C.OUTPUT_DIR / "backtest_forecasts.csv")
    fact_bt = bt[["date", "fold", "series_id", "model", "actual_demand", "forecast_demand"]]

    fc = pd.read_csv(C.OUTPUT_DIR / "forecasts.csv")
    fact_fc = fc[["date", "series_id", "actual_demand", "forecast_demand", "model_used", "forecast_type", "fold"]].copy()
    fact_fc["fold"] = fact_fc["fold"].astype("Int64")

    return {"dim_sku_location": dim, "fact_sales_daily": fact_sales, "fact_backtest": fact_bt,
            "fact_forecast": fact_fc, "fact_reorder": reorder}


def split_analyses(text: str) -> dict[str, str]:
    """Split 03_analysis.sql on '-- name: <snake_case>' marker lines."""
    parts = re.split(r"^--\s*name:\s*(\w+)\s*$", text, flags=re.MULTILINE)
    return {name: body.strip().rstrip(";").strip() for name, body in zip(parts[1::2], parts[2::2])}


def build_db(db_path: Path, export_dir: Path | None = None) -> sqlite3.Connection:
    """Create tables from 01_schema.sql, append the data, create the views from 02_views.sql."""
    conn = _connect(db_path)
    conn.executescript((SQL_DIR / "01_schema.sql").read_text(encoding="utf-8"))
    tables = build_tables()
    for name, df in tables.items():
        df.to_sql(name, conn, if_exists="append", index=False)
        if export_dir is not None:
            Path(export_dir).mkdir(parents=True, exist_ok=True)
            df.to_csv(Path(export_dir) / f"{name}.csv", index=False)
    conn.executescript((SQL_DIR / "02_views.sql").read_text(encoding="utf-8"))
    conn.commit()
    return conn


def run_analyses(conn: sqlite3.Connection, results_dir: Path) -> dict[str, pd.DataFrame]:
    """Run every named analysis and save outputs/sql_results/<name>.csv."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, sql in split_analyses((SQL_DIR / "03_analysis.sql").read_text(encoding="utf-8")).items():
        df = pd.read_sql_query(sql, conn)
        df.to_csv(results_dir / f"{name}.csv", index=False)
        results[name] = df
    return results


def reconcile(conn: sqlite3.Connection, res: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compare SQL results with the Python outputs. Counts must match exactly; other values within 1e-6 relative."""
    rows = []

    def check(name: str, sql_val, py_val, exact: bool = False) -> None:
        ok = (sql_val == py_val) if exact else math.isclose(float(sql_val), float(py_val), rel_tol=REL_TOL, abs_tol=1e-9)
        rows.append({"check": name, "sql_value": sql_val, "python_value": py_val, "status": "PASS" if ok else "FAIL"})

    def scalar(q: str):
        return conn.execute(q).fetchone()[0]

    sales = pd.read_csv(C.SALES_CLEAN_PATH)
    rl = pd.read_csv(C.OUTPUT_DIR / "reorder_list.csv")
    today = pd.read_csv(C.OUTPUT_DIR / "reorder_list_today.csv")
    mc = pd.read_csv(C.OUTPUT_DIR / "model_comparison.csv").set_index("model")
    fc = pd.read_csv(C.OUTPUT_DIR / "forecasts.csv")
    bt = pd.read_csv(C.OUTPUT_DIR / "backtest_forecasts.csv")
    stats = pd.read_csv(C.OUTPUT_DIR / "series_error_stats.csv").set_index("series_id")

    # Row counts (exact)
    for table, df in [("dim_sku_location", rl), ("fact_sales_daily", sales), ("fact_backtest", bt),
                      ("fact_forecast", fc), ("fact_reorder", rl)]:
        check(f"row count {table}", scalar(f"SELECT COUNT(*) FROM {table}"), len(df), exact=True)

    # Sales
    total_units = int(sales["units"].sum())
    check("total units (fact_sales_daily)", scalar("SELECT SUM(units) FROM fact_sales_daily"), total_units, exact=True)
    check("total revenue (fact_sales_daily)", scalar("SELECT SUM(revenue) FROM fact_sales_daily"), sales["revenue"].sum())
    check("total units (demand_by_sku)", int(res["demand_by_sku"]["total_units"].sum()), total_units, exact=True)
    check("total units (demand_by_location)", int(res["demand_by_location"]["total_units"].sum()), total_units, exact=True)
    check("total units (monthly_demand_trend)", int(res["monthly_demand_trend"]["total_units"].sum()), total_units, exact=True)
    check("SKUs ranked (demand_by_sku)", len(res["demand_by_sku"]), sales["item_id"].nunique(), exact=True)

    # Forecast accuracy by model vs model_comparison.csv
    acc = res["forecast_accuracy_by_model"].set_index("model")
    check("models in backtest", len(acc), len(mc), exact=True)
    for model in mc.index:
        for sql_col, py_col in [("mae", "MAE"), ("rmse", "RMSE"), ("wape", "WAPE"), ("bias", "Bias")]:
            check(f"{py_col} {model}", acc.loc[model, sql_col], mc.loc[model, py_col])
    selected = mc.index[mc["selected"]][0]
    check("selected model (is_selected)", acc.index[acc["is_selected"] == 1].tolist()[0], selected, exact=True)
    sel_rows = pd.read_sql_query("SELECT SUM(abs_error) AS ae, SUM(actual_demand) AS a FROM v_forecast_results "
                                 "WHERE forecast_type = 'backtest'", conn).iloc[0]
    check(f"WAPE {selected} via v_forecast_results", sel_rows["ae"] / sel_rows["a"], mc.loc[selected, "WAPE"])
    check("future rows without error (v_forecast_results)",
          scalar("SELECT COUNT(*) FROM v_forecast_results WHERE forecast_type = 'future' AND error IS NOT NULL"), 0, exact=True)

    # Per-series selected-model WAPE vs series_error_stats.csv
    perf = res["sku_location_performance"].set_index("series_id")
    check("series in sku_location_performance", len(perf), len(rl), exact=True)
    diff = (perf["selected_model_wape"] - stats["wape"].reindex(perf.index)).abs()
    check("series with WAPE differing from series_error_stats (>1e-6)", int((diff > REL_TOL).sum()), 0, exact=True)

    # Accuracy by location (selected model): pooled MAE weighted by observations = overall MAE
    loc = res["forecast_accuracy_by_location"]
    check("MAE selected model, n-weighted over locations",
          (loc["mae"] * loc["n_obs"]).sum() / loc["n_obs"].sum(), mc.loc[selected, "MAE"])

    # Reorder summary by location vs pandas groupby
    summ = res["reorder_summary_by_location"].set_index("location")
    g = rl.groupby("location").agg(series=("series_id", "count"),
                                   to_reorder=("recommended_order_quantity", lambda s: int((s > 0).sum())),
                                   units=("recommended_order_quantity", "sum"), order_value=("order_value", "sum"),
                                   high_risk=("stockout_risk", lambda s: int((s == "HIGH").sum())))
    for location in g.index:
        for col in ["series", "to_reorder", "units", "high_risk"]:
            check(f"{col} {location}", int(summ.loc[location, col]), int(g.loc[location, col]), exact=True)
        check(f"order_value {location}", summ.loc[location, "order_value"], g.loc[location, "order_value"])
    check("order_value total (reorder_summary_by_location)", summ["order_value"].sum(), rl["order_value"].sum())

    # Reorder list slices
    check("rows with qty > 0 vs reorder_list_today.csv", len(res["reorder_quantities_today"]), len(today), exact=True)
    check("units in reorder_quantities_today", int(res["reorder_quantities_today"]["recommended_order_quantity"].sum()),
          int(today["recommended_order_quantity"].sum()), exact=True)
    check("order value in reorder_quantities_today", res["reorder_quantities_today"]["order_value"].sum(),
          today["order_value"].sum())
    check("HIGH+MEDIUM rows (stockout_risk_skus)", len(res["stockout_risk_skus"]),
          int(rl["stockout_risk"].isin(["HIGH", "MEDIUM"]).sum()), exact=True)
    check("top 10 order value (top_inventory_requirements)", res["top_inventory_requirements"]["order_value"].sum(),
          rl["order_value"].nlargest(10).sum())
    check("sum of inventory_gap (v_reorder_recommendations)", scalar("SELECT SUM(inventory_gap) FROM v_reorder_recommendations"),
          (rl["reorder_point"] - rl["inventory_position"]).sum())
    check("distinct priority_rank values", scalar("SELECT COUNT(DISTINCT priority_rank) FROM v_reorder_recommendations"),
          len(rl), exact=True)
    check("priority_rank 1 stockout_risk", scalar("SELECT stockout_risk FROM v_reorder_recommendations WHERE priority_rank = 1"),
          rl["stockout_risk"].iloc[0], exact=True)
    return pd.DataFrame(rows)


def _fmt(v) -> str:
    return str(v) if isinstance(v, (int, str)) else f"{v:.10g}"


def write_report(checks: pd.DataFrame, report_path: Path) -> None:
    """reports/sql_reconciliation.md: check / SQL value / Python value / status, generated from the checks."""
    n_pass = int((checks["status"] == "PASS").sum())
    lines = ["# SQL reconciliation", "",
             "Every SQL result is checked against the Python outputs (counts exact, other values within "
             f"{REL_TOL:g} relative). Generated by `src/sql_layer.py`.", "",
             f"**{n_pass} / {len(checks)} checks passed.**", "",
             "| check | SQL value | Python value | status |", "|---|---|---|---|"]
    lines += [f"| {r.check} | {_fmt(r.sql_value)} | {_fmt(r.python_value)} | {r.status} |" for r in checks.itertuples()]
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(db_path: Path = DB_PATH, results_dir: Path = RESULTS_DIR, report_path: Path = REPORT_PATH,
         export_dir: Path | None = EXPORT_DIR) -> pd.DataFrame:
    """Build the DB, run the analyses, reconcile, write the report. Raises AssertionError if any check fails."""
    conn = build_db(db_path, export_dir)
    try:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ["dim_sku_location", "fact_sales_daily", "fact_backtest", "fact_forecast", "fact_reorder"]}
        res = run_analyses(conn, results_dir)
        checks = reconcile(conn, res)
    finally:
        conn.close()
    write_report(checks, report_path)
    failed = checks[checks["status"] != "PASS"]
    print(f"[sql] tables loaded: {counts}")
    print(f"[sql] {len(res)} analyses saved to {results_dir}")
    print(f"[sql] reconciliation: {len(checks) - len(failed)}/{len(checks)} checks passed -> {report_path}")
    assert failed.empty, f"SQL reconciliation failed:\n{failed.to_string(index=False)}"
    return checks


if __name__ == "__main__":
    main()
