"""Policy replay on backtest fold 3: proposed (forecast + safety stock) vs naive 28-day-MA rule. No leakage, no models fitted."""
import numpy as np
import pandas as pd

from src import config as C
from src.forecast import selected_model
from src.inventory import order_quantity, safety_stock, z_value

FOLD = 3


def replay(levels, demand: np.ndarray, L: int, pack: int) -> dict:
    """Day-by-day replay of one series. levels(t) -> (ROP, order_up_to) for the days starting at index t.
    Each day: receive arrivals, serve demand (unmet demand is lost), review IP, order up to S in whole cases.
    The review is after day t's demand, i.e. the morning of t+1, so the order arrives at the start of day t+L+1 and ROP covers days t+1..t+L."""
    n = len(demand)
    on_hand, pipe = int(round(levels(0)[1])), np.zeros(n + L + 2)  # start at the day-1 order-up-to level
    sold, stock, orders = np.zeros(n), np.zeros(n), 0
    for t in range(n):
        on_hand += pipe[t]
        sold[t] = min(on_hand, demand[t])
        on_hand -= sold[t]
        stock[t] = on_hand
        rop, s_up = levels(t + 1)
        qty = order_quantity(on_hand + pipe[t + 1:].sum(), rop, s_up, pack)
        if qty:
            pipe[t + L + 1] += qty
            orders += 1
    return {"sold": sold, "on_hand": stock, "orders": orders}


def proposed_levels(f: np.ndarray, L: int, ss: float):
    """ROP = forecast over the next L days + SS; S = ROP + the next T days. Days past the window use the forecast mean."""
    padded = np.concatenate([f, np.full(L + C.ORDER_CYCLE_DAYS + 1, f.mean())])
    def levels(t: int):
        rop = padded[t:t + L].sum() + ss
        return rop, rop + padded[t + L:t + L + C.ORDER_CYCLE_DAYS].sum()
    return levels


def naive_levels(ma: float, L: int):
    return lambda t: (ma * L, ma * (L + C.ORDER_CYCLE_DAYS))


def run_simulation() -> pd.DataFrame:
    model = selected_model()
    bt = pd.read_csv(C.OUTPUT_DIR / "backtest_forecasts.csv", parse_dates=["date"])
    bt = bt[(bt["model"] == model) & (bt["fold"] == FOLD)].sort_values(["series_id", "date"])
    err = pd.read_csv(C.OUTPUT_DIR / "series_error_stats.csv").set_index("series_id")
    sales = pd.read_csv(C.SALES_CLEAN_PATH, parse_dates=["date"])
    price = sales.pivot(index="date", columns="series_id", values="sell_price").ffill().bfill()
    units = sales.pivot(index="date", columns="series_id", values="units")
    origin, z = pd.Timestamp(C.BACKTEST_ORIGINS[FOLD - 1]), z_value(C.SERVICE_LEVEL)
    rows = []
    for sid, g in bt.groupby("series_id"):
        loc, L = err.loc[sid, "location"], C.LEAD_TIME_DAYS[err.loc[sid, "location"]]
        demand = g["actual_demand"].to_numpy()  # actual sales; the same values as units[sid] in the window
        ss = safety_stock(z, err.loc[sid, "rmse_folds_1_2"], L)  # sigma from folds 1-2 only (no leakage)
        ma = units.loc[:origin, sid].iloc[-28:].mean()           # naive rule: last 28 days of actuals before the origin
        policies = {"proposed": proposed_levels(g["forecast_demand"].to_numpy(), L, ss), "naive_ma28": naive_levels(ma, L)}
        for name, levels in policies.items():
            r = replay(levels, demand, L, C.CASE_PACK)
            p = price.loc[g["date"], sid].to_numpy()
            orders = np.zeros(len(demand), dtype=int)
            orders[0] = r["orders"]  # series total, stored on day 1 so a plain sum gives orders_placed
            rows.append(pd.DataFrame({"policy": name, "location": loc, "series_id": sid, "demand": demand, "sold": r["sold"],
                                      "on_hand": r["on_hand"], "on_hand_value": r["on_hand"] * p, "orders": orders}))
    return pd.concat(rows, ignore_index=True)


def summarize(days: pd.DataFrame) -> pd.DataFrame:
    days = days.assign(lost=days["demand"] - days["sold"])
    def metrics(g: pd.DataFrame) -> pd.Series:
        so = int((g["lost"] > 0).sum())
        return pd.Series({"series": g["series_id"].nunique(), "series_days": len(g),
                          "fill_rate": g["sold"].sum() / g["demand"].sum(), "stockout_days": so,
                          "stockout_day_pct": 100 * so / len(g), "avg_on_hand_units": g["on_hand"].mean(),
                          "avg_on_hand_value": g["on_hand_value"].mean(), "orders_placed": g["orders"].sum()})
    parts = [days.assign(location="ALL")] + [days[days["location"] == loc] for loc in C.STORES]
    out = pd.concat(parts).groupby(["policy", "location"]).apply(metrics, include_groups=False).reset_index()
    out = out.astype({"series": int, "series_days": int, "stockout_days": int, "orders_placed": int})
    out["location"] = pd.Categorical(out["location"], ["ALL"] + C.STORES)
    return out.sort_values(["location", "policy"]).reset_index(drop=True)


def main() -> None:
    out = summarize(run_simulation())
    out.to_csv(C.OUTPUT_DIR / "policy_simulation.csv", index=False)
    print(f"[simulate] fold {FOLD} replay ({C.BACKTEST_ORIGINS[FOLD - 1]} origin, 28 days), proposed vs naive 28-day MA rule")
    print(out.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    print("[simulate] CAVEAT: demand = observed sales (censored by past stockouts, so true demand is understated), "
          "and the window is only 28 days; read this as a sanity check, not proof.")


if __name__ == "__main__":
    main()
