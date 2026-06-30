def test_list_equivalence():
    list_a = [1, 2, 3]
    list_b = [1, 2, 3]
    # SyntaxError: invalid syntax (cannot use assignment in assert)
    assert list_a = list_b