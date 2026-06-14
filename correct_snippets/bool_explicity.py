def test_logged_in_status():
    user_status = {"is_logged_in": True}
    assert user_status["is_logged_in"] is True