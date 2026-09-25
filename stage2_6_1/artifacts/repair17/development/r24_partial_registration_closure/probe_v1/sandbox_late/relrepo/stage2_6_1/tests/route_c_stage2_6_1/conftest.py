# sandbox conftest (partial registration failure; review probe)
import json
from pathlib import Path

import pluggy
import pytest


def _event(name, **values):
    with Path("partial_plugin_events.jsonl").open("a") as handle:
        handle.write(json.dumps({"event": name, **values}) + "\n")


class PartialRegistrationPlugin:
    @pytest.hookimpl(specname="pytest_pycollect_makeitem",
                     hookwrapper=True)
    def pytest_a_filter(self, collector, name, obj):
        outcome = yield
        if name == "test_parameter":
            items = outcome.get_result()
            if isinstance(items, list):
                kept = [item for item in items
                        if getattr(item, "callspec", None) is None
                        or item.callspec.params.get("x") != 1]
                _event("filter_called",
                       generated=[item.name for item in items],
                       kept=[item.name for item in kept])
                outcome.force_result(kept)

    @pytest.hookimpl(specname="pytest_collection_finish",
                     tryfirst=True)
    def pytest_b_release(self, session):
        session.config.pluginmanager.unregister(self)
        _event("unregistered", remains_registered=(
            session.config.pluginmanager.is_registered(self)))

    @pytest.hookimpl(specname="pytest_configure")
    def pytest_z_invalid_signature(self, not_a_pytest_argument):
        pass


def pytest_sessionstart(session):
    plugin = PartialRegistrationPlugin()
    try:
        session.config.pluginmanager.register(
            plugin, "partial_registration")
    except pluggy.PluginValidationError as exc:
        manager = session.config.pluginmanager
        _event("registration_exception_caught",
               error_type=type(exc).__name__,
               remains_registered=manager.is_registered(plugin),
               active_filter=any(
                   impl.plugin is plugin for impl in
                   manager.hook.pytest_pycollect_makeitem
                   .get_hookimpls()))
    else:
        raise AssertionError("probe expected validation failure")
