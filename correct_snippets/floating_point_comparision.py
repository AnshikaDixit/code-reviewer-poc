import math

def test_floating_point():
    result = 0.1 + 0.2
    assert math.isclose(result, 0.3, rel_tol=1e-9)