"""Forecast accuracy metrics. MAPE is not a headline metric because daily SKU sales contain zeros."""
import numpy as np


def mae(actual, forecast) -> float:
    return float(np.mean(np.abs(np.asarray(forecast, float) - np.asarray(actual, float))))


def rmse(actual, forecast) -> float:
    return float(np.sqrt(np.mean((np.asarray(forecast, float) - np.asarray(actual, float)) ** 2)))


def wape(actual, forecast) -> float:
    """Sum |error| / sum actual."""
    a = np.asarray(actual, float)
    return float(np.abs(np.asarray(forecast, float) - a).sum() / a.sum())


def bias(actual, forecast) -> float:
    """Sum (forecast - actual) / sum actual; positive = over-forecast."""
    a = np.asarray(actual, float)
    return float((np.asarray(forecast, float) - a).sum() / a.sum())


def mase(actual, forecast, train, season: int = 7) -> float:
    """MAE divided by the in-sample seasonal-naive (lag-7) MAE of the training data."""
    t = np.asarray(train, float)
    scale = np.mean(np.abs(t[season:] - t[:-season]))
    return mae(actual, forecast) / scale


def mape_nonzero(actual, forecast) -> float:
    """Secondary: MAPE over days with actual > 0 only (zero-sales days are excluded)."""
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    m = a > 0
    return float(np.mean(np.abs(f[m] - a[m]) / a[m]))
