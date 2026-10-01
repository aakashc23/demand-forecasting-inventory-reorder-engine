import numpy as np
import pandas as pd
import pytest

from src import models as MD
from src.backtest import split_at_origin


def make_series(n=400, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    return pd.Series(10 + 3 * np.sin(2 * np.pi * np.arange(n) / 7) + rng.normal(0, 1, n), index=idx).clip(lower=0)


def test_models_order_is_complexity_order():
    assert list(MD.MODELS) == ["naive", "seasonal_naive", "moving_average", "seasonal_ma", "holt_winters"]


@pytest.mark.parametrize("name", list(MD.MODELS))
def test_length_and_non_negative(name):
    y = make_series() - 8  # forces some negative values; forecasts must still be clipped at 0
    fc = MD.forecast_series(y, 28, name)
    assert fc.shape == (28,)
    assert np.isfinite(fc).all() and (fc >= 0).all()


def test_seasonal_naive_repeats_last_week():
    y = make_series()
    fc = MD.seasonal_naive(y, 28)
    last_week = y.iloc[-7:].to_numpy()
    np.testing.assert_allclose(fc, np.tile(last_week, 4))


def test_naive_repeats_last_value():
    y = make_series()
    np.testing.assert_allclose(MD.naive(y, 5), np.repeat(y.iloc[-1], 5))


def test_moving_average_on_constant_series():
    y = pd.Series(5.0, index=pd.date_range("2015-01-01", periods=100))
    np.testing.assert_allclose(MD.moving_average(y, 10), 5.0)
    np.testing.assert_allclose(MD.seasonal_ma(y, 10), 5.0)


def test_holt_winters_falls_back_on_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("fit failed")
    monkeypatch.setattr(MD, "ExponentialSmoothing", boom)
    MD.reset_hw_stats()
    y = make_series()
    np.testing.assert_allclose(MD.holt_winters(y, 28), MD.seasonal_ma(y, 28))
    assert MD.HW_STATS["fallbacks"] == 1


def test_split_at_origin_has_no_leakage():
    y = make_series(500)
    origin = y.index[300]
    train, test = split_at_origin(y, origin, 28)
    assert train.index.max() <= origin
    assert test.index.min() > origin and len(test) == 28
    assert train.index.max() < test.index.min()
