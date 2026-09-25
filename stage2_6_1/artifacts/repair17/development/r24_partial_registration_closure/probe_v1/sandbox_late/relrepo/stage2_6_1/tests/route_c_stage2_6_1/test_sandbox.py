# sandbox probe module (one param instance intentionally fails)
import pytest


def test_probe_plain_ok():
    assert True


@pytest.mark.parametrize("x", [0, 1, 2])
def test_parameter(x):
    assert x != 1
