# sandbox canonical test module (generated)
import pytest


def test_plain_ok():
    assert True


@pytest.mark.parametrize("x", [0, 1, 2])
def test_parameter(x):
    assert x in (0, 1, 2)


@pytest.fixture(params=["fa", "fb"])
def fixture_param(request):
    return request.param


def test_fixture_param(fixture_param):
    assert fixture_param in ("fa", "fb")


def test_generated(gen_param):
    assert gen_param in ("g1", "g2")
