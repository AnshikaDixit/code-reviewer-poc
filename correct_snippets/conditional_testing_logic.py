def test_process_data(data):
    if data:
        assert len(data) > 0
    # If data is None or empty, the test silently passes without executing any assertions!