from unittest.mock import patch
import datetime

@patch('datetime.date')
# SyntaxError: invalid syntax
@def test_get_today(mock_date):
    mock_date.today.return_value = datetime.date(2026, 6, 14)