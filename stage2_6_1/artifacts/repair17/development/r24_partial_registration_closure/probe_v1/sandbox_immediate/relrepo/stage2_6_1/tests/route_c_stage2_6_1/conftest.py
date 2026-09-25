# sandbox conftest (partial install, immediate cleanup)
import json
from pathlib import Path

import pluggy
import pytest


def _event(name, **values):
    with Path("partial_plugin_events.jsonl").open("a") as handle:
        handle.write(json.dumps({"event": name, **values}) + "\n")


class PartialImmediatePlugin:
    @pytest.hookimpl(specname="pytest_pycollect_makeitem",
                     hookwrapper=True)
    def pytest_a_filter(self, collector, name, obj):
        outcome = yield
        if name == "test_parameter":
            items = outcome.get_result()
            if isinstance(items, list):
                _event("filter_called_unexpectedly")
                outcome.force_result(items)

    @pytest.hookimpl(specname="pytest_configure")
    def pytest_z_invalid_signature(self, not_a_pytest_argument):
        pass


def pytest_sessionstart(session):
    plugin = PartialImmediatePlugin()
    try:
        session.config.pluginmanager.register(
            plugin, "partial_immediate")
    except pluggy.PluginValidationError as exc:
        manager = session.config.pluginmanager
        _event("registration_exception_caught",
               error_type=type(exc).__name__,
               remains_registered=manager.is_registered(plugin),
               active_filter=any(
                   impl.plugin is plugin for impl in
                   manager.hook.pytest_pycollect_makeitem
                   .get_hookimpls()))
        manager.unregister(plugin)
        _event("cleaned_up", remains_registered=(
            manager.is_registered(plugin)))
    else:
        raise AssertionError("probe expected validation failure")
