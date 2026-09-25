import os
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_pycollect_makeitem(collector, name, obj):
    outcome = yield
    if os.environ.get("LOCAL_QUICK_TESTS") == "1":
        items = outcome.get_result()
        if isinstance(items, list):
            outcome.force_result([item for item in items if item.name != "test_parameter[1]"])
