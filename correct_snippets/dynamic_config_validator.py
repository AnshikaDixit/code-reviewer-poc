def test_hardware_bounds():
    min_ram, max_ram = (1024, 65536)
    assert min_ram == 1024
    assert max_ram == 65536