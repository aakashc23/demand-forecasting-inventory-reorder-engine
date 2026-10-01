import math

import numpy as np
import pandas as pd
import pytest

from src import config as C
from src import inventory as I


def test_z_value():
    assert I.z_value(0.95) == pytest.approx(1.645, abs=1e-3)


def test_safety_stock_hand_example():
    assert I.safety_stock(1.645, 4.0, 9) == pytest.approx(1.645 * 4.0 * 3)  # sqrt(9) = 3 -> 19.74


def test_reorder_point():
    assert I.reorder_point(40.0, 12.5) == 52.5


def test_no_order_when_position_above_rop():
    assert I.order_quantity(50, 40.0, 80.0, 6) == 0


def test_order_rounds_up_to_case_pack():
    q = I.order_quantity(10, 40.0, 81.0, 6)  # need 71 -> 12 cases = 72
    assert q == 72 and isinstance(q, int)
    assert I.order_quantity(10, 40.0, 82.0, 6) == 72  # need exactly 72 -> no extra case
    assert I.order_quantity(10, 40.0, 82.5, 6) == 78  # need 72.5 -> 13 cases
    assert I.order_quantity(10, 40.0, 81.0, 1) == 71  # case pack 1 disables rounding


def test_order_never_negative():
    assert I.order_quantity(5, 40.0, 3.0, 6) == 0  # bad inputs (S below IP) still give 0, not negative


def test_ip_equal_to_rop_triggers_order():
    assert I.order_quantity(40, 40.0, 60.0, 6) == 24


@pytest.mark.parametrize("on_hand, ltd, rop, cover, expected", [
    (5, 10, 15, 3, "HIGH"),
    (12, 10, 15, 40, "MEDIUM"),      # reorder now even though cover is above the overstock days
    (15, 10, 15, 3, "MEDIUM"),       # on_hand == ROP is MEDIUM
    (20, 10, 15, 31, "OVERSTOCK"),
    (20, 10, 15, 30, "OK"),          # exactly at the threshold is not overstock
    (20, 10, 15, 5, "OK"),
])
def test_risk_flag_branches(on_hand, ltd, rop, cover, expected):
    assert I.risk_flag(on_hand, ltd, rop, cover, 30) == expected


def test_high_beats_medium():
    assert I.risk_flag(5, 10, 15, 100, 30) == "HIGH"  # also <= ROP and overstock-like cover


def test_synthetic_inventory_reproducible():
    mean = np.array([1.5, 10.0, 0.2, 30.0])
    a = I.synthetic_inventory(mean, np.random.default_rng(C.SEED))
    b = I.synthetic_inventory(mean, np.random.default_rng(C.SEED))
    assert (a == b).all() and a.dtype.kind == "i"
    assert (a >= 0).all() and (a <= C.SYNTHETIC_DAYS_OF_SUPPLY[1] * mean + 0.5).all()


def test_reorder_list_integration():
    path = C.OUTPUT_DIR / "reorder_list.csv"
    if not path.exists():
        pytest.skip("outputs/reorder_list.csv not generated yet")
    rl = pd.read_csv(path)
    q = rl["recommended_order_quantity"]
    assert list(rl.columns) == I.COLS
    assert (q >= 0).all() and (q % C.CASE_PACK == 0).all()
    assert np.allclose(rl["reorder_point"], (rl["forecast_demand"] + rl["safety_stock"]).round(1), atol=0.11)
    assert ((q > 0) == (rl["inventory_position"] <= rl["reorder_point"])).all()
    assert (rl["order_up_to"] >= rl["reorder_point"]).all()
