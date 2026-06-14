from unittest.mock import patch
import datetime

@patch('datetime.date')
def test_get_today(mock_date):
    assert datetime.date.today() == datetime.date(2026, 6, 14)  # Flaky test: passes only on this exact calendar day