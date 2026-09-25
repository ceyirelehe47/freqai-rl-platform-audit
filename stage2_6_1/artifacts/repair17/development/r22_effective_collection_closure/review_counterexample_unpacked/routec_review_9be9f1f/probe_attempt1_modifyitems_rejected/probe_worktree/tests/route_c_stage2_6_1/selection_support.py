import os

def pytest_collection_modifyitems(items):
    if os.environ.get("LOCAL_QUICK_TESTS") == "1":
        items[:] = [item for item in items if item.name != "test_parameter[1]"]
