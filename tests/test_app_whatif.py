"""The what-if helper must reproduce outputs/reorder_list.csv exactly at default settings (no Streamlit involved)."""
import pandas as pd
import pytest

from src import config as C
from src import whatif as W

OUT = C.OUTPUT_DIR


@pytest.fixture(scope="module")
def inputs():
    base = pd.read_csv(OUT / "reorder_list.csv")
    fc = pd.read_csv(OUT / "forecast_next_28d.csv")
    err = pd.read_csv(OUT / "series_error_stats.csv")
    price = pd.read_csv(C.POWERBI_DIR / "dim_sku_location.csv").set_index("series_id")["latest_price"]  # what the app uses
    return base, fc, err, price


def test_default_whatif_equals_reorder_list(inputs):
    base, fc, err, price = inputs
    new = W.whatif_reorder_list(fc, err, base, price, C.SERVICE_LEVEL, 1.0)
    pd.testing.assert_frame_equal(new, base, check_dtype=False)
    assert W.changed_rows(base, new).empty
    assert (W.compare(base, new)["change"] == 0).all()


def test_higher_service_level_and_longer_lead_time_order_more(inputs):
    base, fc, err, price = inputs
    hi = W.whatif_reorder_list(fc, err, base, price, 0.99, 1.0)
    assert (hi["safety_stock"] >= base.set_index("series_id").loc[hi["series_id"], "safety_stock"].to_numpy()).all()
    assert W.kpis(hi)["units"] >= W.kpis(base)["units"]
    long_lt = W.whatif_reorder_list(fc, err, base, price, C.SERVICE_LEVEL, 2.0)
    assert W.kpis(long_lt)["units"] > W.kpis(base)["units"]
    assert (long_lt["lead_time"] == 2 * long_lt["location"].map(C.LEAD_TIME_DAYS)).all()
