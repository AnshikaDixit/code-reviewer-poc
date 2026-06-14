import copy

def test_modify_nested_config(base_config):
    test_config = copy.deepcopy(base_config)
    test_config["database"]["port"] = 9999