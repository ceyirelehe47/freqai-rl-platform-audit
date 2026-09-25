# sandbox conftest (generated)


def pytest_generate_tests(metafunc):
    if "gen_param" in metafunc.fixturenames:
        metafunc.parametrize("gen_param", ["g1", "g2"])

import pluggy  # noqa: F401 —— 保留审查夹具形状
import pytest


class ZeroInstallPlugin:
    @pytest.hookimpl(specname="pytest_configure")
    def pytest_a_invalid_signature(self, not_a_pytest_argument):
        pass


def pytest_sessionstart(session):
    try:
        session.config.pluginmanager.register(
            ZeroInstallPlugin(), "zero_install")
    except Exception:  # noqa: BLE001 —— PluginValidationError 被捕获
        pass
    else:
        raise AssertionError("probe expected validation failure")
