"""Refit the selected model on all history to the as-of date and forecast the next 28 days. No inventory logic here."""
import pandas as pd

from src import config as C
from src import models as MD
from src.backtest import load_series

COLS = ["date", "sku", "location", "series_id", "actual_demand", "forecast_demand", "model_used", "forecast_type", "fold"]


def selected_model() -> str:
    comp = pd.read_csv(C.OUTPUT_DIR / "model_comparison.csv")
    return comp.loc[comp["selected"], "model"].iloc[0]


def future_forecasts(wide: pd.DataFrame, model: str) -> pd.DataFrame:
    """Fit on every observation <= AS_OF_DATE and forecast AS_OF_DATE + 1 .. + 28 days."""
    as_of = pd.Timestamp(C.AS_OF_DATE)
    wide = wide[wide.index <= as_of]
    dates = pd.date_range(as_of, periods=C.HORIZON + 1, freq="D")[1:]
    rows = []
    for sid in wide.columns:
        item, store = sid.split("__")
        rows.append(pd.DataFrame({"date": dates, "sku": item, "location": store, "series_id": sid,
                                  "actual_demand": float("nan"),
                                  "forecast_demand": MD.forecast_series(wide[sid], C.HORIZON, model),
                                  "model_used": model, "forecast_type": "future",
                                  "fold": pd.array([pd.NA] * C.HORIZON, dtype="Int64")}))
    return pd.concat(rows, ignore_index=True)


def weekly_demand(wide: pd.DataFrame) -> pd.DataFrame:
    """Weekly units (weeks start Monday) per sku/location, for reporting only."""
    long = wide.stack().rename("units").reset_index()
    long[["sku", "location"]] = long["series_id"].str.split("__", expand=True)
    long["week_start"] = long["date"].dt.to_period("W-SUN").dt.start_time
    return long.groupby(["week_start", "sku", "location"], as_index=False)["units"].sum()


def main() -> None:
    model = selected_model()
    wide = load_series()
    MD.reset_hw_stats()
    future = future_forecasts(wide, model)
    bt = pd.read_csv(C.OUTPUT_DIR / "backtest_forecasts.csv", parse_dates=["date"])
    bt = bt[bt["model"] == model].assign(model_used=model, forecast_type="backtest")
    out = pd.concat([bt[COLS], future[COLS]], ignore_index=True).sort_values(["series_id", "date"])
    out["fold"] = out["fold"].astype("Int64")
    out.to_csv(C.OUTPUT_DIR / "forecasts.csv", index=False)
    future[COLS].to_csv(C.OUTPUT_DIR / "forecast_next_28d.csv", index=False)
    weekly_demand(wide).to_csv(C.OUTPUT_DIR / "weekly_demand.csv", index=False)
    print(f"[forecast] model {model}: {len(bt):,} backtest rows + {len(future):,} future rows "
          f"({future['date'].min().date()} -> {future['date'].max().date()}); "
          f"holt_winters fallbacks in refit: {MD.HW_STATS['fallbacks']}")
    print(f"[forecast] next-28d total forecast units: {future['forecast_demand'].sum():,.0f}")


if __name__ == "__main__":
    main()
