"""Run every pipeline step in order. From the project root: python run_pipeline.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import backtest, data_prep, eda, forecast, inventory, plots, simulate, sql_layer, export_powerbi  # noqa: E402

STEPS = [
    ("data_prep", data_prep.main),
    ("eda", eda.main),
    ("backtest", backtest.main),
    ("forecast", forecast.main),
    ("plots", plots.main),
    ("inventory", inventory.main),
    ("simulate", simulate.main),
    ("sql", sql_layer.main),
    ("export_powerbi", export_powerbi.main),
]


def main() -> None:
    for name, step in STEPS:
        print(f"=== {name} ===")
        t0 = time.time()
        step()
        print(f"=== {name} done in {time.time() - t0:.1f}s ===\n")


if __name__ == "__main__":
    main()
