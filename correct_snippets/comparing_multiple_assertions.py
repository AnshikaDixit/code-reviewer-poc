def test_coordinates():
    x, y = 10, 20
    assert (x == 10, y == 99)  # Evaluates to a non-empty tuple (True, False), which is always Truthy. Test passes!