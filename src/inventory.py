"""Inventory decision: turns forecasts + forecast-error stats into a reorder list. Never fits or calls forecasting models."""
import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from src import config as C

RISK_ORDER = ["HIGH", "MEDIUM", "OVERSTOCK", "OK"]
COLS = ["date", "sku", "location", "series_id", "current_inventory", "inventory_position", "forecast_demand",
        "forecast_daily_avg", "lead_time", "demand_std", "service_level", "z_value", "safety_stock", "reorder_point",
        "order_up_to", "recommended_order_quantity", "order_value", "days_of_cover", "stockout_risk", "reorder_decision"]


def z_value(service_level: float) -> float:
    """Normal quantile for the cycle service level."""
    return float(norm.ppf(service_level))


def safety_stock(z: float, sigma: float, lead_time: float) -> float:
    """z * sigma * sqrt(L): buffer for forecast error over the lead time (errors assumed independent day to day)."""
    return z * sigma * math.sqrt(lead_time)


def reorder_point(lead_time_demand: float, ss: float) -> float:
    return lead_time_demand + ss


def order_quantity(inventory_position: float, rop: float, order_up_to: float, case_pack: int) -> int:
    """Order up to `order_up_to`, rounded UP to whole cases, when IP <= ROP; otherwise 0. Never negative."""
    if inventory_position > rop:
        return 0
    need = max(0.0, order_up_to - inventory_position)
    return int(math.ceil(round(need / case_pack, 9)) * case_pack)


def risk_flag(on_hand: float, lead_time_demand: float, rop: float, days_of_cover: float, overstock_days: float) -> str:
    """Priority: HIGH (stocks out before an order can arrive) > MEDIUM (reorder now) > OVERSTOCK > OK."""
    if on_hand < lead_time_demand:
        return "HIGH"
    if on_hand <= rop:
        return "MEDIUM"
    if days_of_cover > overstock_days:
        return "OVERSTOCK"
    return "OK"


def synthetic_inventory(mean_daily_forecast, rng: np.random.Generator):
    """SYNTHETIC on-hand = round(U(lo, hi) days x mean daily forecast). Pass series in sorted series_id order."""
    lo, hi = C.SYNTHETIC_DAYS_OF_SUPPLY
    days = rng.uniform(lo, hi, size=np.shape(mean_daily_forecast))
    return np.round(days * np.asarray(mean_daily_forecast)).astype(int)


def compute_reorder(f: np.ndarray, on_hand: int, sigma: float, lead_time: int, z: float, price: float,
                    order_cycle: int = C.ORDER_CYCLE_DAYS, case_pack: int = C.CASE_PACK,
                    open_orders: int = C.OPEN_ORDERS, overstock_days: float = C.OVERSTOCK_DAYS) -> dict:
    """One series' decision from its 28-day forecast `f`, on-hand, sigma and lead time. Used by the pipeline and the app."""
    avg = f.mean()
    ltd, cycle = f[:lead_time].sum(), f[lead_time:lead_time + order_cycle].sum()
    ss = safety_stock(z, sigma, lead_time)
    rop = round(reorder_point(ltd, ss), 1)
    s_up = round(rop + cycle, 1)
    ip = int(on_hand) + open_orders
    qty = order_quantity(ip, rop, s_up, case_pack)
    cover = on_hand / avg if avg > 0 else float("inf")
    return {"current_inventory": int(on_hand), "inventory_position": ip, "forecast_demand": round(ltd, 1),
            "forecast_daily_avg": round(avg, 2), "lead_time": lead_time, "demand_std": round(sigma, 2),
            "safety_stock": round(ss, 1), "reorder_point": rop, "order_up_to": s_up,
            "recommended_order_quantity": qty, "order_value": round(qty * price, 2), "days_of_cover": round(cover, 1),
            "stockout_risk": risk_flag(on_hand, ltd, rop, cover, overstock_days),
            "reorder_decision": "REORDER" if qty > 0 else "NO ACTION"}


def scaled_lead_time(lead_time: int, multiplier: float = 1.0) -> int:
    """Lead time x multiplier rounded half up to whole days (at least 1)."""
    return max(1, int(math.floor(lead_time * multiplier + 0.5)))


def build_reorder_table(fc: pd.DataFrame, err: pd.DataFrame, on_hand: dict, price: pd.Series,
                        service_level: float = C.SERVICE_LEVEL, lead_time_mult: float = 1.0) -> pd.DataFrame:
    """Reorder table for given forecasts (future rows), error stats, on-hand per series_id and latest price.
    Defaults reproduce the official list; the app changes service level / lead-time multiplier for what-if runs."""
    fc = fc.sort_values(["series_id", "date"])
    err = err.set_index("series_id")
    z = z_value(service_level)
    rows = []
    for sid, g in fc.groupby("series_id"):  # sorted by series_id
        loc = err.loc[sid, "location"]
        L = scaled_lead_time(C.LEAD_TIME_DAYS[loc], lead_time_mult)
        r = compute_reorder(g["forecast_demand"].to_numpy(), on_hand[sid], err.loc[sid, "rmse_all_folds"], L, z, price[sid])
        rows.append({"date": C.RUN_DATE, "sku": err.loc[sid, "sku"], "location": loc, "series_id": sid, **r,
                     "service_level": service_level, "z_value": round(z, 3)})
    out = pd.DataFrame(rows)[COLS]
    out["_r"] = out["stockout_risk"].map(RISK_ORDER.index)
    return out.sort_values(["_r", "days_of_cover"]).drop(columns="_r").reset_index(drop=True)


def build_reorder_list() -> pd.DataFrame:
    """One row per SKU-location, sorted by risk then days of cover."""
    fc = pd.read_csv(C.OUTPUT_DIR / "forecast_next_28d.csv", parse_dates=["date"]).sort_values(["series_id", "date"])
    err = pd.read_csv(C.OUTPUT_DIR / "series_error_stats.csv")
    sales = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"]).sort_values("date")
    price = sales.groupby("series_id")["sell_price"].last()  # latest observed price
    ids = sorted(fc["series_id"].unique())
    mean_daily = np.array([fc.loc[fc["series_id"] == s, "forecast_demand"].mean() for s in ids])
    on_hand = dict(zip(ids, synthetic_inventory(mean_daily, np.random.default_rng(C.SEED))))
    return build_reorder_table(fc, err, on_hand, price)


def summarize(rl: pd.DataFrame) -> None:
    todo = rl[rl["recommended_order_quantity"] > 0]
    print("[inventory] rows by risk flag:", rl["stockout_risk"].value_counts().reindex(RISK_ORDER, fill_value=0).to_dict())
    print(f"[inventory] SKU-locations to reorder today: {len(todo)} of {len(rl)} | "
          f"units: {todo['recommended_order_quantity'].sum():,} | order value: ${todo['order_value'].sum():,.2f}")
    by_loc = rl.groupby("location").apply(lambda g: pd.Series({
        "series": len(g), "to_reorder": int((g["recommended_order_quantity"] > 0).sum()),
        "units": int(g["recommended_order_quantity"].sum()), "order_value": round(g["order_value"].sum(), 2),
        "HIGH": int((g["stockout_risk"] == "HIGH").sum())}), include_groups=False)
    print(by_loc.astype({"series": int, "to_reorder": int, "units": int, "HIGH": int}).to_string())


def _example(r: pd.Series) -> str:
    """Worked formula chain for one reorder-list row, using the row's own numbers (shown rounded as in the CSV)."""
    ip, rop, S, qty = r["inventory_position"], r["reorder_point"], r["order_up_to"], r["recommended_order_quantity"]
    rule = {"HIGH": f"on_hand {r['current_inventory']} < lead-time demand {r['forecast_demand']}: stock runs out before a new order can arrive.",
            "MEDIUM": f"on_hand {r['current_inventory']} >= lead-time demand {r['forecast_demand']} but <= ROP {rop}: reorder now.",
            "OVERSTOCK": f"on_hand {r['current_inventory']} > ROP {rop} and cover {r['days_of_cover']} days > {C.OVERSTOCK_DAYS}.",
            "OK": f"on_hand {r['current_inventory']} > ROP {rop} and cover {r['days_of_cover']} days <= {C.OVERSTOCK_DAYS}."}[r["stockout_risk"]]
    if qty > 0:
        quantity = (f"ceil(({S} - {ip}) / {C.CASE_PACK}) x {C.CASE_PACK} = ceil({(S - ip) / C.CASE_PACK:.2f}) x {C.CASE_PACK} = {qty}")
        action = f"Order {qty} units (about ${r['order_value']:,.2f}) today."
    else:
        quantity = "0 (inventory position is above the reorder point)"
        action = f"No order today: inventory position {ip} is above the reorder point {rop}."
    lines = [
        f"### {r['stockout_risk']}: {r['sku']} at {r['location']}", "",
        f"- Inputs: lead time L = {r['lead_time']} days (assumed); sigma = {r['demand_std']} (backtest RMSE); "
        f"Z = {r['z_value']} (service level {r['service_level']:.0%}); on-hand = {r['current_inventory']} (SYNTHETIC); "
        f"open orders = {C.OPEN_ORDERS} (assumed)",
        f"- Lead-time demand = sum of forecast for the next {r['lead_time']} days = {r['forecast_demand']}",
        f"- SS = {r['z_value']} x {r['demand_std']} x sqrt({r['lead_time']}) = {r['safety_stock']}",
        f"- ROP = {r['forecast_demand']} + {r['safety_stock']} = {rop}",
        f"- Order-up-to S = ROP + {C.ORDER_CYCLE_DAYS}-day cycle demand = {rop} + {S - rop:.1f} = {S}",
        f"- Inventory position = {r['current_inventory']} + {C.OPEN_ORDERS} = {ip}; compared with ROP {rop}",
        f"- Quantity = {quantity}", f"- Risk flag: {rule}", f"- Decision: {action}", ""]
    return "\n".join(lines)


def write_examples(rl: pd.DataFrame) -> None:
    """reports/reorder_examples.md: one worked example per risk flag (the median-cover row of each flag)."""
    parts = ["# Worked reorder examples", "",
             f"Generated by `src/inventory.py` from `outputs/reorder_list.csv` (run date {C.RUN_DATE}). On-hand is SYNTHETIC; "
             "lead times, service level, case pack and open orders are assumptions. Numbers are shown rounded as in the CSV.", ""]
    for flag in RISK_ORDER:
        g = rl[rl["stockout_risk"] == flag].reset_index(drop=True)
        note = f" (synthetic on-hand is at most {C.SYNTHETIC_DAYS_OF_SUPPLY[1]} days of supply vs the {C.OVERSTOCK_DAYS}-day threshold)." if flag == "OVERSTOCK" else "."
        parts.append(_example(g.iloc[len(g) // 2]) if len(g) else f"### {flag}\n\nNo rows have this flag in the current run{note}\n")
    (C.ROOT / "reports").mkdir(exist_ok=True)
    (C.ROOT / "reports" / "reorder_examples.md").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    rl = build_reorder_list()
    rl.to_csv(C.OUTPUT_DIR / "reorder_list.csv", index=False)
    rl[rl["recommended_order_quantity"] > 0].to_csv(C.OUTPUT_DIR / "reorder_list_today.csv", index=False)
    print(f"[inventory] wrote reorder_list.csv ({len(rl)} rows) and reorder_list_today.csv; "
          f"on-hand is SYNTHETIC (seed {C.SEED}), open orders assumed {C.OPEN_ORDERS}, case pack {C.CASE_PACK}")
    summarize(rl)
    write_examples(rl)


if __name__ == "__main__":
    main()
