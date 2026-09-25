# sandbox conftest (scoped specname temporary plugin; review probe)
import json
from pathlib import Path

import pytest


def _event(name, **values):
    with Path("scoped_plugin_events.jsonl").open("a") as handle:
        handle.write(json.dumps({"event": name, **values}) + "\n")


class ScopedCollectionPlugin:
    @pytest.hookimpl(specname="pytest_pycollect_makeitem",
                     hookwrapper=True)
    def pytest_scoped_parameter(self, collector, name, obj):
        outcome = yield
        if name == "test_parameter":
            items = outcome.get_result()
            if isinstance(items, list):
                kept = [item for item in items
                        if getattr(item, "callspec", None) is None
                        or item.callspec.params.get("x") != 1]
                _event("filtered",
                       generated=[item.name for item in items],
                       kept=[item.name for item in kept])
                outcome.force_result(kept)

    @pytest.hookimpl(specname="pytest_collection_finish", tryfirst=True)
    def pytest_release_scope(self, session):
        session.config.pluginmanager.unregister(self)
        _event("unregistered")


def pytest_sessionstart(session):
    try:
        session.config.pluginmanager.register(
            ScopedCollectionPlugin(), "scoped_collection")
    except Exception:  # noqa: BLE001 —— 审查 A02:注册异常被捕获
        pass
    _event("registered")
