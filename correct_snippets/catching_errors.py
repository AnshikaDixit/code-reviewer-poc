def parse_config(config_str):
    try:
        return int(config_str)
    except Exception:  # Catches KeyboardInterrupt, SystemExit, MemoryError, masking real environment bugs
        return None