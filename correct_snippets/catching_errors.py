def parse_config(config_str):
    try:
        return int(config_str)
    except ValueError:
        return None