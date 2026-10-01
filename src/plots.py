"""Forecast figures for the README. Reads outputs/*.csv; nothing is re-fit here."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from src import config as C  # noqa: E402
from src import metrics as M  # noqa: E402

ACTUAL, FORECAST, FUTURE, MUTED = "#2b2b2b", "#2a6f97", "#e07a1f", "#b8b8b8"
CONTEXT_DAYS = 120


def _save(fig, name: str) -> None:
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / name, dpi=150)
    plt.close(fig)


def _mark_origins(ax) -> None:
    for i, origin in enumerate(C.BACKTEST_ORIGINS, start=1):
        ax.axvline(pd.Timestamp(origin), color=MUTED, ls="--", lw=1)
        ax.text(pd.Timestamp(origin), 1.01, f"fold {i}", transform=ax.get_xaxis_transform(), fontsize=8, color="#666")


def model_comparison_wape(comp: pd.DataFrame) -> None:
    comp = comp.iloc[::-1]  # simplest model at the top
    fig, ax = plt.subplots(figsize=(7, 3.8))
    bars = ax.barh(comp["model"], comp["WAPE"] * 100, color=[FORECAST if s else MUTED for s in comp["selected"]])
    ax.bar_label(bars, labels=[f"{w:.1%}" for w in comp["WAPE"]], padding=3)
    ax.set_xlim(0, comp["WAPE"].max() * 100 * 1.15)
    ax.set_xlabel("WAPE (%), all folds and series (lower is better)")
    ax.set_title("Backtest WAPE by model (selected model highlighted)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=FORECAST), plt.Rectangle((0, 0), 1, 1, color=MUTED)],
              labels=["selected", "other models"], loc="lower right")
    _save(fig, "model_comparison_wape.png")


def forecast_vs_actual_examples(fc: pd.DataFrame, sales: pd.DataFrame) -> None:
    top = sales.groupby(["store_id", "series_id"])["units"].sum().groupby("store_id").idxmax()
    fig, axes = plt.subplots(len(top), 1, figsize=(10, 3.2 * len(top)), sharex=True)
    start = pd.Timestamp(C.AS_OF_DATE) - pd.Timedelta(days=CONTEXT_DAYS - 1)
    bt = fc[fc["forecast_type"] == "backtest"]
    for ax, (store, (_, sid)) in zip(axes, top.items()):
        act = sales[(sales["series_id"] == sid) & (sales["date"] >= start)]
        ax.plot(act["date"], act["units"], color=ACTUAL, lw=1.2, label="actual")
        for fold, g in bt[bt["series_id"] == sid].groupby("fold"):
            ax.plot(g["date"], g["forecast_demand"], color=FORECAST, lw=1.6, label="backtest forecast" if fold == 1 else None)
        _mark_origins(ax)
        ax.set_title(f"{sid} (highest-volume series in {store})", loc="left", fontsize=10)
        ax.set_ylabel("units / day")
        ax.legend(loc="upper left", fontsize=8)
    axes[-1].set_xlabel("date")
    fig.suptitle(f"Selected model ({fc['model_used'].iloc[0]}): backtest forecasts vs actuals, last {CONTEXT_DAYS} days", y=1.0)
    _save(fig, "forecast_vs_actual_examples.png")


def forecast_vs_actual_total(fc: pd.DataFrame) -> None:
    tot = fc.groupby(["date", "forecast_type"])[["actual_demand", "forecast_demand"]].sum(min_count=1).reset_index()
    bt, fut = tot[tot["forecast_type"] == "backtest"], tot[tot["forecast_type"] == "future"]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(bt["date"], bt["actual_demand"], color=ACTUAL, lw=1.4, label="actual")
    ax.plot(bt["date"], bt["forecast_demand"], color=FORECAST, lw=1.6, label="backtest forecast")
    ax.plot(fut["date"], fut["forecast_demand"], color=FUTURE, lw=1.6, label="future forecast (next 28 days)")
    _mark_origins(ax)
    ax.axvline(pd.Timestamp(C.AS_OF_DATE), color=MUTED, ls=":", lw=1)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("date")
    ax.set_ylabel(f"units / day, summed over {fc['series_id'].nunique()} series")
    ax.set_title(f"Total demand: actual vs forecast ({fc['model_used'].iloc[0]})")
    ax.legend(loc="lower left")
    _save(fig, "forecast_vs_actual_total.png")


def error_by_location(fc: pd.DataFrame) -> None:
    bt = fc[fc["forecast_type"] == "backtest"]
    wape = bt.groupby("location").apply(lambda g: M.wape(g["actual_demand"], g["forecast_demand"]), include_groups=False)
    fig, ax = plt.subplots(figsize=(6, 3.8))
    bars = ax.bar(wape.index, wape * 100, color=FORECAST)
    ax.bar_label(bars, labels=[f"{w:.1%}" for w in wape], padding=3)
    ax.set_ylim(0, wape.max() * 100 * 1.2)
    ax.set_xlabel("store")
    ax.set_ylabel("WAPE (%)")
    ax.set_title(f"Backtest WAPE by store ({fc['model_used'].iloc[0]})")
    _save(fig, "error_by_location.png")


def main() -> None:
    comp = pd.read_csv(C.OUTPUT_DIR / "model_comparison.csv")
    fc = pd.read_csv(C.OUTPUT_DIR / "forecasts.csv", parse_dates=["date"])
    sales = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"], usecols=["date", "series_id", "store_id", "units"])
    model_comparison_wape(comp)
    forecast_vs_actual_examples(fc, sales)
    forecast_vs_actual_total(fc)
    error_by_location(fc)
    print(f"[plots] wrote 4 forecast figures to {C.FIGURES_DIR}")


if __name__ == "__main__":
    main()
