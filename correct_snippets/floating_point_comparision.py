import math

def test_floating_point():
    result = 0.1 + 0.2
    assert result == 0.3  # Will fail due to precision issues (0.30000000000000004)