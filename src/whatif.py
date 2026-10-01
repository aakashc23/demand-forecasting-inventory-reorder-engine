"""What-if helpers for the Streamlit app: recompute the reorder list for another service level / lead-time multiplier.
All inventory math lives in src/inventory.py; this module only wires the inputs and compares results."""
import pandas as pd

from src import config as C
from src import inventory as I


def whatif_reorder_list(fc: pd.DataFrame, err: pd.DataFrame, base: pd.DataFrame, price: pd.Series,
                        service_level: float = C.SERVICE_LEVEL, lead_time_mult: float = 1.0) -> pd.DataFrame:
    """Recompute the reorder list. `fc` = outputs/forecast_next_28d.csv, `err` = outputs/series_error_stats.csv,
    `base` = outputs/reorder_list.csv (supplies the fixed synthetic on-hand), `price` = latest price per series_id.
    Defaults reproduce `base` exactly."""
    on_hand = dict(zip(base["series_id"], base["current_inventory"]))
    return I.build_reorder_table(fc, err, on_hand, price, service_level, lead_time_mult)


def kpis(rl: pd.DataFrame) -> dict:
    """Headline numbers of a reorder list: SKU-locations to reorder, units, order value, HIGH-risk count."""
    todo = rl[rl["recommended_order_quantity"] > 0]
    return {"skus": len(todo), "units": int(todo["recommended_order_quantity"].sum()),
            "order_value": round(float(todo["order_value"].sum()), 2), "high": int((rl["stockout_risk"] == "HIGH").sum())}


def compare(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Baseline vs what-if KPIs with the change."""
    b, n = kpis(base), kpis(new)
    return pd.DataFrame({"baseline": b, "what_if": n, "change": {k: round(n[k] - b[k], 2) for k in b}})


def changed_rows(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Series whose order quantity or risk flag differs from the baseline."""
    cols = ["series_id", "sku", "location", "current_inventory", "recommended_order_quantity", "order_value", "stockout_risk"]
    m = base[cols].merge(new[cols], on=["series_id", "sku", "location", "current_inventory"], suffixes=("_base", "_new"))
    diff = (m["recommended_order_quantity_base"] != m["recommended_order_quantity_new"]) | (m["stockout_risk_base"] != m["stockout_risk_new"])
    return m[diff].reset_index(drop=True)
