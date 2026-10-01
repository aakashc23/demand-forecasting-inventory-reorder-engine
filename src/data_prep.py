"""Build a small raw extract of M5, then subset and clean it into the long-format sales table."""
import shutil
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from src import config as C

SALES_RAW = C.RAW_SUBSET_DIR / "sales_foods3_3stores.csv"
CALENDAR_RAW = C.RAW_SUBSET_DIR / "calendar.csv"
PRICES_RAW = C.RAW_SUBSET_DIR / "sell_prices_foods3_3stores.csv"
ID_COLS = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]


def _member(z: zipfile.ZipFile, name: str) -> str:
    """Find a file inside the zip even if the archive nests it in a folder."""
    return next(n for n in z.namelist() if Path(n).name == name)


def ensure_raw_extract() -> None:
    """Create the small immutable raw extract (FOODS_3 x 3 stores) by streaming out of the M5 zip."""
    if C.RAW_SUBSET_DIR.exists():
        print(f"[raw] extract already present at {C.RAW_SUBSET_DIR}, skipping download")
        return
    C.RAW_TMP_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = C.RAW_TMP_DIR / "m5.zip"
    print(f"[raw] downloading {C.M5_URL}")
    urllib.request.urlretrieve(C.M5_URL, zip_path)
    tmp_out = C.RAW_DIR / "_m5_subset_building"  # renamed on success, so a failed run leaves no partial extract
    shutil.rmtree(tmp_out, ignore_errors=True)
    tmp_out.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        with z.open(_member(z, "sales_train_evaluation.csv")) as f:  # wide sales: keep FOODS_3 rows of the stores
            first = True
            for chunk in pd.read_csv(f, dtype={c: str for c in ID_COLS}, chunksize=5000):
                keep = chunk[(chunk["dept_id"] == C.DEPT) & chunk["store_id"].isin(C.STORES)]
                keep.to_csv(tmp_out / SALES_RAW.name, mode="w" if first else "a", header=first, index=False)
                first = False
        items = set(pd.read_csv(tmp_out / SALES_RAW.name, usecols=["item_id"])["item_id"])
        (tmp_out / CALENDAR_RAW.name).write_bytes(z.read(_member(z, "calendar.csv")))  # byte-for-byte copy
        with z.open(_member(z, "sell_prices.csv")) as f:  # prices: same stores, FOODS_3 items only
            first = True
            for chunk in pd.read_csv(f, dtype={"store_id": str, "item_id": str}, chunksize=1_000_000):
                keep = chunk[chunk["store_id"].isin(C.STORES) & chunk["item_id"].isin(items)]
                keep.to_csv(tmp_out / PRICES_RAW.name, mode="w" if first else "a", header=first, index=False)
                first = False
    tmp_out.rename(C.RAW_SUBSET_DIR)
    shutil.rmtree(C.RAW_TMP_DIR)
    print(f"[raw] wrote extract to {C.RAW_SUBSET_DIR}; removed {C.RAW_TMP_DIR}")


def _load_wide_sales() -> pd.DataFrame:
    """Read the raw wide sales extract with compact dtypes."""
    day_cols = [c for c in pd.read_csv(SALES_RAW, nrows=0).columns if c.startswith("d_")]
    dtypes = {c: "int16" for c in day_cols} | {c: str for c in ID_COLS}
    wide = pd.read_csv(SALES_RAW, dtype=dtypes)
    return wide[(wide["dept_id"] == C.DEPT) & wide["store_id"].isin(C.STORES)].drop(columns="dept_id")


def load_long() -> pd.DataFrame:
    """Raw extract -> long table (item, store, date, units + calendar fields), restricted to the history window."""
    wide = _load_wide_sales()
    cal_cols = ["date", "wm_yr_wk", "event_name_1", "snap_CA", "snap_TX", "snap_WI"]
    cal = pd.read_csv(CALENDAR_RAW, usecols=cal_cols, parse_dates=["date"])
    cal["d"] = "d_" + (cal.index + 1).astype(str)  # the Nixtla calendar has no 'd' column; d_1 is row 1
    cal = cal[(cal["date"] >= C.HISTORY_START) & (cal["date"] <= C.AS_OF_DATE)]
    days = [d for d in cal["d"] if d in wide.columns]
    df = wide.melt(id_vars=["item_id", "store_id", "state_id"], value_vars=days, var_name="d", value_name="units")
    return df.merge(cal, on="d", how="inner").drop(columns="d")


def select_items(df: pd.DataFrame) -> tuple[pd.Index, dict[str, int]]:
    """Return (selected items, funnel counts). Rules use only data up to the first backtest origin."""
    origin = pd.Timestamp(C.BACKTEST_ORIGINS[0])
    window = df[(df["date"] > origin - pd.Timedelta(days=C.ELIGIBILITY_DAYS)) & (df["date"] <= origin)]
    zero_share = window.assign(zero=window["units"].eq(0)).groupby(["item_id", "store_id"])["zero"].mean()
    zero_ok = zero_share.groupby("item_id").max().le(C.MAX_ZERO_SHARE)  # must hold in EVERY store
    start = pd.Timestamp(C.HISTORY_START)
    early = df[df["date"] < start + pd.Timedelta(days=C.LAUNCH_CHECK_DAYS)]
    sold_early = early.groupby(["item_id", "store_id"])["units"].sum().gt(0)
    launch_ok = sold_early.groupby("item_id").all()  # listed from the start in EVERY store
    zero_pass = zero_ok[zero_ok].index
    eligible = zero_pass.intersection(launch_ok[launch_ok].index)
    top = window[window["item_id"].isin(eligible)].groupby("item_id")["units"].sum().nlargest(C.N_ITEMS).index
    funnel = {"items": df["item_id"].nunique(), "zero_rule": len(zero_pass),
              "launch_rule": len(eligible), "selected": len(top)}
    return top, funnel


def _flag_zero_runs(units: pd.Series, min_len: int) -> pd.Series:
    """True for days inside a run of >= min_len consecutive zero-sales days (series sorted by date)."""
    is_zero = units.eq(0)
    run_id = (is_zero != is_zero.shift()).cumsum()
    run_len = is_zero.groupby(run_id).transform("size")
    return is_zero & (run_len >= min_len)


def build_clean_sales() -> pd.DataFrame:
    """Build and save data/processed/sales_clean.csv from the raw extract."""
    df = load_long()
    top, f = select_items(df)
    print(f"[data] item funnel: {f['items']} FOODS_3 items -> {f['zero_rule']} pass zero-share rule -> "
          f"{f['launch_rule']} also pass launch rule -> {f['selected']} selected")
    df = df[df["item_id"].isin(top)].copy()

    # weekly sell price; fill gaps forward then backward within each series
    prices = pd.read_csv(PRICES_RAW, dtype={"store_id": str, "item_id": str})
    df = df.merge(prices, on=["store_id", "item_id", "wm_yr_wk"], how="left")
    df["series_id"] = df["item_id"] + "__" + df["store_id"]
    df = df.sort_values(["series_id", "date"]).reset_index(drop=True)
    df["sell_price"] = df.groupby("series_id")["sell_price"].transform(lambda s: s.ffill().bfill())

    # Christmas: impute with the same weekday one week earlier, and flag
    df["is_imputed"] = (df["date"].dt.month == 12) & (df["date"].dt.day == 25)
    lag7 = df.groupby("series_id")["units"].shift(7)
    df["units"] = df["units"].astype("float64").where(~df["is_imputed"], lag7).astype("int64")

    # likely stockouts: zero runs >= 7 days (flagged only, never imputed)
    df["likely_stockout"] = df.groupby("series_id")["units"].transform(
        lambda s: _flag_zero_runs(s, C.STOCKOUT_RUN_DAYS))

    # outliers: units > Q3 + 3*IQR within the series (flagged only, kept in the data)
    grp = df.groupby("series_id")["units"]
    q1, q3 = grp.transform(lambda s: s.quantile(0.25)), grp.transform(lambda s: s.quantile(0.75))
    df["is_outlier"] = df["units"] > q3 + C.OUTLIER_IQR_MULT * (q3 - q1)

    # SNAP flag for the row's own state
    df["snap"] = df["snap_CA"].where(df["state_id"] == "CA",
                                     df["snap_TX"].where(df["state_id"] == "TX", df["snap_WI"]))
    df["weekday"] = df["date"].dt.day_name()
    df["revenue"] = df["units"] * df["sell_price"]
    cols = ["date", "series_id", "item_id", "store_id", "state_id", "weekday", "units", "sell_price", "revenue",
            "is_imputed", "likely_stockout", "is_outlier", "event_name_1", "snap"]
    out = df[cols]
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(C.SALES_CLEAN_PATH, index=False)
    return out


def summarize(df: pd.DataFrame) -> None:
    """Print a concise data summary."""
    per_series = df.groupby("series_id")["units"].mean()
    so = df[df["likely_stockout"]]
    print(f"[data] series: {df['series_id'].nunique()} | "
          f"dates: {df['date'].min().date()} -> {df['date'].max().date()} | rows: {len(df):,}")
    print(f"[data] total units: {df['units'].sum():,} | imputed rows: {int(df['is_imputed'].sum())} | "
          f"outlier days (flagged, kept): {int(df['is_outlier'].sum()):,}")
    print(f"[data] likely-stockout days: {len(so):,} across {so['series_id'].nunique()} series")
    print(f"[data] zero-sales days: {(df['units'] == 0).mean():.1%}")
    print(f"[data] mean daily units per series: min {per_series.min():.2f} | "
          f"median {per_series.median():.2f} | max {per_series.max():.2f}")
    print(f"[data] saved {C.SALES_CLEAN_PATH}")


def main() -> pd.DataFrame:
    """Ensure the raw extract exists, clean, save, and summarize."""
    ensure_raw_extract()
    df = build_clean_sales()
    summarize(df)
    return df


if __name__ == "__main__":
    main()
