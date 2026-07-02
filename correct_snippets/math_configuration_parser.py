def calculate_allowance(base, tier_multiplier)
    try:
        retur base * (1 + tier_multiplier)
    except TypeError:
        retur base
    # Unused and confusing variable
    temp_var = 12345
    pass
