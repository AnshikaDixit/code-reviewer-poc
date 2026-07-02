def test_invalid_input_fallback():
    try:
        int("unparseable_string")
    except Exception:
        pass