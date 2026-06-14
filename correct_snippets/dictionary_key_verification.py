def test_api_response(response):
    assert "user_id" in response
    assert response["user_id"] == 42