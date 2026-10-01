"""Data profile: writes reports/data_profile.md and three figures. Every number is computed from the data."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config as C  # noqa: E402
from src import data_prep as D  # noqa: E402

REPORT_PATH = C.ROOT / "reports" / "data_profile.md"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COLORS = ["#2a6f97", "#e07a1f", "#4c9f70"]


def _fmt(x) -> str:
    """Format a table cell: ints with commas, floats to 2 decimals."""
    if isinstance(x, (bool, np.bool_)):
        return str(bool(x))
    if isinstance(x, (int, np.integer)):
        return f"{int(x):,}"
    if isinstance(x, (float, np.floating)):
        return f"{x:,.2f}"
    return str(x)


def md_table(df: pd.DataFrame, index_name: str = "") -> str:
    """Render a DataFrame as a markdown table."""
    cols = [index_name or (df.index.name or "")] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.astype(object).iterrows():  # object dtype keeps ints as ints
        lines.append("| " + " | ".join([str(idx)] + [_fmt(v) for v in row]) + " |")
    return "\n".join(lines)


def _pct(x: float) -> str:
    return f"{x:.1%}"


def load_raw() -> dict[str, pd.DataFrame]:
    """Load the three raw extract files unchanged."""
    return {"sales": pd.read_csv(D.SALES_RAW), "calendar": pd.read_csv(D.CALENDAR_RAW, parse_dates=["date"]),
            "prices": pd.read_csv(D.PRICES_RAW)}


def section_raw_inspection(raw: dict[str, pd.DataFrame]) -> list[str]:
    """1. Raw extract inspection."""
    rows = []
    for name, df in raw.items():
        dtypes = ", ".join(f"{n} {t}" for t, n in df.dtypes.astype(str).value_counts().items())
        rows.append({"file": name, "rows": len(df), "columns": df.shape[1], "dtypes (count by type)": dtypes})
    cal, sales = raw["calendar"], raw["sales"]
    n_days = sum(c.startswith("d_") for c in sales.columns)
    return ["## 1. Raw extract inspection", "",
            md_table(pd.DataFrame(rows).set_index("file")), "",
            f"- Calendar date range: {cal['date'].min().date()} -> {cal['date'].max().date()} ({len(cal):,} rows).",
            f"- Sales file has {n_days:,} daily columns (d_1 ... d_{n_days}); "
            f"d_{n_days} maps to {cal['date'].iloc[n_days - 1].date()}.",
            f"- SKUs (items) in the extract: {sales['item_id'].nunique():,}; stores: {sales['store_id'].nunique()} "
            f"({', '.join(sorted(sales['store_id'].unique()))}); departments: {', '.join(sales['dept_id'].unique())}.",
            f"- Wide sales rows (item x store series): {len(sales):,}.", ""]


def section_raw_quality(raw: dict[str, pd.DataFrame]) -> list[str]:
    """2. Raw data quality."""
    sales, cal, prices = raw["sales"], raw["calendar"], raw["prices"]
    day_cols = [c for c in sales.columns if c.startswith("d_")]
    vals = sales[day_cols].to_numpy()
    first_nz = (vals > 0).argmax(axis=1)
    never = ~(vals > 0).any(axis=1)
    leading = (first_nz > 0) & ~never
    lead_items = sales.loc[leading, "item_id"].nunique()
    missing = pd.DataFrame({f: raw[f].isna().sum() for f in raw}).fillna(0).astype(int)
    missing = missing[(missing > 0).any(axis=1)]
    date_gaps = cal["date"].diff().dropna().ne(pd.Timedelta(days=1)).sum()
    expected = pd.date_range(cal["date"].min(), cal["date"].max())
    sales_dates = cal["date"].iloc[: len(day_cols)]
    return ["## 2. Raw data quality (FOODS_3 x 3 stores, full history)", "",
            f"- Sales history: {sales_dates.min().date()} -> {sales_dates.max().date()} ({len(day_cols):,} days).",
            "- Missing values per file (only columns with any missing; in the calendar, missing event columns just mean "
            "'no event'):", "", md_table(missing, "column"), "",
            f"- Duplicate keys: sales (item_id, store_id) {sales.duplicated(['item_id', 'store_id']).sum():,}; "
            f"prices (store_id, item_id, wm_yr_wk) {prices.duplicated(['store_id', 'item_id', 'wm_yr_wk']).sum():,}.",
            f"- Negative sales values: {int((vals < 0).sum()):,}.",
            f"- Calendar continuity: {date_gaps} gaps between consecutive dates; "
            f"{len(expected) - cal['date'].nunique()} missing dates in the calendar range; "
            f"calendar has {len(cal):,} rows vs {len(day_cols):,} sales day columns "
            f"(the {len(cal) - len(day_cols)} extra calendar days are the M5 evaluation period, not in the sales file).",
            f"- Zero-sales share of all series-days: {_pct(float((vals == 0).mean()))}.",
            f"- Series with leading zeros (not yet launched on d_1): {int(leading.sum()):,} of {len(sales):,} "
            f"({lead_items:,} distinct items); series with no sales at all: {int(never.sum()):,}.",
            f"- Series with a leading zero run of 28+ days: {int((first_nz[leading] >= 28).sum()):,}; "
            f"median leading run among those with leading zeros: {float(pd.Series(first_nz[leading]).median()):.0f} days.", ""]


def section_funnel(long_df: pd.DataFrame) -> list[str]:
    """3. Selection funnel."""
    top, f = D.select_items(long_df)
    return ["## 3. Subset selection funnel", "",
            f"Rules (all evaluated only on data up to the first backtest origin, {C.BACKTEST_ORIGINS[0]}):", "",
            f"1. Scope: department {C.DEPT}, stores {', '.join(C.STORES)}, history {C.HISTORY_START} -> {C.AS_OF_DATE}.",
            f"2. Zero-share rule: in the {C.ELIGIBILITY_DAYS} days ending at the origin, zero-sales share <= "
            f"{C.MAX_ZERO_SHARE:.0%} in every store.",
            f"3. Launch rule: at least one sale within the first {C.LAUNCH_CHECK_DAYS} days of history in every store.",
            f"4. Take the top {C.N_ITEMS} remaining items by total units (all of them if fewer).", "",
            md_table(pd.DataFrame({"count": [f["items"], f["zero_rule"], f["launch_rule"], f["selected"],
                                             f["selected"] * len(C.STORES)]},
                                  index=[f"{C.DEPT} items in the extract", "pass zero-share rule",
                                         "also pass launch rule", f"selected (cap {C.N_ITEMS})",
                                         "SKU-location series"]), "stage"), ""]


def section_clean(df: pd.DataFrame) -> list[str]:
    """4. Clean dataset profile."""
    miss = df.isna().sum()
    miss = miss[miss > 0].rename("missing").to_frame()
    return ["## 4. Clean dataset profile (`data/processed/sales_clean.csv`)", "",
            f"- Rows: {len(df):,}; columns ({df.shape[1]}): {', '.join(df.columns)}.",
            f"- Series: {df['series_id'].nunique():,}; SKUs: {df['item_id'].nunique():,}; "
            f"locations: {df['store_id'].nunique()}.",
            f"- Date range: {df['date'].min().date()} -> {df['date'].max().date()} "
            f"({df['date'].nunique():,} days per series).",
            f"- Duplicates on (date, series_id): {int(df.duplicated(['date', 'series_id']).sum())}.",
            f"- Imputed rows (Dec 25): {int(df['is_imputed'].sum()):,}.",
            f"- Likely-stockout days: {int(df['likely_stockout'].sum()):,} across "
            f"{df.loc[df['likely_stockout'], 'series_id'].nunique()} series "
            f"({_pct(float(df['likely_stockout'].mean()))} of rows).",
            "- Missing values (event_name_1 is blank when there is no event):", "", md_table(miss, "column"), ""]


def section_distribution(df: pd.DataFrame) -> list[str]:
    """5. Sales distribution."""
    per_series = df.groupby("series_id")["units"].mean()
    q = per_series.quantile([0, 0.25, 0.5, 0.75, 1]).set_axis(["min", "p25", "median", "p75", "max"])
    dq = df["units"].quantile([0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1])
    dq.index = [f"p{int(i * 100)}" for i in dq.index]
    return ["## 5. Sales distribution", "",
            "Per-series mean daily units:", "", md_table(q.to_frame("units/day").T, ""), "",
            f"Daily units per series-day (mean {df['units'].mean():.2f}, zero share {_pct(float((df['units'] == 0).mean()))}):",
            "", md_table(dq.to_frame("units").T, ""), ""]


def section_seasonality(df: pd.DataFrame) -> list[str]:
    """6. Seasonality and SNAP."""
    by = df.groupby(["weekday", "store_id"])["units"].mean().unstack()
    dow = (by / df.groupby("store_id")["units"].mean()).reindex(WEEKDAYS)
    dow["ALL"] = df.groupby("weekday")["units"].mean().reindex(WEEKDAYS) / df["units"].mean()
    month = (df.groupby(df["date"].dt.month)["units"].mean() / df["units"].mean()).rename("index").to_frame()
    month.index.name = "month"
    snap = df.groupby(["store_id", "snap"])["units"].mean().unstack()
    snap.columns = ["non-SNAP mean units", "SNAP mean units"]
    snap["uplift"] = snap["SNAP mean units"] / snap["non-SNAP mean units"] - 1
    snap["SNAP days share"] = df.groupby("store_id")["snap"].mean()
    for c in ["uplift", "SNAP days share"]:
        snap[c] = snap[c].map(_pct)
    return ["## 6. Seasonality", "",
            "Day-of-week index (mean units on weekday / overall mean), per store:", "", md_table(dow, "weekday"), "",
            "Monthly index (mean units in calendar month / overall mean; the window is not a whole number of years, "
            "so months are unevenly covered):", "", md_table(month.T, ""), "",
            "SNAP vs non-SNAP days (mean units per series-day, not adjusted for weekday):", "", md_table(snap, "store"), ""]


def section_trend(df: pd.DataFrame) -> list[str]:
    """7. Trend: monthly totals and last-12 vs prior-12 months (52-week windows to align weekdays)."""
    month = df["date"].dt.to_period("M")
    tot = df.groupby(month)["units"].sum()
    days = df.groupby(month)["date"].nunique()
    table = pd.DataFrame({"days": days, "total units": tot, "units/day": tot / days})
    end = df["date"].max()
    last = df[df["date"] > end - pd.Timedelta(days=364)]
    prior = df[(df["date"] > end - pd.Timedelta(days=728)) & (df["date"] <= end - pd.Timedelta(days=364))]
    yoy = pd.DataFrame({"prior 52 wk": prior.groupby("store_id")["units"].sum(),
                        "last 52 wk": last.groupby("store_id")["units"].sum()})
    yoy.loc["ALL"] = [prior["units"].sum(), last["units"].sum()]
    yoy["change"] = (yoy["last 52 wk"] / yoy["prior 52 wk"] - 1).map(_pct)
    table.index = table.index.astype(str)
    return ["## 7. Trend", "", "Total units by year-month (first and last months are partial, see `days`):", "",
            md_table(table, "month"), "",
            f"Last 52 weeks ({last['date'].min().date()} -> {end.date()}) vs prior 52 weeks "
            f"({prior['date'].min().date()} -> {prior['date'].max().date()}):", "", md_table(yoy, "store"), ""]


def section_outliers(df: pd.DataFrame) -> list[str]:
    """8. Outliers (flagged, kept)."""
    out = df[df["is_outlier"]].copy()
    grp = df.groupby("series_id")["units"]
    q1, q3 = grp.quantile(0.25), grp.quantile(0.75)
    out["upper fence"] = out["series_id"].map(q3 + C.OUTLIER_IQR_MULT * (q3 - q1))
    per = out.groupby("series_id").size().sort_values(ascending=False).head(5).rename("outlier days").to_frame()
    top = out.sort_values(["units"], ascending=False).head(5)
    top = top.assign(date=top["date"].dt.date.astype(str), event=top["event_name_1"].fillna("none"))
    top = top[["date", "series_id", "units", "upper fence", "event"]].reset_index(drop=True)
    top.index = top.index + 1
    event_share_out = out["event_name_1"].notna().mean()
    event_share_all = df["event_name_1"].notna().mean()
    return ["## 8. Outliers", "",
            f"Rule: a day is an outlier if units > Q3 + {C.OUTLIER_IQR_MULT:g} x IQR, computed per series over the full "
            "history. Outliers are flagged (`is_outlier`) and kept, not removed or capped.", "",
            f"- Outlier days: {len(out):,} of {len(df):,} rows ({_pct(len(out) / len(df))}) across "
            f"{out['series_id'].nunique()} of {df['series_id'].nunique()} series.",
            f"- {_pct(float(event_share_out))} of outlier days fall on a calendar event day, vs "
            f"{_pct(float(event_share_all))} of all days.", "",
            "Series with the most outlier days:", "", md_table(per, "series"), "",
            "Top 5 outlier days by units:", "", md_table(top, "#"), "",
            "Decision: keep outliers. They are real demand spikes (often events/promotions) that a reorder policy "
            "must be able to see; they are only flagged.", ""]


def section_assumptions(df: pd.DataFrame) -> list[str]:
    """9. Assumptions and decisions."""
    return ["## 9. Assumptions & decisions", "",
            f"- Source: M5 (Walmart) from the public Nixtla mirror, {C.M5_URL}. Only a small raw extract is kept in "
            "`data/raw/m5_subset/` and is never modified.",
            f"- Filtering: department {C.DEPT}, stores {', '.join(C.STORES)}; history {C.HISTORY_START} -> {C.AS_OF_DATE}.",
            f"- Sampling: items must pass the zero-share rule (<= {C.MAX_ZERO_SHARE:.0%} zero days in every store over "
            f"{C.ELIGIBILITY_DAYS} days) and the launch rule (a sale within the first {C.LAUNCH_CHECK_DAYS} days in "
            f"every store); then the top {C.N_ITEMS} by units, ranked only on data up to {C.BACKTEST_ORIGINS[0]} "
            f"(no look-ahead). Result: {df['item_id'].nunique()} items, {df['series_id'].nunique()} series.",
            f"- Christmas (Dec 25): stores are closed; {int(df['is_imputed'].sum()):,} rows imputed with the same weekday "
            "one week earlier and flagged `is_imputed`.",
            f"- Stockouts: zero-sales runs of {C.STOCKOUT_RUN_DAYS}+ days are flagged `likely_stockout` "
            f"({int(df['likely_stockout'].sum()):,} days) and not imputed; sales are censored demand, so sales != true demand.",
            f"- Outliers: units > Q3 + {C.OUTLIER_IQR_MULT:g} x IQR per series are flagged `is_outlier` "
            f"({int(df['is_outlier'].sum()):,} days) and kept.",
            "- Missing sell prices are forward- then back-filled within each series.", ""]


def make_figures(df: pd.DataFrame) -> None:
    """Save the three profile figures to reports/figures/."""
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.alpha": 0.3, "font.size": 10})
    daily = df.groupby("date")["units"].sum()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(daily.index, daily.values, color=COLORS[0], alpha=0.35, lw=0.8, label="daily total")
    ax.plot(daily.index, daily.rolling(28).mean(), color=COLORS[1], lw=2, label="28-day rolling mean")
    ax.set(title="Total daily units across all series", xlabel="Date", ylabel="Units per day")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / "daily_units.png", dpi=150)
    plt.close(fig)

    dow = (df.groupby(["weekday", "store_id"])["units"].mean().unstack()
           / df.groupby("store_id")["units"].mean()).reindex(WEEKDAYS)
    fig, ax = plt.subplots(figsize=(10, 4))
    dow.plot.bar(ax=ax, color=COLORS[: dow.shape[1]], width=0.8)
    ax.axhline(1, color="grey", lw=1, ls="--")
    ax.set(title="Day-of-week seasonality index by store (1.0 = store average)", xlabel="Weekday",
           ylabel="Index")
    ax.set_xticklabels([d[:3] for d in WEEKDAYS], rotation=0)
    ax.legend(title="Store", frameon=False)
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / "weekday_seasonality.png", dpi=150)
    plt.close(fig)

    cap = df["units"].quantile(0.99)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.hist(df["units"].clip(upper=cap), bins=int(cap) + 1, color=COLORS[0])
    ax.set_yscale("log")
    ax.set(title=f"Distribution of daily units per series (values above the 99th percentile, {cap:.0f}, are clipped)",
           xlabel="Units sold per day", ylabel="Series-days (log scale)")
    fig.tight_layout()
    fig.savefig(C.FIGURES_DIR / "units_distribution.png", dpi=150)
    plt.close(fig)


def main() -> None:
    """Build the data profile report and figures from the raw extract and the clean table."""
    raw = load_raw()
    df = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"])
    long_df = D.load_long()
    lines = ["# Data profile", "",
             "_Generated by `src/eda.py`; every number below is computed from the data when the pipeline runs._", ""]
    for part in (section_raw_inspection(raw), section_raw_quality(raw), section_funnel(long_df),
                 section_clean(df), section_distribution(df), section_seasonality(df), section_trend(df),
                 section_outliers(df), section_assumptions(df)):
        lines += part
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    make_figures(df)
    print(f"[eda] wrote {REPORT_PATH} and 3 figures to {C.FIGURES_DIR}")


if __name__ == "__main__":
    main()
