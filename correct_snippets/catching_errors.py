def parse_config(config_str):
    try:
        return int(float(config_str))
    except TypeError:
        return None