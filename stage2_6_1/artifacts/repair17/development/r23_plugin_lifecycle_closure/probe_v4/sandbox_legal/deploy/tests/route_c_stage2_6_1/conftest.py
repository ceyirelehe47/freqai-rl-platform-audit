# sandbox conftest (generated)


def pytest_generate_tests(metafunc):
    if "gen_param" in metafunc.fixturenames:
        metafunc.parametrize("gen_param", ["g1", "g2"])
