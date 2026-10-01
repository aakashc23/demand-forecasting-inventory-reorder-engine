"""Five forecasting models as pure functions f(train, horizon) -> np.ndarray (clipped at 0). No inventory logic here."""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing

HW_HISTORY_DAYS = 364     # Holt-Winters fit window and seasonal-index window (52 full weeks)
MA_DAYS = 28              # level window for the moving-average models
HW_STATS = {"fallbacks": 0, "convergence_warnings": 0}  # running counters, reset with reset_hw_stats()


def reset_hw_stats() -> None:
    HW_STATS.update(fallbacks=0, convergence_warnings=0)


def _future_dates(train: pd.Series, horizon: int) -> pd.DatetimeIndex:
    return pd.date_range(train.index[-1], periods=horizon + 1, freq="D")[1:]


def naive(train: pd.Series, horizon: int) -> np.ndarray:
    """Last observed value repeated."""
    return np.clip(np.repeat(float(train.iloc[-1]), horizon), 0, None)


def seasonal_naive(train: pd.Series, horizon: int) -> np.ndarray:
    """Same weekday last week: the last 7 days repeated."""
    last_week = train.iloc[-7:].to_numpy(dtype=float)
    return np.clip(np.resize(last_week, horizon), 0, None)


def moving_average(train: pd.Series, horizon: int) -> np.ndarray:
    """Mean of the last 28 days."""
    return np.clip(np.repeat(train.iloc[-MA_DAYS:].mean(), horizon), 0, None)


def seasonal_ma(train: pd.Series, horizon: int) -> np.ndarray:
    """Level (28-day mean) x day-of-week index (weekday mean / overall mean over the last 364 days)."""
    recent = train.iloc[-HW_HISTORY_DAYS:]
    overall = recent.mean()
    index = recent.groupby(recent.index.dayofweek).mean() / overall if overall > 0 else pd.Series(1.0, index=range(7))
    weekdays = _future_dates(train, horizon).dayofweek
    level = train.iloc[-MA_DAYS:].mean()
    return np.clip(level * index.reindex(weekdays).fillna(1.0).to_numpy(), 0, None)


def holt_winters(train: pd.Series, horizon: int) -> np.ndarray:
    """Damped additive-trend, additive weekly-seasonal exponential smoothing on the last 364 days; falls back to seasonal_ma."""
    y = train.iloc[-HW_HISTORY_DAYS:].astype(float).to_numpy()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fit = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add", seasonal_periods=7,
                                       initialization_method="estimated").fit()
            fc = np.asarray(fit.forecast(horizon), dtype=float)
        HW_STATS["convergence_warnings"] += sum(issubclass(w.category, ConvergenceWarning) for w in caught)
        if not np.isfinite(fc).all():
            raise ValueError("non-finite forecast")
    except Exception:
        HW_STATS["fallbacks"] += 1
        return seasonal_ma(train, horizon)
    return np.clip(fc, 0, None)


MODELS = {"naive": naive, "seasonal_naive": seasonal_naive, "moving_average": moving_average,
          "seasonal_ma": seasonal_ma, "holt_winters": holt_winters}  # simplest first = complexity order


def forecast_series(train: pd.Series, horizon: int, model_name: str) -> np.ndarray:
    """Forecast `horizon` days after the end of `train` with the named model."""
    return MODELS[model_name](train, horizon)
