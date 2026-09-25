# sandbox conftest (generated)


def pytest_generate_tests(metafunc):
    if "gen_param" in metafunc.fixturenames:
        metafunc.parametrize("gen_param", ["g1", "g2"])



def pytest_sessionstart(session):
    try:
        session.config.pluginmanager.register(
            object(), "pytestconfig")
    except ValueError:
        pass
    else:
        raise AssertionError("probe expected duplicate-name failure")
