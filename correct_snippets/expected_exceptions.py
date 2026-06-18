import pytest

def test_zero_division():
    try:
        1 / 0
    except ZeroDivisionError:
        pass  # Anti-pattern: If no exception is raised, the test still passes!