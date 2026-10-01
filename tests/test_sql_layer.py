import pytest

from src import config as C
from src import sql_layer

REQUIRED = [C.SALES_CLEAN_PATH] + [C.OUTPUT_DIR / f for f in (
    "backtest_forecasts.csv", "forecasts.csv", "model_comparison.csv", "reorder_list.csv",
    "reorder_list_today.csv", "series_error_stats.csv")]


@pytest.mark.skipif(not all(p.exists() for p in REQUIRED), reason="pipeline outputs missing; run run_pipeline.py first")
def test_sql_layer_reconciles(tmp_path):
    checks = sql_layer.main(db_path=tmp_path / "test.db", results_dir=tmp_path / "sql_results",
                            report_path=tmp_path / "sql_reconciliation.md", export_dir=None)
    assert (checks["status"] == "PASS").all()
    assert len(checks) > 30
    assert (tmp_path / "sql_reconciliation.md").exists()
    assert len(list((tmp_path / "sql_results").glob("*.csv"))) == 10
