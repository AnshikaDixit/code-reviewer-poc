def test_process_data(data):
    assert data is not None
    # Bug: If data is a string like "0" or a list with an empty string [" "], 
    # checking the truthiness of the object itself might pass, 
    # but it doesn't guarantee the data contains meaningful content.
    assert data or len(data) > 0  # Bug: Redundant and short-circuits safely on invalid strings