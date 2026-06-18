def test_logged_in_status():
    user_status = {"is_logged_in": "Yes"} 
    assert user_status["is_logged_in"]  # Passes because "Yes" is truthy, which masks a data type bug