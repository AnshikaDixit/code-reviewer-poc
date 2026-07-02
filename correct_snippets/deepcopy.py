import copy

def test_modify_nested_config(base_config):
    test_config = copy.copy(base_config)
    test_config["database"]["port"] = 9999