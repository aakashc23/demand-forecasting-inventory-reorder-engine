"""Rolling-origin backtest: every series x fold x model, trained only on data <= the fold origin."""
import numpy as np
import pandas as pd

from src import config as C
from src import metrics as M
from src import models as MD


def load_series() -> pd.DataFrame:
    """Wide table: rows = dates, columns = series_id, values = units."""
    df = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"])
    return df.pivot(index="date", columns="series_id", values="units").astype(float)


def split_at_origin(y: pd.Series, origin, horizon: int) -> tuple[pd.Series, pd.Series]:
    """Train = data <= origin; test = the next `horizon` days. No data after the origin reaches the train set."""
    origin = pd.Timestamp(origin)
    return y[y.index <= origin], y[y.index > origin].iloc[:horizon]


def run_backtest(wide: pd.DataFrame) -> pd.DataFrame:
    """Long table of forecasts for all series x folds x models, plus the training scale used for MASE."""
    rows = []
    for sid in wide.columns:
        item, store = sid.split("__")
        for fold, origin in enumerate(C.BACKTEST_ORIGINS, start=1):
            train, test = split_at_origin(wide[sid], origin, C.HORIZON)
            t = train.to_numpy()
            scale = float(np.mean(np.abs(t[7:] - t[:-7])))  # in-sample seasonal-naive (lag-7) MAE
            for name in MD.MODELS:
                rows.append(pd.DataFrame({
                    "date": test.index, "fold": fold, "series_id": sid, "sku": item, "location": store,
                    "model": name, "actual_demand": test.to_numpy(),
                    "forecast_demand": MD.forecast_series(train, C.HORIZON, name), "mase_scale": scale}))
    out = pd.concat(rows, ignore_index=True)
    out["error"] = out["forecast_demand"] - out["actual_demand"]
    out["abs_error"] = out["error"].abs()
    return out


def _agg(g: pd.DataFrame) -> pd.Series:
    a, f = g["actual_demand"], g["forecast_demand"]
    return pd.Series({"MAE": M.mae(a, f), "RMSE": M.rmse(a, f), "WAPE": M.wape(a, f), "Bias": M.bias(a, f)})


def compare_models(bt: pd.DataFrame) -> pd.DataFrame:
    """One row per model: pooled metrics, per-series WAPE wins, and the parsimony-based `selected` flag."""
    table = bt.groupby("model").apply(_agg, include_groups=False).loc[list(MD.MODELS)]
    sf = bt.groupby(["model", "series_id", "fold"]).apply(
        lambda g: M.mae(g["actual_demand"], g["forecast_demand"]) / g["mase_scale"].iloc[0], include_groups=False)
    table["MASE"] = sf.groupby("model").mean()
    table["mape_nonzero"] = bt[bt["actual_demand"] > 0].groupby("model").apply(
        lambda g: M.mape_nonzero(g["actual_demand"], g["forecast_demand"]), include_groups=False)
    series_wape = bt.groupby(["series_id", "model"]).apply(
        lambda g: M.wape(g["actual_demand"], g["forecast_demand"]), include_groups=False).unstack()
    table["wins"] = series_wape.idxmin(axis=1).value_counts().reindex(table.index).fillna(0).astype(int)
    best = table["WAPE"].min()
    ok = table.index[table["WAPE"] <= best + C.SELECTION_TOLERANCE_PP / 100]  # MODELS order = simplest first
    table["selected"] = table.index == ok[0]
    return table.reset_index()


def selection_reason(table: pd.DataFrame) -> str:
    best = table.loc[table["WAPE"].idxmin()]
    sel = table.loc[table["selected"]].iloc[0]
    if sel["model"] == best["model"]:
        return f"{sel['model']} has the lowest overall WAPE ({sel['WAPE']:.2%}) and no simpler model is within tolerance."
    gap = (sel["WAPE"] - best["WAPE"]) * 100
    return (f"best WAPE is {best['model']} ({best['WAPE']:.2%}); {sel['model']} ({sel['WAPE']:.2%}) is {gap:.2f} pp worse, "
            f"within the {C.SELECTION_TOLERANCE_PP:.1f} pp tolerance, and is the simplest such model.")


def series_error_stats(bt: pd.DataFrame, model: str) -> pd.DataFrame:
    """Per-series error stats of the selected model. rmse_folds_1_2 excludes fold 3 (leak-free for the fold-3 simulation)."""
    rows = []
    for sid, g in bt[bt["model"] == model].groupby("series_id"):
        a, f = g["actual_demand"], g["forecast_demand"]
        g12 = g[g["fold"] <= 2]
        rows.append({"series_id": sid, "sku": g["sku"].iloc[0], "location": g["location"].iloc[0],
                     "mae": M.mae(a, f), "rmse_all_folds": M.rmse(a, f),
                     "rmse_folds_1_2": M.rmse(g12["actual_demand"], g12["forecast_demand"]),
                     "wape": M.wape(a, f), "bias": M.bias(a, f), "n_days": len(g)})
    return pd.DataFrame(rows)


def main() -> None:
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wide = load_series()
    MD.reset_hw_stats()
    bt = run_backtest(wide)
    cols = ["date", "fold", "series_id", "sku", "location", "model", "actual_demand", "forecast_demand", "error", "abs_error"]
    bt[cols].to_csv(C.OUTPUT_DIR / "backtest_forecasts.csv", index=False)

    table = compare_models(bt)
    table.to_csv(C.OUTPUT_DIR / "model_comparison.csv", index=False)
    by_fold = bt.groupby(["model", "fold"]).apply(_agg, include_groups=False).reset_index()
    by_fold["model"] = pd.Categorical(by_fold["model"], list(MD.MODELS))
    by_fold.sort_values(["model", "fold"]).to_csv(C.OUTPUT_DIR / "model_metrics_by_fold.csv", index=False)
    selected = table.loc[table["selected"], "model"].iloc[0]
    series_error_stats(bt, selected).to_csv(C.OUTPUT_DIR / "series_error_stats.csv", index=False)

    print(f"[backtest] {wide.shape[1]} series x {len(C.BACKTEST_ORIGINS)} folds x {len(MD.MODELS)} models, horizon {C.HORIZON}")
    print(table.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"[backtest] selected: {selected} - {selection_reason(table)}")
    print(f"[backtest] holt_winters fallbacks: {MD.HW_STATS['fallbacks']} | "
          f"convergence warnings: {MD.HW_STATS['convergence_warnings']}")


if __name__ == "__main__":
    main()
