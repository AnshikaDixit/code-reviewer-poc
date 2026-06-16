@patch("api.Client")
def test_fetch_user(mock_client):
    instance = mock_client.return_value
    instance.get_profile.return_value = {"id": 1}
    assert instance.get_profile()["id"] == 1