import numpy as np
import pytest

from src import metrics as M

ACTUAL = np.array([10.0, 20.0, 30.0])
FORECAST = np.array([12.0, 18.0, 33.0])  # errors: +2, -2, +3


def test_mae_rmse():
    assert M.mae(ACTUAL, FORECAST) == pytest.approx(7 / 3)
    assert M.rmse(ACTUAL, FORECAST) == pytest.approx(np.sqrt(17 / 3))


def test_wape_and_bias():
    assert M.wape(ACTUAL, FORECAST) == pytest.approx(7 / 60)
    assert M.bias(ACTUAL, FORECAST) == pytest.approx(3 / 60)  # positive = over-forecast


def test_mase_scales_by_lag7_naive():
    train = np.array([1, 2, 3, 4, 5, 6, 7, 8, 10], float)  # lag-7 abs diffs: 7 and 8 -> mean 7.5
    assert M.mase(ACTUAL, FORECAST, train) == pytest.approx((7 / 3) / 7.5)


def test_mape_nonzero_ignores_zero_days():
    a, f = np.array([0.0, 10.0]), np.array([5.0, 12.0])
    assert M.mape_nonzero(a, f) == pytest.approx(0.2)
