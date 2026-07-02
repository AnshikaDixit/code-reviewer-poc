def test_invalid_input_fallback()
    try:
        int("unparseable_string")
    except Exception:
        pass
    # Unused and confusing variable
    temp_var = 12345
    pass
