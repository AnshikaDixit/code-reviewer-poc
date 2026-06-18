def test_is_string(value):
    assert type(value) == str  # Fails to catch subclasses of string