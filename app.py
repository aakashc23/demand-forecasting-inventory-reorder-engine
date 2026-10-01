"""Streamlit demo: the same 3 pages as the Power BI report. Reads only committed CSVs in outputs/ and outputs/powerbi/."""
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # so `src` imports work when run from any directory (Streamlit Cloud runs from the repo root)

from src import config as C  # noqa: E402
from src import inventory as I  # noqa: E402
from src import whatif as W  # noqa: E402

OUT, PBI = ROOT / "outputs", ROOT / "outputs" / "powerbi"
PAGES = ["1. Demand Overview", "2. Forecast Performance", "3. Inventory Reorder Engine"]
BLUE, GREY = "#2563EB", "#6B7280"
RISK_COLORS = {"HIGH": "#FECACA", "MEDIUM": "#FED7AA", "OVERSTOCK": "#BFDBFE", "OK": "#BBF7D0"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
REORDER_COLS = ["sku", "location", "stockout_risk", "recommended_order_quantity", "current_inventory", "forecast_demand",
                "safety_stock", "reorder_point", "order_up_to", "order_value", "days_of_cover"]

st.set_page_config(page_title="Demand Forecasting & Inventory Reorder Engine", layout="wide")


# ---------- data ----------
@st.cache_data
def load(name: str, folder: str = "powerbi") -> pd.DataFrame:
    return pd.read_csv((PBI if folder == "powerbi" else OUT) / name)


@st.cache_data
def sales_with_dims() -> pd.DataFrame:
    s = load("fact_sales_daily.csv").merge(load("dim_sku_location.csv")[["series_id", "sku", "location"]], on="series_id")
    d = load("dim_date.csv")[["date", "year_month", "week_start", "weekday"]]
    s = s.merge(d, on="date")
    s["date"] = pd.to_datetime(s["date"])
    return s


def bar(df: pd.DataFrame, cat: str, val: str, horizontal: bool = False, sort=None, fmt: str = ",.0f", title: str = "") -> alt.Chart:
    """Single-colour bar chart: category column `cat`, value column `val`."""
    c, v = alt.X(f"{cat}:N", sort=sort, title=None), alt.Y(f"{val}:Q", title=title)
    if horizontal:
        c, v = alt.Y(f"{cat}:N", sort=sort, title=None), alt.X(f"{val}:Q", title=title)
    tip = [cat, alt.Tooltip(f"{val}:Q", format=fmt)]
    return alt.Chart(df).mark_bar(color=BLUE).encode(x=v if horizontal else c, y=c if horizontal else v, tooltip=tip)


def styled_risk(df: pd.DataFrame, formats: dict):
    return df.style.map(lambda v: f"background-color: {RISK_COLORS.get(v, '')}", subset=["stockout_risk"]).format(formats)


# ---------- page 1 ----------
def page_demand() -> None:
    st.header("Demand Overview")
    st.caption("Question: how much do we sell, where, and when?")
    s = sales_with_dims()
    locs = st.multiselect("Location", sorted(s["location"].unique()), default=sorted(s["location"].unique()))
    s = s[s["location"].isin(locs)]
    if s.empty:
        st.info("Select at least one location.")
        return
    days = s["date"].nunique()
    c = st.columns(4)
    c[0].metric("Total units", f"{int(s['units'].sum()):,}")
    c[1].metric("Total revenue", f"${s['revenue'].sum():,.2f}")
    c[2].metric("Avg daily units", f"{s['units'].sum() / days:,.0f}")
    c[3].metric("Date range", f"{s['date'].min():%Y-%m-%d} to {s['date'].max():%Y-%m-%d}")

    grain = st.radio("Trend grain", ["Monthly", "Weekly"], horizontal=True)
    key = "year_month" if grain == "Monthly" else "week_start"
    trend = s.groupby(key, as_index=False)["units"].sum()
    st.subheader(f"{grain} demand")
    chart = alt.Chart(trend).mark_line(color=BLUE, point=grain == "Monthly").encode(
        x=alt.X(f"{key}:{'O' if grain == 'Monthly' else 'T'}", title=None), y=alt.Y("units:Q", title="Units"),
        tooltip=[key, alt.Tooltip("units:Q", format=",.0f")])
    st.altair_chart(chart, width="stretch")
    st.caption("The first and last periods are partial (history runs 2014-05-22 to 2016-05-22).")

    a, b = st.columns(2)
    with a:
        st.subheader("Top 10 SKUs by units")
        top = s.groupby("sku", as_index=False)["units"].sum().nlargest(10, "units")
        st.altair_chart(bar(top, "sku", "units", horizontal=True, sort="-x", title="Units"), width="stretch")
    with b:
        st.subheader("Demand by location")
        by_loc = s.groupby("location", as_index=False)["units"].sum()
        st.altair_chart(bar(by_loc, "location", "units", sort="-y", title="Units"), width="stretch")

    st.subheader("Weekday seasonality (average units per day)")
    wd = s.groupby("weekday")["units"].sum() / s.groupby("weekday")["date"].nunique()
    wd = wd.rename("avg_daily_units").reset_index()
    st.altair_chart(bar(wd, "weekday", "avg_daily_units", sort=WEEKDAYS, fmt=",.1f", title="Avg units per day"), width="stretch")


# ---------- page 2 ----------
def page_forecast() -> None:
    st.header("Forecast Performance")
    st.caption("Question: how accurate is the forecast, and where is it weakest? Errors: error = forecast - actual.")
    mc = load("model_comparison.csv")
    sel = mc[mc["selected"]].iloc[0]
    c = st.columns(4)
    c[0].metric("Selected model", sel["model"])
    c[1].metric("MAE", f"{sel['MAE']:.3f}")
    c[2].metric("RMSE", f"{sel['RMSE']:.3f}")
    c[3].metric("WAPE", f"{sel['WAPE']:.1%}")

    st.subheader("Model comparison (3-fold rolling-origin backtest, all series)")
    show = mc[["model", "MAE", "RMSE", "WAPE", "Bias", "MASE", "wins", "selected"]]
    hi = lambda r: ["background-color: #DBEAFE; font-weight: 600" if r["selected"] else "" for _ in r]  # noqa: E731
    st.dataframe(show.style.apply(hi, axis=1).format({"MAE": "{:.3f}", "RMSE": "{:.3f}", "WAPE": "{:.1%}", "Bias": "{:+.1%}", "MASE": "{:.3f}"}),
                 hide_index=True, width="stretch")
    st.caption(f"Selection rule: pick the simplest model whose WAPE is within {C.SELECTION_TOLERANCE_PP:g} percentage point of the best "
               "(naive < seasonal_naive < moving_average < seasonal_ma < holt_winters). `wins` = series where the model has the lowest WAPE.")

    st.subheader("Actual vs forecast for one series")
    dim, ff = load("dim_sku_location.csv"), load("fact_forecast.csv")
    sales = sales_with_dims()
    by_volume = sales.groupby("series_id")["units"].sum().sort_values(ascending=False).index.tolist()
    sid = st.selectbox("Series (SKU at location), highest volume first", by_volume)
    act = sales[(sales["series_id"] == sid) & (sales["date"] >= "2016-01-01")][["date", "units"]]
    f = ff[ff["series_id"] == sid].copy()
    f["date"] = pd.to_datetime(f["date"])
    f["period"] = f.apply(lambda r: "Future 28d" if r["forecast_type"] == "future" else f"Fold {int(r['fold'])}", axis=1)
    order = ["Fold 1", "Fold 2", "Fold 3", "Future 28d"]
    line_actual = alt.Chart(act).mark_line(color="#111827").encode(x=alt.X("date:T", title=None), y=alt.Y("units:Q", title="Units"),
                                                                    tooltip=["date:T", "units:Q"])
    line_fc = alt.Chart(f).mark_line().encode(
        x="date:T", y="forecast_demand:Q",
        color=alt.Color("period:N", scale=alt.Scale(domain=order, range=["#2563EB", "#0891B2", "#7C3AED", "#EA580C"]), title="Forecast"),
        tooltip=["date:T", "period:N", alt.Tooltip("forecast_demand:Q", format=".2f")])
    st.altair_chart(line_actual + line_fc, width="stretch")
    st.caption("Black = actual units (from 2016-01-01). Coloured = the selected model's forecast: one colour per backtest fold, "
               "then the 28-day future forecast.")

    a, b = st.columns(2)
    bt = ff[ff["forecast_type"] == "backtest"].merge(dim[["series_id", "location"]], on="series_id")
    with a:
        st.subheader("WAPE by location")
        g = bt.groupby("location").agg(abs_error=("abs_error", "sum"), actual=("actual_demand", "sum"))
        wl = (g["abs_error"] / g["actual"]).rename("WAPE").reset_index()
        st.altair_chart(bar(wl, "location", "WAPE", fmt=".1%", title="WAPE"), width="stretch")
    with b:
        st.subheader("Per-series error")
        err = load("series_error_stats.csv", "outputs")
        locs = st.multiselect("Location", sorted(err["location"].unique()), default=sorted(err["location"].unique()), key="err_loc")
        t = err[err["location"].isin(locs)][["sku", "location", "mae", "rmse_all_folds", "wape", "bias"]].sort_values("wape", ascending=False)
        st.dataframe(t.style.format({"mae": "{:.2f}", "rmse_all_folds": "{:.2f}", "wape": "{:.1%}", "bias": "{:+.2f}"}),
                     hide_index=True, width="stretch", height=300)
        st.caption("Sorted by WAPE, worst first. Bias is the mean daily error in units (positive = over-forecast).")


# ---------- page 3 ----------
def worked_example(rl: pd.DataFrame) -> None:
    with st.expander("How the decision is made (worked example)"):
        st.markdown(
            "1. **Lead-time demand** = forecast units over the lead time.  \n"
            "2. **Safety stock** = Z x sigma x sqrt(lead time); sigma = the model's backtest RMSE for that series.  \n"
            "3. **Reorder point (ROP)** = lead-time demand + safety stock.  \n"
            f"4. **Order-up-to** = ROP + {C.ORDER_CYCLE_DAYS} days of forecast demand.  \n"
            f"5. If inventory position <= ROP, **order quantity** = order-up-to minus position, rounded up to whole cases of {C.CASE_PACK}.  \n"
            f"6. **Risk**: HIGH = on-hand below lead-time demand; MEDIUM = at or below ROP; OVERSTOCK = over {C.OVERSTOCK_DAYS} days of cover; OK otherwise.")
        sid = st.selectbox("Series", rl["series_id"].tolist(), key="example_series")
        st.markdown(I._example(rl[rl["series_id"] == sid].iloc[0]))


def what_if(base: pd.DataFrame) -> None:
    st.subheader("What-if: service level and lead time")
    st.caption("Recomputes safety stock, ROP, order-up-to and quantity with the same code as the pipeline "
               "(`src/inventory.py`), from the 28-day forecast, the backtest error and the synthetic on-hand above.")
    a, b = st.columns(2)
    service = a.slider("Service level", 0.90, 0.99, float(C.SERVICE_LEVEL), 0.01)
    mult = b.slider("Lead-time multiplier", 0.5, 2.0, 1.0, 0.25, format="%.2fx")
    fc, err = load("forecast_next_28d.csv", "outputs"), load("series_error_stats.csv", "outputs")
    price = load("dim_sku_location.csv").set_index("series_id")["latest_price"]
    new = W.whatif_reorder_list(fc, err, base, price, service, mult)
    cmp = W.compare(base, new)
    c = st.columns(4)
    c[0].metric("SKU-locations to reorder", int(cmp.loc["skus", "what_if"]), int(cmp.loc["skus", "change"]))
    c[1].metric("Units to order", f"{int(cmp.loc['units', 'what_if']):,}", f"{int(cmp.loc['units', 'change']):+,}")
    c[2].metric("Order value", f"${cmp.loc['order_value', 'what_if']:,.0f}", f"{'-' if cmp.loc['order_value', 'change'] < 0 else '+'}${abs(cmp.loc['order_value', 'change']):,.0f}")
    c[3].metric("HIGH-risk", int(cmp.loc["high", "what_if"]), int(cmp.loc["high", "change"]), delta_color="inverse")
    st.caption("Deltas are versus the baseline list (service level "
               f"{C.SERVICE_LEVEL:.0%}, lead times {C.LEAD_TIME_DAYS}). Lead time is rounded to whole days.")
    ch = W.changed_rows(base, new)
    if ch.empty:
        st.info("At these settings the result equals the baseline.")
    else:
        with st.expander(f"{len(ch)} SKU-locations change quantity or risk"):
            st.dataframe(ch, hide_index=True, width="stretch")


def page_reorder() -> None:
    st.header("Inventory Reorder Engine")
    st.subheader("Where do I need to reorder today, and how much?")
    st.warning("Current inventory is synthetic (M5 has no inventory data). Lead times, service level and case pack are also assumptions.")
    rl = load("reorder_list.csv")
    a, b = st.columns(2)
    locs = a.multiselect("Location", sorted(rl["location"].unique()), default=sorted(rl["location"].unique()))
    risks = b.multiselect("Risk", I.RISK_ORDER, default=I.RISK_ORDER)
    only_todo = st.checkbox("Only SKU-locations to reorder today", value=True)
    f = rl[rl["location"].isin(locs) & rl["stockout_risk"].isin(risks)]
    todo = f[f["recommended_order_quantity"] > 0]
    c = st.columns(4)
    c[0].metric("SKU-locations to reorder", len(todo))
    c[1].metric("Recommended units", f"{int(todo['recommended_order_quantity'].sum()):,}")
    c[2].metric("Order value", f"${todo['order_value'].sum():,.2f}")
    c[3].metric("HIGH risk", int((f["stockout_risk"] == "HIGH").sum()))

    table = (todo if only_todo else f)[REORDER_COLS]  # reorder_list.csv is already sorted: risk priority, then days of cover
    st.dataframe(styled_risk(table, {"forecast_demand": "{:.1f}", "safety_stock": "{:.1f}", "reorder_point": "{:.1f}", "order_up_to": "{:.1f}",
                                     "order_value": "${:,.2f}", "days_of_cover": "{:.1f}"}), hide_index=True, width="stretch", height=380)
    st.caption("Sorted by priority: HIGH, MEDIUM, OVERSTOCK, OK, then fewest days of cover. forecast_demand = demand over the lead time.")
    st.download_button("Download reorder list (CSV)", table.to_csv(index=False).encode("utf-8"), "reorder_list_filtered.csv", "text/csv")

    st.subheader("Order value by location")
    if todo.empty:
        st.info("No orders for the current filters.")
    else:
        ov = todo.groupby("location", as_index=False)["order_value"].sum()
        st.altair_chart(bar(ov, "location", "order_value", sort="-y", fmt="$,.2f", title="Order value ($)"), width="stretch")

    worked_example(rl)
    what_if(rl)

    sim = load("policy_simulation.csv")
    sim = sim[sim["location"] == "ALL"].set_index("policy")
    if {"proposed", "naive_ma28"} <= set(sim.index):
        st.subheader("Policy check: replay of the last 28 days")
        c = st.columns(3)
        c[0].metric("Fill rate, proposed policy", f"{sim.loc['proposed', 'fill_rate']:.1%}")
        c[1].metric("Fill rate, naive 28-day MA rule", f"{sim.loc['naive_ma28', 'fill_rate']:.1%}")
        c[2].metric("Avg on-hand value, proposed vs naive", f"${sim.loc['proposed', 'avg_on_hand_value']:,.0f}",
                    f"{sim.loc['proposed', 'avg_on_hand_value'] - sim.loc['naive_ma28', 'avg_on_hand_value']:+,.0f} USD vs naive", delta_color="off")


# ---------- layout ----------
st.title("Demand Forecasting & Inventory Reorder Engine")
page = st.sidebar.radio("Page", PAGES, key="page")
with st.sidebar.expander("About / assumptions"):
    st.markdown(
        f"- Data: M5 (Walmart) subset, department {C.DEPT}, stores {', '.join(C.STORES)}; history {C.HISTORY_START} to {C.AS_OF_DATE}.\n"
        f"- Forecast: {C.HORIZON}-day horizon, 3-fold rolling-origin backtest, one global model chosen by a parsimony rule.\n"
        f"- Service level {C.SERVICE_LEVEL:.0%}; lead times {C.LEAD_TIME_DAYS} days; order cycle {C.ORDER_CYCLE_DAYS} days; case pack {C.CASE_PACK}.\n"
        f"- Current inventory is **synthetic** (M5 has none); open orders assumed {C.OPEN_ORDERS}.\n"
        "- Sales are not true demand: zero-sales runs of 7+ days are flagged as likely stockouts but not corrected.")
{PAGES[0]: page_demand, PAGES[1]: page_forecast, PAGES[2]: page_reorder}[page]()
