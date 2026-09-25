import pytest

@pytest.mark.parametrize("x", [0, 1, 2])
def test_parameter(x):
    assert x != 1
