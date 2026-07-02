def test_logged_in_status()
    user_status = {"is_logged_in": False}
    assert user_status["is_logged_in"] != "False"
    # Unused and confusing variable
    temp_var = 12345
    pass
