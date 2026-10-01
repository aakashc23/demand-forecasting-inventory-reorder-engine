"""Smoke test: every Streamlit page renders without an exception (uses streamlit.testing, no server needed)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["1. Demand Overview", "2. Forecast Performance", "3. Inventory Reorder Engine"]  # sidebar radio options in app.py


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_exception(page):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value == "Demand Forecasting & Inventory Reorder Engine"


def test_reorder_page_whatif_sliders_run():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio(key="page").set_value(PAGES[2]).run()
    sliders = {s.label: s for s in at.slider}
    sliders["Service level"].set_value(0.99)
    sliders["Lead-time multiplier"].set_value(2.0)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
